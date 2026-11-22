import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Cancelled
from extraction import pcm_hash
from library import LibraryFinder, LibraryHandler, metadata


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / 'music'
        self.media.mkdir()
        self.app = LibraryFinder(self.media, self.root / 'config', scheduler=False)
        self.tool = self.app.extractor

    def tearDown(self):
        self.app.shutdown()
        self.temp.cleanup()

    def scan(self):
        self.tool.start('')
        self.tool.thread.join(20)
        self.assertFalse(self.tool.busy())

    def extract(self):
        ids = [r['id'] for r in self.tool.entries.values() if r['status'] == 'ready']
        preview = self.tool.preview(ids)
        self.tool.extract(preview['confirmation'])
        self.tool.thread.join(30)
        self.assertFalse(self.tool.busy())
        return preview

    def test_scope_skips_collisions_and_keeps_library_state(self):
        (self.media / 'a.M4A').write_bytes(b'fake')
        (self.media / 'a.flac').write_bytes(b'existing')
        (self.media / 'b.m4a').write_bytes(b'fake')
        self.app.quarantine.mkdir()
        (self.app.quarantine / 'q.m4a').write_bytes(b'fake')
        before = dict(self.app.progress)
        with patch('extraction.flac_stream', return_value=True):
            self.scan()
        self.assertEqual(self.tool.progress['found'], 2)
        self.assertEqual(self.tool.progress['eligible'], 1)
        self.assertEqual(self.app.progress, before)
        with self.assertRaises(ValueError):
            self.tool.start('../')
        with self.assertRaises(ValueError):
            self.tool.start('.nas-audio-finder-quarantine')
        with self.assertRaises(ValueError):
            self.tool.preview(['unknown'])
        with self.assertRaises(ValueError):
            self.tool.extract('unknown')

    def test_changed_source_and_new_destination_preserve_originals(self):
        source = self.media / 'track.m4a'
        source.write_bytes(b'fake')
        with patch('extraction.flac_stream', return_value=True):
            self.scan()
            source.write_bytes(b'changed source')
            preview = self.extract()
            self.assertEqual(self.tool.progress['failed'], 1)
            self.assertTrue(source.exists())
            with self.assertRaises(ValueError):
                self.tool.extract(preview['confirmation'])
            self.scan()
            target = source.with_suffix('.flac')
            target.write_bytes(b'existing')
            self.extract()
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertTrue(source.exists())

    def test_cancellation_and_busy_exclusion(self):
        (self.media / 'track.m4a').write_bytes(b'fake')
        entered = threading.Event()
        def wait(path, cancel):
            entered.set()
            cancel.wait(5)
            raise Cancelled()
        with patch('extraction.flac_stream', side_effect=wait):
            self.tool.start('')
            self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError):
                self.app.start(dict(formats=['m4a']))
            with self.assertRaises(ValueError):
                self.tool.start('')
            self.tool.cancel.set()
            self.tool.thread.join(5)
        self.assertEqual(self.tool.progress['phase'], 'cancelled')

    def test_paginated_results_select_all_ready_files(self):
        for index in range(103):
            (self.media / f'track-{index}.m4a').write_bytes(b'fake')
        (self.media / 'skipped.m4a').write_bytes(b'fake')
        with patch('extraction.flac_stream', side_effect=lambda path, _: path.stem != 'skipped'):
            self.scan()

        handler = LibraryHandler.__new__(LibraryHandler)
        handler.server = type('Server', (), {'finder': self.app})()
        first = handler.extra_get('/api/extraction', lambda key, default: default)
        second = handler.extra_get('/api/extraction',
                                   lambda key, default: '100' if key == 'offset' else default)
        selection = handler.extra_get('/api/extraction/selection', None)
        rows = first['rows'] + second['rows']
        self.assertEqual((len(first['rows']), len(second['rows']), first['total']), (100, 4, 104))
        self.assertEqual(len({row['id'] for row in rows}), 104)
        self.assertEqual(selection['ids'], [row['id'] for row in rows if row['status'] == 'ready'])
        self.assertEqual(self.tool.preview(selection['ids'])['count'], 103)

    def test_scan_and_extraction_process_files_in_parallel(self):
        for name in ('first.m4a', 'second.m4a'):
            (self.media / name).write_bytes(b'fake')
        probe_barrier = threading.Barrier(2, timeout=5)

        def probe(path, cancel):
            probe_barrier.wait()
            return True

        with patch('extraction.flac_stream', side_effect=probe):
            self.tool.start('', workers=2)
            self.tool.thread.join(15)
        self.assertEqual(self.tool.progress['eligible'], 2)

        extraction_barrier = threading.Barrier(2, timeout=5)
        with patch.object(self.tool, 'extract_one', side_effect=lambda row: extraction_barrier.wait()):
            self.extract()
        self.assertEqual(self.tool.progress['extracted'], 2)
        self.assertEqual(self.tool.selection()['ids'], [])

    def test_api_requires_csrf_and_confirmation(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), LibraryHandler)
        server.finder = self.app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%s' % server.server_port
        try:
            with urlopen(base + '/api/extraction') as response:
                self.assertEqual(json.load(response)['progress']['phase'], 'idle')
            for token in ('', self.app.token):
                request = Request(base + '/api/extraction/extract', data=b'{}',
                    headers={'X-CSRF-Token': token, 'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as result:
                    urlopen(request)
                self.assertEqual(result.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @unittest.skipUnless((os.getenv('FFMPEG') or shutil.which('ffmpeg')) and
                         (os.getenv('FFPROBE') or shutil.which('ffprobe')), 'FFmpeg and FFprobe required')
    def test_real_flac_remux_and_audio_verification(self):
        def make(name, codec, extra=()):
            path = self.media / name
            subprocess.run([os.getenv('FFMPEG', 'ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi',
                '-i', 'sine=frequency=440:duration=0.3', '-c:a', codec,
                '-metadata', 'artist=Extraction artist', '-f', 'mp4', *extra, str(path)], check=True, capture_output=True)
            return path
        source = make('track.M4A', 'flac', ['-strict', 'experimental'])
        make('aac.m4a', 'aac')
        make('alac.m4a', 'alac')
        (self.media / 'broken.m4a').write_bytes(b'corrupt')
        expected = pcm_hash(source, threading.Event())
        self.scan()
        self.assertEqual(self.tool.progress['eligible'], 1)
        self.assertEqual(self.tool.progress['skipped'], 2)
        self.assertEqual(self.tool.progress['failed'], 1)
        self.extract()
        target = self.media / 'track.flac'
        self.assertEqual(self.tool.progress['extracted'], 1, self.tool.state())
        self.assertFalse(source.exists())
        self.assertEqual(pcm_hash(target, threading.Event()), expected)
        self.assertEqual(metadata(target, threading.Event())['artist'], 'Extraction artist')
        self.assertTrue((self.media / 'aac.m4a').exists())
        # Verification failure and failed publication must retain the source.
        source = make('mismatch.m4a', 'flac', ['-strict', 'experimental'])
        self.scan()
        with patch('extraction.pcm_hash', side_effect=[b'SHA256=a', b'SHA256=b']):
            self.extract()
        self.assertTrue(source.exists())
        self.assertFalse(source.with_suffix('.flac').exists())
        self.assertFalse(list(self.media.glob('.nas-flac-*')))
        self.scan()
        with patch('extraction.os.link', side_effect=OSError('unsupported')):
            self.extract()
        self.assertTrue(source.exists())
        self.assertFalse(source.with_suffix('.flac').exists())
        self.assertFalse(list(self.media.glob('.nas-flac-*')))
