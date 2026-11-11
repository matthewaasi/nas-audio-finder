import base64
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import app


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "music"
        self.media.mkdir()
        self.calls = []
        def reader(path, cancel):
            self.calls.append(path.name)
            return 30.0
        self.finder = app.Finder(self.media, self.root / "config", reader)

    def tearDown(self):
        self.finder.shutdown()
        self.temp.cleanup()

    def file(self, name, age=20):
        path = self.media / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(bytes(range(100)))
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def start(self, **values):
        settings = dict(folder="", days=7, minimum=25, maximum=35, workers=4,
                        formats=["m4a", "mp3", "flac", "wav"])
        settings.update(values)
        self.finder.start(settings)
        self.finder.thread.join(10)
        self.assertFalse(self.finder.thread.is_alive())


class ScannerTests(Fixture):
    def test_formats_date_and_cache(self):
        self.file("Artist/Track.MP3")
        self.file("Artist/Track.flac")
        self.file("Artist/old.wav", age=8*86400)
        self.file("Artist/future.m4a", age=-500)
        self.file("Artist/not-audio.jpg")
        self.start(formats=["mp3"])
        self.assertEqual([r["name"] for r in self.finder.rows()], ["Track.MP3"])
        self.assertEqual(len(self.calls), 1)
        self.start(formats=["mp3"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.finder.progress["cached"], 1)
        self.start()
        self.assertEqual(len(self.finder.rows()), 2)
        self.assertEqual(self.finder.progress["files"], 4)
        self.assertEqual(self.finder.progress["recent"], 2)

    def test_inclusive_duration_bounds_and_unknown(self):
        for name in ("25.wav", "35.wav", "36.wav", "unknown.wav"):
            self.file(name)
        def reader(path, _):
            if path.stem == "unknown":
                raise ValueError("Unknown duration")
            return float(path.stem)
        self.finder.reader = reader
        self.start(formats=["wav"])
        self.assertEqual([r["name"] for r in self.finder.rows()], ["25.wav", "35.wav"])
        self.assertEqual(self.finder.progress["errors"], 1)

    def test_modified_file_invalidates_cache(self):
        path = self.file("track.mp3")
        self.start()
        path.write_bytes(b"changed size")
        os.utime(path, (time.time()-1, time.time()-1))
        self.start()
        self.assertEqual(len(self.calls), 2)

    def test_validation_and_scope(self):
        for settings in ({"formats": []}, {"formats": ["exe"]}, {"workers": 100},
                         {"minimum": 40, "maximum": 30}, {"folder": "../"},
                         {"days": float("nan")}):
            with self.assertRaises(ValueError):
                self.start(**settings)
        with self.assertRaises(ValueError):
            self.finder.path(str(self.root))

    def test_cancel_drains_queue(self):
        for i in range(100):
            self.file("%s.mp3" % i)
        started = threading.Event()
        def reader(path, cancel):
            started.set()
            cancel.wait(5)
            raise app.Cancelled()
        self.finder.reader = reader
        self.finder.start(dict(folder="", days=7, minimum=25, maximum=35, workers=1, formats=["mp3"]))
        self.assertTrue(started.wait(2))
        self.finder.stop()
        self.finder.thread.join(5)
        self.assertFalse(self.finder.thread.is_alive())
        self.assertEqual(self.finder.progress["phase"], "cancelled")

    def test_confirmed_delete_and_changed_file_protection(self):
        unchanged = self.file("remove.mp3")
        changed = self.file("keep.mp3")
        self.start()
        changed.write_bytes(b"modified after scan")
        preview = self.finder.deletion_preview(list(self.finder.results))
        self.assertEqual(preview["count"], 2)
        self.finder.delete(preview["confirmation"])
        self.finder.thread.join(5)
        self.assertFalse(unchanged.exists())
        self.assertTrue(changed.exists())
        self.assertEqual(len(self.finder.results), 1)
        self.assertEqual(self.finder.progress["deleted"], 1)
        self.assertEqual(self.finder.progress["delete_failed"], 1)
        with self.assertRaises(ValueError):
            self.finder.delete(preview["confirmation"])

    def test_symlinks_are_not_scanned_or_followed(self):
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"outside")
        try:
            (self.media / "link.mp3").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        self.start()
        self.assertEqual(len(self.finder.results), 0)
        with self.assertRaises(ValueError):
            self.finder.path("link.mp3")


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.file("sample.mp3")
        self.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.server.finder = self.finder
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%s" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.url + path, data=data, headers=headers or {})
        return urlopen(request, timeout=5)

    def test_gui_assets_and_results_export(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("Content-Security-Policy", response.headers)
        with self.request("/api/results") as response:
            rows = json.load(response)
            self.assertEqual(rows["total"], 1)
            self.assertNotIn("signature", rows["rows"][0])
        with self.request("/api/export") as response:
            self.assertIn("sample.mp3", response.read().decode("utf-8-sig"))
        with self.request("/api/results?search=missing") as response:
            self.assertEqual(json.load(response)["total"], 0)

    def test_playback_removed(self):
        ident = next(iter(self.finder.results))
        for suffix in ("", "&compatible=1"):
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/audio?id=" + ident + suffix)
            self.assertEqual(caught.exception.code, 404)
        with self.request("/") as response:
            html = response.read().decode()
            self.assertNotIn("<audio", html)
            self.assertNotIn("playbackMode", html)
        with self.request("/app.js") as response:
            script = response.read().decode()
            self.assertNotIn("playTrack", script)
            self.assertNotIn("/api/audio", script)

    def test_csrf_and_confirmation_flow(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/delete-preview", {"ids": list(self.finder.results)})
        self.assertEqual(caught.exception.code, 400)
        headers = {"X-CSRF-Token": self.finder.token, "Content-Type": "application/json"}
        with self.assertRaises(HTTPError):
            self.request("/api/delete-preview", {"ids": list(self.finder.results)}, dict(headers, Origin="http://other-host"))
        with self.request("/api/delete-preview", {"ids": list(self.finder.results)}, headers) as response:
            preview = json.load(response)
        self.assertTrue((self.media / "sample.mp3").exists())
        with self.request("/api/delete", {"confirmation": preview["confirmation"]}, headers) as response:
            self.assertTrue(json.load(response)["ok"])
        self.finder.thread.join(5)
        self.assertFalse((self.media / "sample.mp3").exists())

    def test_password_and_malformed_body(self):
        with patch.dict(os.environ, APP_PASSWORD="test-secret"):
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/state")
            self.assertEqual(caught.exception.code, 401)
            auth = "Basic " + base64.b64encode(b"admin:test-secret").decode()
            with self.request("/api/state", headers={"Authorization": auth}) as response:
                self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/cancel", [], {"X-CSRF-Token": self.finder.token})
        self.assertEqual(caught.exception.code, 400)


class ProbeTests(unittest.TestCase):
    def fake(self, output):
        class Process:
            returncode = 0
            def communicate(self, **kwargs): return json.dumps(output).encode(), b""
            def poll(self): return 0
        return Process()

    def test_stream_duration_and_fragmented_format_fallback(self):
        for output in ({"streams": [{"duration": "30"}], "format": {"duration": "100"}},
                       {"streams": [{}], "format": {"duration": "30"}}):
            with patch("app.subprocess.Popen", return_value=self.fake(output)):
                self.assertEqual(app.probe(Path("fixture.m4a"), threading.Event()), 30)
        with patch("app.subprocess.Popen", return_value=self.fake({"streams": [], "format": {"duration": "30"}})):
            with self.assertRaisesRegex(ValueError, "No audio"):
                app.probe(Path("fixture.m4a"), threading.Event())


if __name__ == "__main__":
    unittest.main()
