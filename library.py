"""Library management, persistent scans, scheduling, health and duplicate analysis."""
import array
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time

from authenticity import analyze, ANALYSIS_VERSION

from app import Finder, Handler, Cancelled, signature

VERSION = "2.1.0"


def command(args, cancel, timeout=60):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel.is_set():
                raise Cancelled()
            if time.monotonic() > deadline:
                raise ValueError("Audio analysis timed out")
            try:
                output, error = process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise ValueError(error.decode(errors="replace")[-1500:] or "Audio analysis failed")
        return output, error
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def numeric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else 0
    except (ValueError, TypeError):
        return 0


def metadata(path, cancel):
    output, _ = command([os.getenv("FFPROBE", "ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "a", "-show_entries",
        "stream=duration,codec_name,bit_rate,sample_rate,channels:stream_tags=artist,album,title:format=duration,bit_rate:format_tags=artist,album,title",
        "-of", "json", str(path)], cancel)
    data = json.loads(output)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("No audio stream found")
    stream = streams[0]
    container = data.get("format", {})
    duration = max((numeric(s.get("duration")) for s in streams), default=0) or numeric(container.get("duration"))
    tags = {k.lower(): str(v) for k, v in container.get("tags", {}).items()}
    tags.update({k.lower(): str(v) for k, v in stream.get("tags", {}).items()})
    return {"duration": duration, "codec": stream.get("codec_name", "unknown"),
            "bitrate": int(numeric(stream.get("bit_rate")) or numeric(container.get("bit_rate"))),
            "sample_rate": int(numeric(stream.get("sample_rate"))), "channels": int(numeric(stream.get("channels"))),
            "artist": tags.get("artist", ""), "album": tags.get("album", ""), "title": tags.get("title", ""),
            "health": "zero-duration" if duration <= 0 else "metadata-ok"}


def decode_health(path, cancel):
    _, error = command([os.getenv("FFMPEG", "ffmpeg"), "-v", "error", "-xerror", "-nostdin",
        "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn", "-threads", "1", "-f", "null", "-"], cancel, 3600)
    if error.strip():
        raise ValueError(error.decode(errors="replace")[-1500:])


def file_hash(path, cancel):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel.is_set():
                raise Cancelled()
            h.update(block)
    return h.hexdigest()


def pcm_fingerprint(data, cancel):
    """Compact, perceptual spectral signatures, independent of tags/container/codec.

    Compare band-energy ordering per 256ms frame. Silence is excluded. Near
    matches are candidates for manual review, never proof of identical content.
    """
    pcm = array.array("h")
    pcm.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder != "little":
        pcm.byteswap()
    frequencies = (100, 150, 220, 330, 500, 750, 1100, 1600, 2400, 3200)
    coefficients = [2 * math.cos(2 * math.pi * f / 8000) for f in frequencies]
    result = []
    for start in range(0, len(pcm) - 2047, 2048):
        if cancel.is_set():
            raise Cancelled()
        block = pcm[start:start + 2048]
        if sum(x*x for x in block) / len(block) < 100:
            result.append(-1)
            continue
        powers = []
        for coefficient in coefficients:
            a = b = 0.0
            for sample in block:
                value = sample + coefficient * a - b
                b, a = a, value
            powers.append(max(0, a*a + b*b - coefficient*a*b))
        code = 0
        for i in range(len(powers) - 1):
            if powers[i] > powers[i+1]:
                code |= 1 << i
        result.append(code)
    return result


def fingerprint(path, cancel):
    output, _ = command([os.getenv("FFMPEG", "ffmpeg"), "-v", "error", "-nostdin",
        "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn", "-t", "120",
        "-threads", "1", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"], cancel, 300)
    return pcm_fingerprint(output, cancel)


def similar(left, right, threshold=.1):
    best = 1.0
    for shift in range(-2, 3):
        a = left[max(0, shift):]
        b = right[max(0, -shift):]
        pairs = [(x, y) for x, y in zip(a, b) if x >= 0 and y >= 0]
        if len(pairs) < 40:
            continue
        # Avoid grouping featureless single tones solely by their common ordering.
        if len(set(x for x, _ in pairs)) < 6 or len(set(y for _, y in pairs)) < 6:
            continue
        distance = sum((x ^ y).bit_count() for x, y in pairs) / (9 * len(pairs))
        best = min(best, distance)
    return best <= threshold


class LibraryFinder(Finder):
    def __init__(self, media, config, metadata_reader=metadata, deep_reader=decode_health,
                 fingerprint_reader=fingerprint, scheduler=True):
        super().__init__(media, config)
        self.metadata_reader = metadata_reader
        self.deep_reader = deep_reader
        self.fingerprint_reader = fingerprint_reader
        self.advanced_confirmations = {}
        self.scan_id = None
        self.shutdown_event = threading.Event()
        self.quarantine = Path(os.getenv("QUARANTINE_ROOT", str(self.media / ".nas-audio-finder-quarantine"))).absolute()
        if self.quarantine.is_symlink():
            raise ValueError("Quarantine root must not be a symbolic link")
        self.quarantine = self.quarantine.resolve()
        if self.quarantine == self.media or self.quarantine in self.media.parents or self.quarantine == self.config.resolve():
            raise ValueError("Quarantine must be a dedicated subfolder or separate volume")
        with self.db_lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS library_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scan_history(id TEXT PRIMARY KEY,started REAL,finished REAL,settings TEXT,progress TEXT,errors TEXT);
            CREATE TABLE IF NOT EXISTS scan_results(scan_id TEXT,id TEXT,data TEXT,PRIMARY KEY(scan_id,id));
            CREATE INDEX IF NOT EXISTS scan_results_scan ON scan_results(scan_id);
            CREATE TABLE IF NOT EXISTS audio_metadata(path TEXT PRIMARY KEY,size INTEGER,modified INTEGER,data TEXT);
            CREATE TABLE IF NOT EXISTS quarantine_items(id TEXT PRIMARY KEY,original TEXT,stored TEXT,quarantined REAL,data TEXT,state TEXT,error TEXT);
            """)
            self.db.commit()
        saved = self.kv("last-settings")
        if saved:
            self.settings.update(saved)
        self.schedule = self.kv("schedule") or {"enabled": False, "time": "02:00", "preset": "", "last_run": ""}
        self.retention = self.kv("retention") or {"enabled": False, "days": 30}
        active = self.kv("active-scan")
        if active:
            self.load_history(active, recovering=True)
        self.reconcile_quarantine()
        self.scheduler_thread = None
        if scheduler:
            self.scheduler_thread = threading.Thread(target=self.scheduler_loop, daemon=True)
            self.scheduler_thread.start()

    def kv(self, key, value=None):
        with self.db_lock:
            if value is not None:
                self.db.execute("INSERT OR REPLACE INTO library_settings VALUES(?,?)", (key, json.dumps(value)))
                self.db.commit()
                return value
            row = self.db.execute("SELECT value FROM library_settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def busy(self):
        return super().busy() or self.progress["phase"] in ("quarantining", "restoring", "purging", "duplicates") or bool(self.thread and self.thread.is_alive())

    def exclude(self, path):
        return path == self.quarantine or self.quarantine in path.parents or path == self.config.resolve()

    def extra_settings(self, settings):
        result = {"artist": str(settings.get("artist", "")).strip()[:300],
                  "album": str(settings.get("album", "")).strip()[:300],
                  "codec": str(settings.get("codec", "")).strip().lower()[:100],
                  "deep_check": bool(settings.get("deep_check", False)),
                  "authenticity_check": bool(settings.get("authenticity_check", False)),
                  "duplicates": settings.get("duplicates", "off"), "health_filter": settings.get("health_filter", "any")}
        if result["duplicates"] not in ("off", "exact", "acoustic", "both") or result["health_filter"] not in ("any", "issues", "healthy"):
            raise ValueError("Invalid health or duplicate mode")
        for field in ("bitrate_min", "bitrate_max", "sample_min", "sample_max", "size_min", "size_max", "low_bitrate"):
            raw = settings.get(field, "")
            value = None if raw in (None, "") else float(raw)
            if value is not None and (not math.isfinite(value) or value < 0 or value > 10**15):
                raise ValueError("Invalid metadata range: " + field)
            result[field] = value
        for name in ("bitrate", "sample", "size"):
            lo, hi = result[name + "_min"], result[name + "_max"]
            if lo is not None and hi is not None and lo > hi:
                raise ValueError("Minimum exceeds maximum: " + name)
        return result

    def scan_start(self):
        self.scan_id = secrets.token_hex(12)
        self.advanced_confirmations.clear()
        with self.db_lock:
            self.db.execute("INSERT INTO scan_history VALUES(?,?,?,?,?,?)", (self.scan_id, time.time(), None,
                json.dumps(self.settings), json.dumps(self.progress), "[]"))
            self.db.commit()
        self.kv("last-settings", self.settings)
        self.kv("active-scan", self.scan_id)

    def store_result(self, entry):
        with self.lock:
            self.results[entry["id"]] = entry
            self.progress["matches"] = len(self.results)
        with self.db_lock:
            self.db.execute("INSERT OR REPLACE INTO scan_results VALUES(?,?,?)", (self.scan_id, entry["id"], json.dumps(entry)))

    def inspect(self, relative, original, settings):
        entry = {"id": secrets.token_hex(12), "path": relative, "name": Path(relative).name,
            "format": Path(relative).suffix.lstrip(".").upper(), "modified": original[1] / 1e9,
            "size": original[0], "signature": original, "duplicate": "", "duration": None,
            "health": "unreadable", "health_detail": "", "bitrate": 0, "sample_rate": 0,
            "codec": "", "artist": "", "album": "", "fingerprint": [], "sha256": "", "authenticity": "not-scanned", "authenticity_detail": ""}
        try:
            path = self.path(relative)
            with self.db_lock:
                saved = self.db.execute("SELECT size,modified,data FROM audio_metadata WHERE path=?", (relative,)).fetchone()
            info = json.loads(saved[2]) if saved and tuple(saved[:2]) == original[:2] else None
            begin = time.monotonic()
            try:
                if info:
                    with self.lock:
                        self.progress["cached"] += 1
                else:
                    info = self.metadata_reader(path, self.cancel)
                    with self.lock:
                        self.progress["read"] += 1
                entry.update(info)
                entry["health"] = "zero-duration" if not entry["duration"] else "metadata-ok"
                threshold = settings.get("low_bitrate")
                # Lossless/PCM encodings are not judged by lossy bitrate thresholds.
                lossless = entry["codec"] in ("flac", "alac", "ape", "wavpack") or entry["codec"].startswith("pcm_")
                if threshold and entry["health"] == "metadata-ok" and not lossless and entry["bitrate"] and entry["bitrate"] < threshold * 1000:
                    entry["health"] = "low-bitrate"
                if settings["deep_check"]:
                    try:
                        self.deep_reader(path, self.cancel)
                        if entry["health"] == "metadata-ok":
                            entry["health"] = "decode-ok"
                    except Cancelled:
                        raise
                    except Exception as error:
                        entry.update(health="decode-error", health_detail=str(error))
                if self.matches(entry, settings):
                    mode = settings["duplicates"]
                    if mode in ("exact", "both"):
                        entry["sha256"] = info.get("sha256") or file_hash(path, self.cancel)
                    if mode in ("acoustic", "both") and entry["duration"]:
                        entry["fingerprint"] = info.get("fingerprint") or self.fingerprint_reader(path, self.cancel)
                if settings.get("authenticity_check") and self.matches(entry, settings):
                    analysis = info.get("authenticity_analysis")
                    if not analysis or analysis.get("version") != ANALYSIS_VERSION:
                        try:
                            analysis = analyze(path, entry, self.cancel, command)
                        except Cancelled:
                            raise
                        except Exception as error:
                            analysis = {"status": "analysis-error", "detail": str(error)}
                    entry.update(authenticity=analysis["status"], authenticity_detail=analysis["detail"])
                    # Retry failures on the next scan rather than caching them.
                    if analysis["status"] != "analysis-error":
                        info["authenticity_analysis"] = analysis
                if signature(path.stat()) != tuple(original):
                    raise ValueError("File changed during analysis; scan again")
                # Health status depends on this run; only raw metadata and stable expensive results are cached.
                cached = dict(info)
                for field in ("sha256", "fingerprint"):
                    if entry[field]:
                        cached[field] = entry[field]
                with self.db_lock:
                    self.db.execute("INSERT OR REPLACE INTO audio_metadata VALUES(?,?,?,?)", (relative, original[0], original[1], json.dumps(cached)))
            finally:
                with self.lock:
                    self.progress["duration_seconds"] += time.monotonic() - begin
            if self.matches(entry, settings) and not self.cancel.is_set():
                self.store_result(entry)
        except Cancelled:
            pass
        except Exception as error:
            self.error(relative, error)
            entry.update(health="unreadable", health_detail=str(error))
            # Surface problematic candidates even when their duration cannot be trusted.
            if settings["health_filter"] != "healthy" and not self.cancel.is_set():
                self.store_result(entry)

    def matches(self, entry, settings):
        issue = entry["health"] not in ("metadata-ok", "decode-ok")
        health = settings["health_filter"]
        if health == "issues" and not issue or health == "healthy" and issue:
            return False
        if not issue or health != "issues":
            duration = entry.get("duration")
            if duration is None or not settings["minimum"] <= duration <= settings["maximum"]:
                return False
        for field in ("artist", "album", "codec"):
            if settings[field].casefold() not in str(entry.get(field, "")).casefold():
                return False
        for name, value in (("bitrate", entry["bitrate"] / 1000), ("sample", entry["sample_rate"]), ("size", entry["size"] / 1048576)):
            lo, hi = settings[name+"_min"], settings[name+"_max"]
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                return False
        return True

    def group_duplicates(self):
        rows = list(self.results.values())
        parent = {r["id"]: r["id"] for r in rows}
        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key
        exact = {}
        for entry in rows:
            if entry.get("sha256"):
                previous = exact.setdefault(entry["sha256"], entry["id"])
                parent[find(entry["id"])] = find(previous)
        acoustic = sorted((r for r in rows if r.get("fingerprint") and r.get("duration")), key=lambda r: r["duration"])
        # Bounded candidate search prevents quadratic comparisons in large libraries.
        buckets = {}
        for entry in acoustic:
            if self.cancel.is_set():
                break
            codes = entry["fingerprint"]
            keys = []
            candidates = {}
            for segment in range(8):
                chunk = [x for x in codes[segment::8] if x >= 0]
                if not chunk:
                    continue
                code = sum((1 << bit) for bit in range(9) if sum(bool(x & (1 << bit)) for x in chunk) > len(chunk)/2)
                for duration_bucket in range(int(entry["duration"])-2, int(entry["duration"])+3):
                    key = (duration_bucket, segment, code)
                    for other in buckets.get(key, []):
                        candidates[other["id"]] = other
                keys.append((int(entry["duration"]), segment, code))
            for other in list(candidates.values())[-200:]:
                if abs(other["duration"] - entry["duration"]) > max(1, entry["duration"] * .01):
                    continue
                if find(entry["id"]) != find(other["id"]) and similar(entry["fingerprint"], other["fingerprint"]):
                    parent[find(other["id"])] = find(entry["id"])
            for key in keys:
                buckets.setdefault(key, []).append(entry)
                if len(buckets[key]) > 200:
                    buckets[key].pop(0)
        groups = {}
        for entry in rows:
            groups.setdefault(find(entry["id"]), []).append(entry)
        counter = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            counter += 1
            kind = "exact" if len({r.get("sha256") for r in members}) == 1 and members[0].get("sha256") else "similar"
            for entry in members:
                entry["duplicate"] = kind + "-" + str(counter)
                self.store_result(entry)

    def checkpoint(self):
        with self.lock:
            if not self.scan_id:
                return
            progress, errors = dict(self.progress), list(self.errors)
            if self.started and self.busy():
                progress["elapsed"] = time.monotonic() - self.started
        with self.db_lock:
            self.db.execute("UPDATE scan_history SET progress=?,errors=? WHERE id=?", (json.dumps(progress), json.dumps(errors), self.scan_id))
            self.db.commit()

    def scan_finish(self):
        try:
            if self.settings.get("duplicates") != "off" and not self.cancel.is_set():
                with self.lock:
                    self.progress.update(phase="duplicates", message="Comparing duplicate candidates")
                self.group_duplicates()
                with self.lock:
                    self.progress.update(phase="cancelled" if self.cancel.is_set() else "complete", message="Scan complete; duplicate candidates require review")
            with self.lock:
                self.progress["elapsed"] = time.monotonic() - self.started
            self.checkpoint()
            with self.db_lock:
                self.db.execute("UPDATE scan_history SET finished=? WHERE id=?", (time.time(), self.scan_id))
                keep = max(1, min(1000, int(os.getenv("HISTORY_LIMIT", "30"))))
                old = self.db.execute("SELECT id FROM scan_history ORDER BY started DESC LIMIT -1 OFFSET ?", (keep,)).fetchall()
                for (ident,) in old:
                    if ident != self.scan_id:
                        self.db.execute("DELETE FROM scan_results WHERE scan_id=?", (ident,))
                        self.db.execute("DELETE FROM scan_history WHERE id=?", (ident,))
                self.db.commit()
        except Exception as error:
            self.error("Scan history", error)
            with self.lock:
                self.progress.update(phase="failed", message="Analysis failed: " + str(error))

    def history(self):
        with self.db_lock:
            rows = self.db.execute("SELECT id,started,finished,settings,progress FROM scan_history ORDER BY started DESC LIMIT 100").fetchall()
        return [{"id": r[0], "started": r[1], "finished": r[2], "settings": json.loads(r[3]), "progress": json.loads(r[4])} for r in rows]

    def load_history(self, ident, recovering=False):
        with self.lock:
            if self.busy() and not recovering:
                raise ValueError("Finish the current operation first")
            with self.db_lock:
                row = self.db.execute("SELECT settings,progress,errors,finished FROM scan_history WHERE id=?", (ident,)).fetchone()
                if not row:
                    return False
                entries = self.db.execute("SELECT data FROM scan_results WHERE scan_id=?", (ident,)).fetchall()
            self.results = {entry["id"]: entry for (text,) in entries for entry in [json.loads(text)]}
            self.settings.update(json.loads(row[0]))
            self.progress.update(json.loads(row[1]))
            self.progress["matches"] = len(self.results)
            self.errors = json.loads(row[2])
            if self.progress["phase"] in ("scanning", "cancelling", "duplicates", "deleting", "quarantining", "restoring", "purging"):
                self.progress.update(phase="interrupted", message="Previous operation interrupted; persisted results restored")
            self.scan_id = ident
            self.confirmations.clear()
            self.advanced_confirmations.clear()
            self.kv("active-scan", ident)
            return True

    def presets(self):
        return self.kv("presets") or {}

    def preset(self, data):
        name = str(data.get("name", "")).strip()[:100]
        if not name:
            raise ValueError("Enter a preset name")
        presets = self.presets()
        if data.get("remove"):
            presets.pop(name, None)
        else:
            settings = data.get("settings")
            if not isinstance(settings, dict):
                raise ValueError("Invalid preset settings")
            self.extra_settings(settings)
            try:
                days, low, high = float(settings.get("days", 7)), float(settings.get("minimum", 25)), float(settings.get("maximum", 35))
                workers = int(settings.get("workers", 4))
                if not all(math.isfinite(n) for n in (days, low, high)) or not 0 <= days <= 36500 or not 0 <= low <= high <= 604800 or not 1 <= workers <= 32:
                    raise ValueError("Invalid preset ranges")
                from app import FORMATS
                formats = settings.get("formats", [])
                if not formats or not isinstance(formats, list) or any(f not in FORMATS for f in formats):
                    raise ValueError("Select supported audio formats")
                self.path(str(settings.get("folder", "")))
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid preset: " + str(error)) from None
            presets[name] = settings
        self.kv("presets", presets)
        return {"presets": presets}

    def settings_schedule(self, data):
        clock = str(data.get("time", "02:00"))
        try:
            datetime.datetime.strptime(clock, "%H:%M")
        except ValueError:
            raise ValueError("Use a daily schedule time in HH:MM format") from None
        preset = str(data.get("preset", ""))
        if data.get("enabled") and preset not in self.presets():
            raise ValueError("Select an existing preset for scheduled scans")
        self.schedule.update(enabled=bool(data.get("enabled")), time=clock, preset=preset)
        self.kv("schedule", self.schedule)
        return self.schedule

    def scheduler_tick(self, now=None):
        now = now or datetime.datetime.now(datetime.timezone.utc)
        schedule = self.schedule
        day = now.date().isoformat()
        if schedule["enabled"] and schedule["last_run"] != day and now.strftime("%H:%M") >= schedule["time"]:
            with self.lock:
                if not self.busy():
                    preset = self.presets().get(schedule["preset"])
                    if preset:
                        self.start(preset)
                        schedule["last_run"] = day
                        self.kv("schedule", schedule)
        if self.retention["enabled"]:
            with self.lock:
                if not self.busy():
                    due = [r["id"] for r in self.quarantine_rows() if r["quarantined"] + self.retention["days"] * 86400 <= time.time()]
                    if due:
                        self.run_action("purge", due, automatic=True)

    def scheduler_loop(self):
        while not self.shutdown_event.wait(30):
            try:
                self.checkpoint()
                self.scheduler_tick()
            except Exception as error:
                self.error("Scheduler", error)

    def quarantine_path(self, ident):
        if len(ident) != 24 or any(c not in "0123456789abcdef" for c in ident):
            raise ValueError("Invalid quarantine ID")
        if self.quarantine.is_symlink():
            raise ValueError("Quarantine symlink refused")
        self.quarantine.mkdir(parents=True, exist_ok=True)
        path = self.quarantine / ident
        if path.is_symlink():
            raise ValueError("Quarantined file must not be a symbolic link")
        return path

    def quarantine_rows(self):
        with self.db_lock:
            rows = self.db.execute("SELECT id,original,quarantined,data,state,error FROM quarantine_items WHERE state NOT IN ('restored','purged') ORDER BY quarantined DESC").fetchall()
        return [{"id": r[0], "path": r[1], "quarantined": r[2], "size": json.loads(r[3]).get("size", 0), "state": r[4], "error": r[5]} for r in rows]

    def reconcile_quarantine(self):
        for entry in self.quarantine_rows():
            if entry["state"] == "moving":
                stored = self.quarantine_path(entry["id"])
                source = self.path(entry["path"])
                status = "quarantined" if stored.is_file() and not source.exists() else "needs-review"
                with self.db_lock:
                    row = self.db.execute("SELECT data FROM quarantine_items WHERE id=?", (entry["id"],)).fetchone()
                    data = json.loads(row[0])
                    if status == "quarantined" and (stored.stat().st_size != data["size"] or stored.stat().st_mtime_ns != data["signature"][1]):
                        status = "needs-review"
                    if status == "quarantined":
                        data["quarantine_signature"] = signature(stored.lstat())
                    self.db.execute("UPDATE quarantine_items SET state=?,error=?,data=? WHERE id=?", (status, "Recovered interrupted move; inspect both locations" if status == "needs-review" else "", json.dumps(data), entry["id"]))
                    self.db.commit()

    def preview_action(self, data):
        action = data.get("action")
        if action not in ("quarantine", "restore", "purge"):
            raise ValueError("Invalid file action")
        with self.lock:
            if self.busy():
                raise ValueError("Finish or cancel the current operation first")
            ids = list(dict.fromkeys(data.get("ids", [])))
            available = self.results if action == "quarantine" else {r["id"]: r for r in self.quarantine_rows() if r["state"] == "quarantined"}
            if not ids or any(i not in available for i in ids):
                raise ValueError("Select current files; unresolved quarantine entries require manual inspection")
            nonce = secrets.token_urlsafe(24)
            self.advanced_confirmations = {nonce: (time.monotonic()+120, action, ids)}
            return {"confirmation": nonce, "action": action, "count": len(ids), "paths": [available[i]["path"] for i in ids]}

    def confirm_action(self, nonce):
        with self.lock:
            if self.busy():
                raise ValueError("Another operation is running")
            saved = self.advanced_confirmations.pop(nonce, None)
            if not saved or saved[0] < time.monotonic():
                raise ValueError("Confirmation expired; review the selection again")
            self.run_action(saved[1], saved[2])

    @staticmethod
    def move_exclusive(source, target, expected):
        if target.exists() or target.is_symlink():
            raise ValueError("Destination already exists; nothing was overwritten")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target, follow_symlinks=False)
        except OSError:
            try:
                with source.open("rb") as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1024*1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                shutil.copystat(source, target, follow_symlinks=False)
            except Exception:
                # Never delete a destination another process created.
                raise
        if signature(source.lstat()) != tuple(expected):
            raise ValueError("Source changed during move; both copies retained for manual review")
        source.unlink()

    def run_action(self, action, ids, automatic=False):
        with self.lock:
            if self.busy():
                raise ValueError("Another operation is running")
            self.progress.update(phase={"quarantine":"quarantining", "restore":"restoring", "purge":"purging"}[action],
                message=("Automatic " if automatic else "") + action, deleted=0, delete_failed=0, errors=0)
            self.errors.clear()
            self.started = time.monotonic()
            entries = [dict(self.results[i]) for i in ids] if action == "quarantine" else ids
            self.thread = threading.Thread(target=self.file_action, args=(action, entries), daemon=True)
            self.thread.start()

    def file_action(self, action, entries):
        for entry in entries:
            try:
                if action == "quarantine":
                    source = self.path(entry["path"])
                    if not stat.S_ISREG(source.lstat().st_mode) or signature(source.lstat()) != tuple(entry["signature"]):
                        raise ValueError("File changed since scanning; rescan first")
                    ident = secrets.token_hex(12)
                    target = self.quarantine_path(ident)
                    with self.db_lock:
                        self.db.execute("INSERT INTO quarantine_items VALUES(?,?,?,?,?,?,?)",
                            (ident, entry["path"], str(target), time.time(), json.dumps(entry), "moving", ""))
                        self.db.commit()
                    self.move_exclusive(source, target, entry["signature"])
                    entry["quarantine_signature"] = signature(target.lstat())
                    with self.db_lock:
                        self.db.execute("UPDATE quarantine_items SET state='quarantined',data=? WHERE id=?", (json.dumps(entry), ident))
                        self.db.execute("DELETE FROM scan_results WHERE scan_id=? AND id=?", (self.scan_id, entry["id"]))
                        self.db.commit()
                    with self.lock:
                        self.results.pop(entry["id"], None)
                else:
                    ident = entry
                    with self.db_lock:
                        row = self.db.execute("SELECT original,data,state FROM quarantine_items WHERE id=?", (ident,)).fetchone()
                    if not row or row[2] != "quarantined":
                        raise ValueError("Quarantine item is not ready for this action")
                    data = json.loads(row[1])
                    source = self.quarantine_path(ident)
                    if not stat.S_ISREG(source.lstat().st_mode) or signature(source.lstat()) != tuple(data["quarantine_signature"]):
                        raise ValueError("Quarantined file changed; manual inspection required")
                    if action == "restore":
                        destination = self.path(row[0])
                        self.move_exclusive(source, destination, data["quarantine_signature"])
                    else:
                        source.unlink()
                    with self.db_lock:
                        self.db.execute("UPDATE quarantine_items SET state=?,error='' WHERE id=?", ("restored" if action == "restore" else "purged", ident))
                        self.db.commit()
                with self.lock:
                    self.progress["deleted"] += 1
            except Exception as error:
                self.error(entry.get("path", "quarantine") if isinstance(entry, dict) else entry, error, deletion=True)
        with self.lock:
            self.progress.update(phase="complete", message=action+" complete", matches=len(self.results), elapsed=time.monotonic()-self.started)
        self.checkpoint()

    def delete_entries(self, entries):
        super().delete_entries(entries)
        with self.db_lock:
            remaining = set(self.results)
            for entry in entries:
                if entry["id"] not in remaining:
                    self.db.execute("DELETE FROM scan_results WHERE scan_id=? AND id=?", (self.scan_id, entry["id"]))
            self.db.commit()
        self.checkpoint()

    def stop(self):
        if self.progress["phase"] == "duplicates":
            self.cancel.set()
        else:
            super().stop()

    def state(self):
        result = super().state()
        result.update(version=VERSION, scan_id=self.scan_id, schedule=self.schedule, retention=self.retention,
                      quarantine_root=str(self.quarantine), timezone="UTC", busy=self.busy())
        return result

    def shutdown(self):
        self.shutdown_event.set()
        if self.scheduler_thread:
            self.scheduler_thread.join(5)
        self.stop()
        if self.thread:
            self.thread.join()
        self.checkpoint()
        super().shutdown()


class LibraryHandler(Handler):
    server_version = "NasAudioFinder/2.0"

    def extra_get(self, route, get):
        if route == "/api/presets":
            return {"presets": self.app.presets()}
        if route == "/api/history":
            return {"history": self.app.history()}
        if route == "/api/quarantine":
            return {"rows": self.app.quarantine_rows()}

    def extra_post(self, route, data):
        if route == "/api/preset":
            return self.app.preset(data)
        if route == "/api/schedule":
            return self.app.settings_schedule(data)
        if route == "/api/history/load":
            if not self.app.load_history(data.get("id", "")):
                raise ValueError("Scan history not found")
            return {"ok": True}
        if route == "/api/action-preview":
            return self.app.preview_action(data)
        if route == "/api/action":
            self.app.confirm_action(data.get("confirmation", ""))
            return {"ok": True}
        if route == "/api/retention":
            days = int(data.get("days", 30))
            if not 1 <= days <= 3650:
                raise ValueError("Retention must be 1–3650 days")
            if data.get("enabled") and not data.get("acknowledged"):
                raise ValueError("Acknowledge that expired quarantine files are permanently purged")
            self.app.retention = {"enabled": bool(data.get("enabled")), "days": days}
            self.app.kv("retention", self.app.retention)
            return self.app.retention
