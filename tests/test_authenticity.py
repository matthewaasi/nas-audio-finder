import array
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import Cancelled
from authenticity import analyze, cutoff
from library import command, metadata
import test_library


class SpectralTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()

    def pcm(self, samples):
        pcm = array.array('f', samples)
        if sys.byteorder != 'little':
            pcm.byteswap()
        return pcm.tobytes()

    def test_silence_tone_and_broadband_are_inconclusive(self):
        for samples in ([0.]*32768, [math.sin(i*.2)*.2 for i in range(32768)],
                        [random.Random(i).uniform(-.3,.3) for i in range(32768)]):
            self.assertIsNone(cutoff(self.pcm(samples), 44100, 1, self.cancel))

    def test_sharp_band_edge_and_antiphase_channels(self):
        rng = random.Random(7)
        frequencies = list(range(100, 1480, 8)) # FFT bins, extending to 15.9 kHz
        phases = [rng.random()*2*math.pi for _ in frequencies]
        block = [sum(math.sin(2*math.pi*f*i/4096+p) for f,p in zip(frequencies, phases))*.002 for i in range(4096)]
        samples = block*8
        edge = cutoff(self.pcm(samples), 44100, 1, self.cancel)
        self.assertIsNotNone(edge)
        self.assertTrue(15000 <= edge <= 16500, edge)
        stereo = [v for x in samples for v in (x, -x)]
        self.assertEqual(cutoff(self.pcm(stereo), 44100, 2, self.cancel), edge)

    def test_cancel(self):
        self.cancel.set()
        with self.assertRaises(Cancelled):
            cutoff(self.pcm([.1]*32768), 44100, 1, self.cancel)

    def test_codec_classification_and_consensus(self):
        info = dict(codec='flac', sample_rate=44100, duration=60, channels=2)
        calls = []
        def decode(args, cancel, timeout):
            calls.append(args)
            return b'', b''
        self.assertEqual(analyze('x',dict(info,codec='mp3'),self.cancel,decode)['status'],'lossy-codec')
        self.assertEqual(analyze('x',dict(info,codec='wavpack'),self.cancel,decode)['status'],'inconclusive')
        with patch('authenticity.cutoff',side_effect=[16000,16250,None]):
            self.assertEqual(analyze('x',info,self.cancel,decode)['status'],'suspected-lossy-source')
        self.assertEqual(len(calls),3)
        with patch('authenticity.cutoff',return_value=22000):
            self.assertEqual(analyze('x',dict(info,sample_rate=96000),self.cancel,decode)['status'],'possible-upsampling')
        with patch('authenticity.cutoff',side_effect=[16000,None,None]):
            self.assertEqual(analyze('x',info,self.cancel,decode)['status'],'inconclusive')


class AuthenticityCacheTests(unittest.TestCase):
    setUp = test_library.LibraryTests.setUp
    tearDown = test_library.LibraryTests.tearDown
    make_app = test_library.LibraryTests.make_app
    reader = test_library.LibraryTests.reader
    deep = test_library.LibraryTests.deep
    file = test_library.LibraryTests.file
    settings = test_library.LibraryTests.settings
    scan = test_library.LibraryTests.scan
    wait = test_library.LibraryTests.wait
    def test_authenticity_opt_in_cache_invalidation_and_retry(self):
        path = self.file('a.flac')
        answer = dict(version=1,status='suspected-lossy-source',detail='Test evidence')
        with patch('library.analyze',return_value=answer) as reader:
            self.scan()
            reader.assert_not_called()
            self.assertEqual(next(iter(self.app.results.values()))['authenticity'],'not-scanned')
            self.scan(authenticity_check=True)
            self.scan(authenticity_check=True)
            self.assertEqual(reader.call_count,1)
            self.assertEqual(next(iter(self.app.results.values()))['authenticity_detail'],'Test evidence')
            self.scan()
            self.assertEqual(next(iter(self.app.results.values()))['authenticity'],'not-scanned')
            path.write_bytes(b'changed fixture')
            self.scan(authenticity_check=True)
            self.assertEqual(reader.call_count,2)
        path.write_bytes(b'changed again')
        with patch('library.analyze',side_effect=ValueError('Decoder failed')) as reader:
            self.scan(authenticity_check=True)
            self.scan(authenticity_check=True)
            self.assertEqual(reader.call_count,2)
            self.assertEqual(next(iter(self.app.results.values()))['authenticity'],'analysis-error')
            self.assertEqual(next(iter(self.app.results.values()))['health'],'metadata-ok')


@unittest.skipUnless(os.getenv('FFMPEG') or shutil.which('ffmpeg'), 'FFmpeg required')
class RealAudioTests(unittest.TestCase):
    def test_mp3_transcode_and_lossless_noise(self):
        ffmpeg = os.getenv('FFMPEG') or shutil.which('ffmpeg')
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def run(*args):
                subprocess.run([ffmpeg,'-v','error','-y',*map(str,args)],check=True,capture_output=True)
            original = root/'original.flac'
            mp3 = root/'lossy.mp3'
            transcode = root/'transcoded.flac'
            run('-f','lavfi','-i','anoisesrc=color=white:amplitude=0.3:sample_rate=44100:duration=16:seed=42',original)
            run('-i',original,'-c:a','libmp3lame','-b:a','128k',mp3)
            run('-i',mp3,transcode)
            self.assertEqual(analyze(original,metadata(original,cancel),cancel,command)['status'],'inconclusive')
            self.assertEqual(analyze(mp3,metadata(mp3,cancel),cancel,command)['status'],'lossy-codec')
            result = analyze(transcode,metadata(transcode,cancel),cancel,command)
            self.assertEqual(result['status'],'suspected-lossy-source',result)
