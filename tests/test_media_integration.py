import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from library import metadata, decode_health, fingerprint, similar, LibraryFinder

FFMPEG = os.getenv('FFMPEG') or shutil.which('ffmpeg')
FFPROBE = os.getenv('FFPROBE') or shutil.which('ffprobe')


@unittest.skipUnless(FFMPEG and FFPROBE, 'FFmpeg and FFprobe required for real codec integration')
class MediaIntegrationTests(unittest.TestCase):
    def test_real_formats_fragmented_m4a_health_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);media=root/'music';media.mkdir()
            def run(args):
                subprocess.run([FFMPEG,'-v','error','-y']+args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            wav=media/'original.wav'
            run(['-f','lavfi','-i','aevalsrc=0.4*sin(2*PI*(220+37*floor(t*4))*t)+0.12*sin(2*PI*150*t):s=44100:d=30','-ac','1','-c:a','pcm_s16le',str(wav)])
            run(['-i',str(wav),'-c:a','flac','-metadata','artist=Integration artist',str(media/'lossless.flac')])
            run(['-i',str(wav),'-c:a','libmp3lame','-b:a','192k',str(media/'lossy.mp3')])
            run(['-i',str(wav),'-c:a','aac','-movflags','frag_keyframe+empty_moov',str(media/'fragmented.m4a')])
            cancel=threading.Event()
            for path in media.iterdir():
                info=metadata(path,cancel)
                self.assertGreater(info['duration'],29.8)
                self.assertLess(info['duration'],30.2)
                self.assertGreater(info['sample_rate'],0)
                decode_health(path,cancel)
            self.assertEqual(metadata(media/'lossless.flac',cancel)['artist'],'Integration artist')
            a=fingerprint(wav,cancel);b=fingerprint(media/'lossless.flac',cancel);c=fingerprint(media/'lossy.mp3',cancel)
            self.assertTrue(similar(a,b),'Lossless containers should match acoustically')
            self.assertTrue(similar(a,c),'MP3 and WAV should match acoustically on this fixture')
            app=LibraryFinder(media,root/'config',scheduler=False)
            try:
                app.start(dict(folder='',days=7,minimum=29,maximum=31,workers=2,formats=['wav','flac','mp3','m4a'],duplicates='both',deep_check=True))
                app.thread.join(60)
                self.assertFalse(app.thread.is_alive())
                self.assertEqual(len(app.results),4)
                self.assertEqual(app.progress['errors'],0)
                self.assertTrue(all(r['health']=='decode-ok' for r in app.results.values()))
                self.assertTrue(any(r['duplicate'].startswith('similar-') for r in app.results.values()))
            finally:
                app.shutdown()


if __name__=='__main__':unittest.main()
