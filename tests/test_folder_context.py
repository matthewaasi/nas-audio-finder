import csv
import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from unittest.mock import patch

from authenticity import ANALYSIS_VERSION, analyze, folder_context
from library import LibraryHandler
import test_library


def row(path, status='inconclusive', outcome='no-suspicious-cutoff', health='metadata-ok'):
    return dict(path=path, health=health, authenticity=status,
                authenticity_analysis=dict(screening_outcome=outcome))


class FolderContextTests(unittest.TestCase):
    def test_isolated_flag_counts_only_immediate_folder(self):
        rows = [row('Album/1.flac','suspected-lossy-source'),row('Album/2.flac'),
                row('Album/3.flac'),row('Album/Disc 2/4.flac'),row('Other/5.flac')]
        result=folder_context(rows)
        self.assertIn('2 of 2 other matching',result[0]['authenticity_folder_detail'])
        self.assertIn('false positive is more plausible',result[0]['authenticity_folder_detail'])
        self.assertIn('not verified lossless',result[0]['authenticity_folder_detail'])
        self.assertEqual(result[0]['authenticity'],'suspected-lossy-source')
        self.assertNotIn('authenticity_folder_detail',rows[0])
        self.assertNotIn('authenticity_folder_detail',result[1])

    def test_incomplete_unsupported_and_unhealthy_peers_do_not_reassure(self):
        rows=[row('a.flac','possible-upsampling'),row('b.flac',outcome='insufficient-or-mixed-evidence'),
              row('c.flac',health='decode-error'),row('d.mp3','lossy-codec'),
              row('e.flac','analysis-error'),row('f.flac','not-scanned')]
        self.assertNotIn('authenticity_folder_detail',folder_context(rows)[0])
        self.assertNotIn('authenticity_folder_detail',folder_context([rows[0],dict(path='old.flac',health='metadata-ok',authenticity='inconclusive')])[0])

    def test_mixed_flags_and_lossy_codec_are_not_downgraded(self):
        result=folder_context([row('A/1.flac','suspected-lossy-source'),row('A/2.flac'),
                row('A/3.mp3','lossy-codec'),row('A/4.flac','possible-upsampling')])
        self.assertIn('folder evidence is mixed',result[0]['authenticity_folder_detail'])
        self.assertEqual(result[0]['authenticity_folder_counts']['other_flags'],2)
        self.assertNotIn('authenticity_folder_detail',result[2])

    def test_context_is_idempotent_and_removed_when_peers_change(self):
        once=folder_context([row('1.flac','suspected-lossy-source'),row('2.flac')])
        self.assertEqual(folder_context(once),once)
        self.assertNotIn('authenticity_folder_detail',folder_context(once[:1])[0])

    def test_silent_material_is_not_a_reassuring_peer(self):
        def decode(*args): return b'\0'*131072,b''
        result=analyze('silent.flac',dict(codec='flac',duration=30,sample_rate=44100,channels=1),threading.Event(),decode)
        self.assertEqual(result['status'],'inconclusive')
        self.assertEqual(result['screening_outcome'],'insufficient-or-mixed-evidence')


class FolderScanTests(unittest.TestCase):
    setUp=test_library.LibraryTests.setUp
    tearDown=test_library.LibraryTests.tearDown
    make_app=test_library.LibraryTests.make_app
    reader=test_library.LibraryTests.reader
    deep=test_library.LibraryTests.deep
    file=test_library.LibraryTests.file
    settings=test_library.LibraryTests.settings
    scan=test_library.LibraryTests.scan
    wait=test_library.LibraryTests.wait

    def answers(self,path,info,cancel,command):
        if path.name.startswith('flag'):
            return dict(version=ANALYSIS_VERSION,status='suspected-lossy-source',detail='Sharp cutoff')
        return dict(version=ANALYSIS_VERSION,status='inconclusive',detail='No cutoff',screening_outcome='no-suspicious-cutoff')

    def test_scan_cache_history_and_csv_context(self):
        self.file('Album/flag.flac');self.file('Album/clear.flac');self.file('Other/clear.flac')
        with patch('library.analyze',side_effect=self.answers) as reader:
            self.scan(authenticity_check=True)
            first=self.app.scan_id
            flagged=next(r for r in self.app.results.values() if r['name']=='flag.flac')
            self.assertIn('1 of 1 other matching',flagged['authenticity_folder_detail'])
            with self.app.db_lock:
                cache=[json.loads(r[0]) for r in self.app.db.execute('SELECT data FROM audio_metadata')]
            self.assertTrue(all('authenticity_folder_detail' not in r for r in cache))
            self.scan(authenticity_check=True)
            self.assertEqual(reader.call_count,3)
            flagged=next(r for r in self.app.results.values() if r['name']=='flag.flac')
            self.assertIn('authenticity_folder_detail',flagged)
            self.app.load_history(first)
            server=ThreadingHTTPServer(('127.0.0.1',0),LibraryHandler);server.finder=self.app
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/export') as response:
                    exported=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
                flagged=next(r for r in exported if r['Path relative to /music']=='Album/flag.flac')
                self.assertIn('1 of 1 other matching',flagged['Authenticity folder context'])
            finally:
                server.shutdown();server.server_close();thread.join()
            self.scan(authenticity_check=True,codec='does-not-match')
            self.assertFalse(self.app.results)

    def test_error_or_cancelled_scans_do_not_add_context(self):
        self.file('flag.flac');self.file('clear.flac')
        with patch('library.analyze',side_effect=self.answers): self.scan(authenticity_check=True)
        self.app.results={r['id']:{k:v for k,v in r.items() if not k.startswith('authenticity_folder_')} for r in self.app.results.values()}
        self.app.cancel.set();self.app.scan_finish()
        self.assertTrue(all('authenticity_folder_detail' not in r for r in self.app.results.values()))
        self.app.cancel.clear();self.app.progress['errors']=1;self.app.scan_finish()
        self.assertTrue(all('authenticity_folder_detail' not in r for r in self.app.results.values()))
