import datetime
import json
import math
import os
from pathlib import Path
import random
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from library import LibraryFinder, LibraryHandler, pcm_fingerprint, similar


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "music"
        self.media.mkdir()
        self.calls = 0
        self.deep_calls = 0
        self.app = self.make_app()

    def reader(self, path, cancel):
        self.calls += 1
        if path.name.startswith("bad"):
            raise ValueError("No audio stream found")
        return dict(duration=0 if path.name.startswith("zero") else 30, codec="aac", bitrate=128000,
                    sample_rate=44100, channels=2, artist="Test artist", album="Test album", title="Song", health="metadata-ok")

    def deep(self, path, cancel):
        self.deep_calls += 1
        if path.name.startswith("corrupt"):
            raise ValueError("Corrupt packet")

    def make_app(self):
        return LibraryFinder(self.media, self.root / "config", self.reader, self.deep, scheduler=False)

    def tearDown(self):
        self.app.shutdown()
        self.temp.cleanup()

    def file(self, name, data=b"audio fixture", age=20):
        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (time.time()-age, time.time()-age))
        return path

    def settings(self, **extra):
        return dict(folder="", days=7, minimum=25, maximum=35, workers=2, formats=["mp3", "m4a", "flac", "wav"], **extra)

    def scan(self, **extra):
        self.app.start(self.settings(**extra))
        self.wait()

    def wait(self):
        self.app.thread.join(10)
        self.assertFalse(self.app.thread.is_alive(), "Operation did not finish")

    def action(self, kind, ids):
        preview = self.app.preview_action(dict(action=kind, ids=ids))
        self.app.confirm_action(preview["confirmation"])
        self.wait()

    def test_metadata_filters_and_cache(self):
        self.file("song.mp3")
        self.scan(artist="TEST", album="album", codec="aac", bitrate_min=120, bitrate_max=150, sample_min=44100)
        self.assertEqual(len(self.app.results), 1)
        self.scan(artist="other")
        self.assertEqual(len(self.app.results), 0)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.app.progress["cached"], 1)

    def test_health_zero_unreadable_low_bitrate_and_decode(self):
        for name in ("good.mp3", "bad.mp3", "zero.mp3", "corrupt.mp3"):
            self.file(name)
        self.scan(health_filter="issues", deep_check=True, low_bitrate=160)
        health = {r["name"]: r["health"] for r in self.app.results.values()}
        self.assertEqual(health["bad.mp3"], "unreadable")
        self.assertEqual(health["zero.mp3"], "zero-duration")
        self.assertEqual(health["good.mp3"], "low-bitrate")
        self.assertEqual(health["corrupt.mp3"], "decode-error")

    def test_presets_history_and_results_survive_restart(self):
        self.file("song.mp3")
        self.app.preset(dict(name="Short tracks", settings=self.settings()))
        self.scan()
        scan_id = self.app.scan_id
        self.app.shutdown()
        self.app = self.make_app()
        self.assertEqual(len(self.app.results), 1)
        self.assertEqual(self.app.scan_id, scan_id)
        self.assertIn("Short tracks", self.app.presets())
        self.assertEqual(len(self.app.history()), 1)
        self.assertEqual(self.app.settings["workers"], 2)

    def test_load_previous_scan(self):
        self.file("one.mp3")
        self.scan()
        first = self.app.scan_id
        self.file("two.mp3")
        self.scan()
        self.assertEqual(len(self.app.results), 2)
        self.assertTrue(self.app.load_history(first))
        self.assertEqual(len(self.app.results), 1)

    def test_interrupted_snapshot_recovers_without_resuming_actions(self):
        self.file("song.mp3")
        self.scan()
        with self.app.db_lock:
            row=self.app.db.execute("SELECT progress FROM scan_history WHERE id=?",(self.app.scan_id,)).fetchone()
            progress=json.loads(row[0]);progress['phase']='scanning'
            self.app.db.execute("UPDATE scan_history SET progress=? WHERE id=?",(json.dumps(progress),self.app.scan_id));self.app.db.commit()
        # Close the database directly to simulate loss after a committed checkpoint.
        self.app.db.close()
        self.app=self.make_app()
        self.assertEqual(self.app.progress['phase'],'interrupted')
        self.assertEqual(len(self.app.results),1)
        self.assertFalse(self.app.busy())

    def test_quarantine_restore_and_scan_exclusion(self):
        source = self.file("Artist/song.mp3")
        self.scan()
        self.action("quarantine", list(self.app.results))
        self.assertFalse(source.exists())
        self.assertEqual(len(self.app.results), 0)
        quarantined = self.app.quarantine_rows()
        self.assertEqual(quarantined[0]["state"], "quarantined")
        self.scan()
        self.assertEqual(len(self.app.results), 0)
        self.action("restore", [quarantined[0]["id"]])
        self.assertEqual(source.read_bytes(), b"audio fixture")
        self.assertEqual(self.app.quarantine_rows(), [])

    def test_restore_does_not_overwrite(self):
        source = self.file("song.mp3")
        self.scan()
        self.action("quarantine", list(self.app.results))
        source.write_bytes(b"new file must survive")
        self.action("restore", [self.app.quarantine_rows()[0]["id"]])
        self.assertEqual(source.read_bytes(), b"new file must survive")
        self.assertEqual(self.app.progress["delete_failed"], 1)
        self.assertEqual(self.app.quarantine_rows()[0]["state"], "quarantined")

    def test_cross_device_quarantine_copy_and_restore(self):
        source=self.file('song.mp3',b'cross-volume content')
        self.scan()
        with patch('library.os.link',side_effect=OSError('Cross-device link')):
            self.action('quarantine',list(self.app.results))
            ident=self.app.quarantine_rows()[0]['id']
            self.assertFalse(source.exists())
            self.action('restore',[ident])
        self.assertEqual(source.read_bytes(),b'cross-volume content')

    def test_quarantine_tampering_blocks_purge(self):
        self.file('song.mp3')
        self.scan();self.action('quarantine',list(self.app.results))
        ident=self.app.quarantine_rows()[0]['id'];stored=self.app.quarantine_path(ident)
        stored.write_bytes(b'changed quarantine data')
        self.action('purge',[ident])
        self.assertTrue(stored.exists())
        self.assertEqual(self.app.progress['delete_failed'],1)

    def test_quarantine_changed_source_refused_and_manifest_persists(self):
        source = self.file("song.mp3")
        self.scan()
        preview = self.app.preview_action(dict(action="quarantine", ids=list(self.app.results)))
        source.write_bytes(b"changed")
        self.app.confirm_action(preview["confirmation"])
        self.wait()
        self.assertTrue(source.exists())
        self.assertEqual(self.app.progress["delete_failed"], 1)
        self.scan()
        self.action("quarantine", list(self.app.results))
        self.app.shutdown()
        self.app = self.make_app()
        self.assertEqual(len(self.app.quarantine_rows()), 1)
        self.action("restore", [self.app.quarantine_rows()[0]["id"]])
        self.assertEqual(source.read_bytes(), b"changed")

    def test_purge_and_expired_confirmation(self):
        self.file("song.mp3")
        self.scan()
        self.action("quarantine", list(self.app.results))
        ident = self.app.quarantine_rows()[0]["id"]
        preview = self.app.preview_action(dict(action="purge", ids=[ident]))
        saved = self.app.advanced_confirmations[preview["confirmation"]]
        self.app.advanced_confirmations[preview["confirmation"]] = (0, saved[1], saved[2])
        with self.assertRaises(ValueError):
            self.app.confirm_action(preview["confirmation"])
        self.action("purge", [ident])
        self.assertFalse(self.app.quarantine_path(ident).exists())
        self.assertEqual(self.app.quarantine_rows(), [])

    def test_retention_off_by_default_then_purges_only_expired(self):
        self.file("song.mp3")
        self.scan()
        self.action("quarantine", list(self.app.results))
        ident = self.app.quarantine_rows()[0]["id"]
        with self.app.db_lock:
            self.app.db.execute("UPDATE quarantine_items SET quarantined=? WHERE id=?", (time.time()-40*86400, ident))
            self.app.db.commit()
        self.app.scheduler_tick()
        self.assertTrue(self.app.quarantine_path(ident).exists())
        self.app.retention = dict(enabled=True, days=30)
        self.app.scheduler_tick()
        self.wait()
        self.assertFalse(self.app.quarantine_path(ident).exists())

    def test_daily_schedule_runs_once_and_only_scans(self):
        self.file("song.mp3")
        self.app.preset(dict(name="Daily", settings=self.settings()))
        self.app.settings_schedule(dict(enabled=True, time="02:00", preset="Daily"))
        moment = datetime.datetime(2026, 11, 11, 3, 0)
        self.app.scheduler_tick(moment)
        self.wait()
        self.assertEqual(self.app.schedule["last_run"], "2026-11-11")
        first = self.app.scan_id
        self.app.scheduler_tick(moment)
        self.assertEqual(self.app.scan_id, first)
        self.assertTrue((self.media / "song.mp3").exists())
        self.assertEqual(self.app.quarantine_rows(), [])

    def test_exact_duplicates_and_no_auto_file_actions(self):
        self.file("a.mp3", b"same content")
        self.file("b.flac", b"same content")
        self.file("c.mp3", b"different content")
        self.scan(duplicates="exact")
        rows = {r["name"]: r for r in self.app.results.values()}
        self.assertEqual(rows["a.mp3"]["duplicate"], rows["b.flac"]["duplicate"])
        self.assertTrue(rows["a.mp3"]["duplicate"].startswith("exact-"))
        self.assertEqual(rows["c.mp3"]["duplicate"], "")
        self.assertEqual(len(list(self.media.glob('*.*'))), 3)

    def test_similar_fingerprints_with_noise_and_featureless_rejection(self):
        rng = random.Random(10)
        base = [rng.randrange(512) for _ in range(100)]
        noisy = [x ^ (1 if i % 3 == 0 else 0) for i, x in enumerate(base)]
        self.assertTrue(similar(base, noisy))
        self.assertFalse(similar(base, [511-x for x in base]))
        self.assertFalse(similar([3]*100, [3]*100))

    def test_fingerprint_works_on_pcm_and_is_gain_tolerant(self):
        import array
        samples = []
        for n in range(8000*12):
            segment = n // 2048
            f = [220,330,500,750,1100,1600,2400][segment % 7]
            samples.append(int(7000*math.sin(2*math.pi*f*n/8000)+2000*math.sin(2*math.pi*150*n/8000)))
        data = array.array('h', samples).tobytes()
        quieter = array.array('h', [n//2 for n in samples]).tobytes()
        left = pcm_fingerprint(data, threading.Event())
        right = pcm_fingerprint(quieter, threading.Event())
        self.assertTrue(similar(left, right))


class LibraryHTTPTests(unittest.TestCase):
    setUp = LibraryTests.setUp
    tearDown = LibraryTests.tearDown
    reader = LibraryTests.reader
    deep = LibraryTests.deep
    make_app = LibraryTests.make_app
    file = LibraryTests.file
    settings = LibraryTests.settings
    scan = LibraryTests.scan
    wait = LibraryTests.wait
    def test_api_management_and_retention_acknowledgement(self):
        self.file("song.mp3")
        self.scan()
        server = ThreadingHTTPServer(("127.0.0.1", 0), LibraryHandler)
        server.finder = self.app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%s" % server.server_port
        def request(route, data=None):
            req = Request(base+route, data=None if data is None else json.dumps(data).encode(),
                          headers={"X-CSRF-Token": self.app.token, "Content-Type": "application/json"})
            with urlopen(req, timeout=5) as response:
                return json.load(response)
        try:
            self.assertEqual(request('/api/state')['version'], '2.1.0')
            self.assertEqual(len(request('/api/history')['history']), 1)
            request('/api/preset',dict(name='HTTP',settings=self.settings()))
            self.assertIn('HTTP',request('/api/presets')['presets'])
            with self.assertRaises(HTTPError):
                request('/api/retention',dict(enabled=True,days=30))
            self.assertFalse(self.app.retention['enabled'])
            request('/api/retention',dict(enabled=True,days=30,acknowledged=True))
            self.assertTrue(self.app.retention['enabled'])
            preview=request('/api/action-preview',dict(action='quarantine',ids=list(self.app.results)))
            request('/api/action',dict(confirmation=preview['confirmation']))
            self.wait()
            self.assertEqual(len(request('/api/quarantine')['rows']),1)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    unittest.main()
