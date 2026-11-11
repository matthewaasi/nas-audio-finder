"""NAS Audio Finder: standard-library HTTP server, SQLite cache, FFprobe metadata."""
import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import queue
import secrets
import signal
import sqlite3
import stat
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

FORMATS = {"m4a", "mp3", "flac", "wav", "aac", "ogg", "opus", "aiff", "aif", "wma", "ape"}
STATIC = Path(__file__).parent / "static"


class Cancelled(Exception):
    pass


def probe(path, cancel):
    command = [os.getenv("FFPROBE", "ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a",
               "-show_entries", "stream=duration:format=duration", "-of", "json", str(path)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 60
    try:
        while True:
            if cancel.is_set():
                raise Cancelled()
            if time.monotonic() > deadline:
                raise ValueError("Metadata read timed out after 60 seconds")
            try:
                output, error = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise ValueError(error.decode(errors="replace")[-1000:] or "FFprobe failed")
        data = json.loads(output)
        streams = data.get("streams", [])
        if not streams:
            raise ValueError("No audio track found")
        values = []
        for stream in streams:
            try:
                value = float(stream.get("duration", 0))
                if math.isfinite(value) and value > 0:
                    values.append(value)
            except (ValueError, TypeError):
                pass
        if not values:
            try:
                value = float(data.get("format", {}).get("duration", 0))
                if math.isfinite(value) and value > 0:
                    values.append(value)
            except (ValueError, TypeError):
                pass
        if not values:
            raise ValueError("No positive audio duration available")
        return max(values)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def signature(info):
    return (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino)


class Finder:
    def __init__(self, media, config, duration_reader=probe):
        self.media = Path(media).resolve()
        self.config = Path(config)
        self.config.mkdir(parents=True, exist_ok=True)
        self.reader = duration_reader
        self.lock = threading.RLock()
        self.db_lock = threading.Lock()
        self.db = sqlite3.connect(self.config / "durations.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS durations(path TEXT PRIMARY KEY, size INTEGER, modified INTEGER, seconds REAL)")
        self.db.commit()
        self.token = secrets.token_urlsafe(32)
        self.cancel = threading.Event()
        self.thread = None
        self.results = {}
        self.errors = []
        self.confirmations = {}
        self.settings = {"folder": "", "days": 7, "minimum": 25, "maximum": 35,
                         "workers": 4, "formats": ["m4a", "mp3", "flac", "wav"]}
        self.progress = {"phase": "idle", "message": "Ready", "files": 0, "folders": 0,
                         "recent": 0, "read": 0, "cached": 0, "matches": 0, "errors": 0,
                         "listing_seconds": 0, "duration_seconds": 0, "elapsed": 0,
                         "deleted": 0, "delete_failed": 0}
        self.started = None

    def busy(self):
        return self.progress["phase"] in ("scanning", "cancelling", "deleting")

    def path(self, relative):
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("Use a folder relative to the mounted music root")
        candidate = self.media / raw
        current = self.media
        for part in raw.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symbolic links are excluded")
        resolved = candidate.resolve()
        if resolved != self.media and self.media not in resolved.parents:
            raise ValueError("Path is outside the music root")
        return resolved

    def error(self, path, error, deletion=False):
        with self.lock:
            self.progress["errors"] += 1
            if deletion:
                self.progress["delete_failed"] += 1
            if len(self.errors) < 2000:
                self.errors.append({"path": str(path), "error": str(error)})

    def state(self):
        with self.lock:
            progress = dict(self.progress)
            if self.started and self.busy():
                progress["elapsed"] = time.monotonic() - self.started
            return {"progress": progress, "settings": self.settings, "root": str(self.media),
                    "formats": sorted(FORMATS), "csrf": self.token, "errors": list(self.errors[-100:])}

    def start(self, settings):
        with self.lock:
            if self.busy():
                raise ValueError("Wait for the current operation to finish")
            root = self.path(str(settings.get("folder", "")).strip())
            if not root.is_dir():
                raise ValueError("Music folder does not exist; check the /music volume mapping")
            days = float(settings.get("days", 7))
            low = float(settings.get("minimum", 25))
            high = float(settings.get("maximum", 35))
            workers = int(settings.get("workers", 4))
            formats = settings.get("formats", [])
            if not all(math.isfinite(v) for v in (days, low, high)) or not (0 <= days <= 36500 and 0 <= low <= high <= 604800):
                raise ValueError("Invalid date or duration range")
            if not 1 <= workers <= 32:
                raise ValueError("Readers must be between 1 and 32")
            if not isinstance(formats, list) or not formats or any(f not in FORMATS for f in formats):
                raise ValueError("Select at least one supported audio format")
            self.settings = dict(folder=str(root.relative_to(self.media)) if root != self.media else "",
                                 days=days, minimum=low, maximum=high, workers=workers, formats=sorted(set(formats)))
            self.settings.update(self.extra_settings(settings))
            self.results.clear()
            self.errors.clear()
            self.confirmations.clear()
            for key in self.progress:
                if isinstance(self.progress[key], (int, float)):
                    self.progress[key] = 0
            self.progress.update(phase="scanning", message="Scanning local files")
            self.started = time.monotonic()
            self.cancel.clear()
            self.scan_start()
            self.thread = threading.Thread(target=self.scan, args=(root, dict(self.settings)), daemon=True)
            self.thread.start()

    def scan(self, root, settings):
        work = queue.Queue(maxsize=settings["workers"] * 8)
        now = time.time()
        cutoff = now - settings["days"] * 86400 if settings["days"] else float("-inf")

        def consume():
            while True:
                item = work.get()
                try:
                    if item is None:
                        return
                    if not self.cancel.is_set():
                        self.inspect(*item, settings=settings)
                finally:
                    work.task_done()

        workers = [threading.Thread(target=consume, daemon=True) for _ in range(settings["workers"])]
        for worker in workers:
            worker.start()
        fatal = None
        try:
            pending = [root]
            while pending and not self.cancel.is_set():
                directory = pending.pop()
                with self.lock:
                    self.progress["folders"] += 1
                try:
                    begin = time.monotonic()
                    try:
                        with os.scandir(directory) as iterator:
                            entries = list(iterator)
                    finally:
                        with self.lock:
                            self.progress["listing_seconds"] += time.monotonic() - begin
                    for entry in entries:
                        if self.cancel.is_set():
                            break
                        begin = time.monotonic()
                        item = None
                        try:
                            if entry.is_symlink() or self.exclude(Path(entry.path)):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower().lstrip(".") in settings["formats"]:
                                # Windows DirEntry.stat may report zero inode/device;
                                # use a full stat there so change checks use stable IDs.
                                info = os.stat(entry.path, follow_symlinks=False) if os.name == "nt" else entry.stat(follow_symlinks=False)
                                with self.lock:
                                    self.progress["files"] += 1
                                if cutoff <= info.st_mtime <= now:
                                    with self.lock:
                                        self.progress["recent"] += 1
                                    item = (str(Path(entry.path).relative_to(self.media)), signature(info))
                        except OSError as error:
                            self.error(entry.path, error)
                        finally:
                            with self.lock:
                                self.progress["listing_seconds"] += time.monotonic() - begin
                        if item:
                            while not self.cancel.is_set():
                                try:
                                    work.put(item, timeout=0.2)
                                    break
                                except queue.Full:
                                    continue
                except OSError as error:
                    self.error(directory, error)
        except Exception as error:
            fatal = str(error)
            self.error(root, error)
        finally:
            for _ in workers:
                work.put(None)
            work.join()
            for worker in workers:
                worker.join()
            try:
                with self.db_lock:
                    self.db.commit()
            except sqlite3.Error as error:
                self.error("Duration cache", error)
            with self.lock:
                self.progress["elapsed"] = time.monotonic() - self.started
                self.progress["phase"] = "failed" if fatal else "cancelled" if self.cancel.is_set() else "complete"
                self.progress["message"] = fatal or ("Cancelled; partial results retained" if self.cancel.is_set() else "Scan complete")
            self.scan_finish()

    def extra_settings(self, settings): return {}
    def scan_start(self): pass
    def scan_finish(self): pass
    def exclude(self, path): return False

    def inspect(self, relative, original, settings):
        try:
            path = self.path(relative)
            with self.db_lock:
                row = self.db.execute("SELECT size,modified,seconds FROM durations WHERE path=?", (relative,)).fetchone()
            if row and tuple(row[:2]) == original[:2] and row[2] > 0:
                duration = row[2]
                with self.lock:
                    self.progress["cached"] += 1
            else:
                begin = time.monotonic()
                try:
                    duration = self.reader(path, self.cancel)
                    if not math.isfinite(duration) or duration <= 0:
                        raise ValueError("Invalid audio duration")
                    if signature(path.stat()) != original:
                        raise ValueError("File changed while reading metadata; scan again")
                finally:
                    with self.lock:
                        self.progress["duration_seconds"] += time.monotonic() - begin
                with self.db_lock:
                    self.db.execute("INSERT OR REPLACE INTO durations VALUES(?,?,?,?)", (relative, original[0], original[1], duration))
                with self.lock:
                    self.progress["read"] += 1
                    count = self.progress["read"]
                if count % 100 == 0:
                    with self.db_lock:
                        self.db.commit()
            if settings["minimum"] <= duration <= settings["maximum"] and not self.cancel.is_set():
                entry = {"id": secrets.token_hex(12), "path": relative, "name": Path(relative).name,
                         "format": Path(relative).suffix.lstrip(".").upper(), "modified": original[1] / 1e9,
                         "size": original[0], "duration": duration, "signature": original}
                with self.lock:
                    self.results[entry["id"]] = entry
                    self.progress["matches"] = len(self.results)
        except Cancelled:
            pass
        except Exception as error:
            self.error(relative, error)

    def rows(self, search="", sort="path", reverse=False):
        if sort not in {"path", "duration", "modified", "size", "format", "bitrate", "sample_rate", "artist", "album", "codec", "health", "duplicate"}:
            raise ValueError("Invalid sort column")
        with self.lock:
            rows = list(self.results.values())
        if search:
            rows = [r for r in rows if search.casefold() in r["path"].casefold()]
        return sorted(rows, key=lambda r: (r.get(sort) is None, r.get(sort, "").casefold() if isinstance(r.get(sort, ""), str) else r.get(sort) or 0, r["path"]), reverse=reverse)

    def stop(self):
        with self.lock:
            if self.progress["phase"] == "scanning":
                self.cancel.set()
                self.progress.update(phase="cancelling", message="Cancelling metadata reads...")

    def deletion_preview(self, ids):
        with self.lock:
            if self.busy():
                raise ValueError("Finish or cancel scanning before deleting")
            if not isinstance(ids, list) or not ids:
                raise ValueError("Select files to delete")
            ids = list(dict.fromkeys(ids))
            if any(i not in self.results for i in ids):
                raise ValueError("Results changed; refresh your selection")
            nonce = secrets.token_urlsafe(24)
            self.confirmations = {nonce: (time.monotonic() + 120, ids)}
            return {"confirmation": nonce, "count": len(ids), "paths": [self.results[i]["path"] for i in ids]}

    def delete(self, nonce):
        with self.lock:
            if self.busy():
                raise ValueError("Another operation is running")
            saved = self.confirmations.pop(nonce, None)
            if not saved or saved[0] < time.monotonic():
                raise ValueError("Confirmation expired; review the selection again")
            entries = [self.results[i] for i in saved[1] if i in self.results]
            self.errors.clear()
            self.progress.update(phase="deleting", message="Deleting confirmed files", deleted=0, delete_failed=0, errors=0)
            self.started = time.monotonic()
            self.thread = threading.Thread(target=self.delete_entries, args=(entries,), daemon=True)
            self.thread.start()

    def delete_entries(self, entries):
        for entry in entries:
            try:
                path = self.path(entry["path"])
                current = path.lstat()
                if not stat.S_ISREG(current.st_mode) or signature(current) != tuple(entry["signature"]):
                    raise ValueError("File changed since scanning; rescan before deleting")
                path.unlink()
                with self.db_lock:
                    self.db.execute("DELETE FROM durations WHERE path=?", (entry["path"],))
                with self.lock:
                    self.results.pop(entry["id"], None)
                    self.progress["deleted"] += 1
            except Exception as error:
                self.error(entry["path"], error, deletion=True)
        try:
            with self.db_lock:
                self.db.commit()
        except Exception as error:
            self.error("Duration cache", error)
        with self.lock:
            self.progress.update(phase="complete", message="Deletion complete", matches=len(self.results),
                                 elapsed=time.monotonic() - self.started)

    def shutdown(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=65)
        with self.db_lock:
            self.db.commit()
            self.db.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "NasAudioFinder/1.0"

    @property
    def app(self):
        return self.server.finder

    def log_message(self, fmt, *args):
        # Do not log the optional Basic Authorization header or arbitrary query strings.
        print("%s %s" % (self.address_string(), fmt % args), flush=True)

    def authorized(self):
        password = os.getenv("APP_PASSWORD", "")
        if not password:
            return True
        expected = "Basic " + base64.b64encode(("admin:" + password).encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="NAS Audio Finder"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def send(self, status, data, content_type="application/json", headers=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.authorized():
            return
        try:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            get = lambda key, default="": query.get(key, [default])[0]
            extra = self.extra_get(parsed.path, get)
            if extra is not None:
                return self.send(200, extra)
            if parsed.path == "/api/state":
                return self.send(200, self.app.state())
            if parsed.path in ("/api/results", "/api/selection", "/api/export"):
                rows = self.app.rows(get("search"), get("sort", "path"), get("reverse") == "1")
                if get("duplicates") == "1":
                    rows = [r for r in rows if r.get("duplicate")]
                if parsed.path == "/api/selection":
                    return self.send(200, {"ids": [r["id"] for r in rows]})
                if parsed.path == "/api/export":
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(["Path relative to /music", "Modified UTC", "Duration seconds", "Bytes", "Format", "Codec", "Bitrate bps", "Sample rate Hz", "Artist", "Album", "Health", "Duplicate group"])
                    for r in rows:
                        # Prevent spreadsheet formula evaluation from file names.
                        path = r["path"]
                        if path[:1] in ("=", "+", "-", "@", "\t", "\r"):
                            path = "'" + path
                        values=[path, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["modified"])), r["duration"], r["size"], r["format"], r.get("codec", ""), r.get("bitrate", ""), r.get("sample_rate", ""), r.get("artist", ""), r.get("album", ""), r.get("health", ""), r.get("duplicate", "")]
                        writer.writerow([("'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r") else v) for v in values])
                    return self.send(200, output.getvalue().encode("utf-8-sig"), "text/csv", {"Content-Disposition": 'attachment; filename="audio-results.csv"'})
                offset = max(0, int(get("offset", "0")))
                limit = max(1, min(200, int(get("limit", "100"))))
                clean = [{k: v for k, v in row.items() if k not in ("signature", "fingerprint", "quarantine_signature")} for row in rows[offset:offset + limit]]
                return self.send(200, {"rows": clean, "total": len(rows)})
            if parsed.path == "/api/errors":
                with self.app.lock:
                    errors = list(self.app.errors)
                return self.send(200, errors, headers={"Content-Disposition": 'attachment; filename="audio-errors.json"'})
            assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "application/javascript"), "/style.css": ("style.css", "text/css")}
            if parsed.path in assets:
                name, mime = assets[parsed.path]
                return self.send(200, (STATIC / name).read_bytes(), mime)
            self.send(404, {"error": "Not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError) as error:
            self.send(400, {"error": str(error)})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                raise ValueError("Cross-origin request refused")
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self.app.token):
                raise ValueError("Session changed; reload the page")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 20_000_000:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            route = urlsplit(self.path).path
            if route == "/api/scan":
                self.app.start(data)
                result = {"ok": True}
            elif route == "/api/cancel":
                self.app.stop()
                result = {"ok": True}
            elif route == "/api/delete-preview":
                result = self.app.deletion_preview(data.get("ids"))
            elif route == "/api/delete":
                self.app.delete(data.get("confirmation", ""))
                result = {"ok": True}
            else:
                result = self.extra_post(route, data)
                if result is None:
                    return self.send(404, {"error": "Not found"})
            self.send(200, result)
        except (ValueError, TypeError, OSError) as error:
            self.send(400, {"error": str(error)})

    def extra_get(self, route, get): return None
    def extra_post(self, route, data): return None


def main():
    from library import LibraryFinder, LibraryHandler
    finder = LibraryFinder(os.getenv("MEDIA_ROOT", "/music"), os.getenv("CONFIG_ROOT", "/config"))
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), LibraryHandler)
    server.finder = finder
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("NAS Audio Finder listening on port %s; music root %s" % (server.server_port, finder.media), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        finder.shutdown()


if __name__ == "__main__":
    main()
