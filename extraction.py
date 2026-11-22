"""Independent, explicitly confirmed FLAC-in-M4A extraction jobs."""
from contextlib import closing
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import islice
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time

from app import Cancelled, signature


def flac_stream(path, cancel):
    from library import command
    output, _ = command([os.getenv('FFPROBE', 'ffprobe'), '-v', 'error',
        '-protocol_whitelist', 'file,pipe', '-select_streams', 'a',
        '-show_entries', 'stream=index,codec_name', '-of', 'json', str(path)], cancel)
    streams = json.loads(output).get('streams', [])
    # Refuse to discard additional audio tracks.
    return len(streams) == 1 and streams[0].get('codec_name') == 'flac'


def pcm_hash(path, cancel):
    from library import command
    output, error = command([os.getenv('FFMPEG', 'ffmpeg'), '-v', 'error', '-xerror',
        '-nostdin', '-protocol_whitelist', 'file,pipe', '-i', str(path),
        '-map', '0:a:0', '-c:a', 'pcm_s32le', '-f', 'hash', '-hash', 'sha256', '-'], cancel, 3600)
    if error.strip() or not output.startswith(b'SHA256='):
        raise ValueError('Audio verification failed')
    return output.strip()


class Extractor:
    def __init__(self, finder):
        self.finder = finder
        self.thread = None
        self.cancel = threading.Event()
        self.entries = {}
        self.confirmations = {}
        self.scan_id = None
        self.workers = 4
        self.ready = 0
        self.progress = dict(phase='idle', found=0, eligible=0, skipped=0, extracted=0, failed=0)

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def excluded(self, path):
        config = self.finder.config.resolve()
        return self.finder.exclude(path) or path == config or config in path.parents

    def state(self, offset=0, limit=100):
        with self.finder.lock:
            offset = min(offset, len(self.entries))
            page = islice(self.entries.values(), offset, offset + limit)
            return dict(progress=dict(self.progress), busy=self.busy(), scan_id=self.scan_id,
                total=len(self.entries), ready=self.ready,
                rows=[{k: v for k, v in r.items() if k != 'signature'} for r in page])

    def selection(self):
        with self.finder.lock:
            if self.finder.busy():
                raise ValueError('Wait for the current operation to finish')
            return dict(scan_id=self.scan_id,
                        ids=[row['id'] for row in self.entries.values() if row['status'] == 'ready'])

    def start(self, folder, workers=4):
        with self.finder.lock:
            if self.finder.busy():
                raise ValueError('Wait for the current operation to finish')
            root = self.finder.path(str(folder).strip())
            if not root.is_dir() or self.excluded(root):
                raise ValueError('Choose a library folder outside quarantine and config')
            if type(workers) is not int or not 1 <= workers <= 32:
                raise ValueError('Choose between 1 and 32 extraction workers')
            self.workers = workers
            self.scan_id = secrets.token_hex(12)
            self.entries.clear()
            self.ready = 0
            self.confirmations.clear()
            self.cancel.clear()
            self.progress = dict(phase='scanning', found=0, eligible=0, skipped=0, extracted=0, failed=0)
            self.thread = threading.Thread(target=self.scan, args=(root,), daemon=True)
            self.thread.start()

    def candidates(self, root):
        pending = [root]
        while pending and not self.cancel.is_set():
            directory = pending.pop()
            # Resolve every directory again to reject replaced symlinks.
            directory = self.finder.path(str(directory.relative_to(self.finder.media)))
            with os.scandir(directory) as items:
                for item in items:
                    if self.cancel.is_set():
                        return
                    path = Path(item.path)
                    if item.is_symlink() or self.excluded(path):
                        continue
                    if item.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif item.is_file(follow_symlinks=False) and path.suffix.lower() == '.m4a':
                        yield path

    def process(self, worker, items):
        pending = set()
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            for item in items:
                if self.cancel.is_set():
                    break
                pending.add(executor.submit(worker, item))
                if len(pending) == self.workers:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        future.result()
            for future in pending:
                future.result()

    def scan(self, root):
        try:
            with closing(self.candidates(root)) as candidates:
                self.process(self.inspect, candidates)
        except Cancelled:
            pass
        except Exception as error:
            with self.finder.lock:
                self.progress['error'] = str(error)
                self.progress['failed'] += 1
        finally:
            with self.finder.lock:
                self.progress['phase'] = 'cancelled' if self.cancel.is_set() else 'complete'

    def inspect(self, path):
        row = dict(id=secrets.token_hex(12), path=str(path.relative_to(self.finder.media)),
                   output=str(path.with_suffix('.flac').relative_to(self.finder.media)), status='skipped', detail='')
        try:
            path = self.finder.path(row['path'])
            original = path.lstat()
            row['signature'] = signature(original)
            if not stat.S_ISREG(original.st_mode):
                raise ValueError('Not a regular file')
            if not flac_stream(path, self.cancel):
                row['detail'] = 'Requires exactly one FLAC audio stream; AAC/ALAC are not extracted'
            elif os.path.lexists(path.with_suffix('.flac')):
                row['detail'] = 'Destination already exists'
            elif signature(path.lstat()) != row['signature']:
                raise ValueError('File changed while reading')
            else:
                row.update(status='ready', detail='FLAC audio; ready to extract without re-encoding')
        except Cancelled:
            raise
        except Exception as error:
            row.update(status='error', detail=str(error))
        with self.finder.lock:
            self.entries[row['id']] = row
            self.progress['found'] += 1
            self.progress['eligible' if row['status'] == 'ready' else 'failed' if row['status'] == 'error' else 'skipped'] += 1
            self.ready += row['status'] == 'ready'

    def preview(self, ids):
        with self.finder.lock:
            if self.finder.busy():
                raise ValueError('Wait for the current operation to finish')
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
                raise ValueError('Select ready files')
            ids = list(dict.fromkeys(ids))
            if any(i not in self.entries or self.entries[i]['status'] != 'ready' for i in ids):
                raise ValueError('Selection changed; scan again')
            token = secrets.token_urlsafe(24)
            self.confirmations = {token: (time.monotonic() + 120, ids)}
            return dict(confirmation=token, count=len(ids), paths=[self.entries[i]['path'] for i in ids])

    def extract(self, token):
        with self.finder.lock:
            if self.finder.busy():
                raise ValueError('Wait for the current operation to finish')
            saved = self.confirmations.pop(token, None)
            if not saved or saved[0] < time.monotonic():
                raise ValueError('Confirmation expired; review files again')
            self.cancel.clear()
            self.progress.update(phase='extracting', extracted=0, failed=0)
            self.thread = threading.Thread(target=self.run, args=(saved[1],), daemon=True)
            self.thread.start()

    def run(self, ids):
        try:
            self.process(self.extract_entry, ids)
        except Cancelled:
            pass
        finally:
            with self.finder.lock:
                self.progress['phase'] = 'cancelled' if self.cancel.is_set() else 'complete'

    def extract_entry(self, ident):
        if self.cancel.is_set():
            raise Cancelled()
        row = self.entries[ident]
        try:
            self.extract_one(row)
            with self.finder.lock:
                row.update(status='extracted', detail='Verified FLAC saved; original M4A deleted')
                self.progress['extracted'] += 1
                self.ready -= 1
        except Cancelled:
            raise
        except Exception as error:
            with self.finder.lock:
                row.update(status='error', detail=str(error))
                self.progress['failed'] += 1
                self.ready -= 1

    def extract_one(self, row):
        from library import command
        source = self.finder.path(row['path'])
        original = source.lstat()
        if not stat.S_ISREG(original.st_mode) or signature(original) != tuple(row['signature']):
            raise ValueError('Source changed since scan; original retained')
        destination = source.with_suffix('.flac')
        if os.path.lexists(destination):
            raise ValueError('Destination already exists; original retained')
        if not flac_stream(source, self.cancel):
            raise ValueError('Source no longer contains a single FLAC stream')
        fd, name = tempfile.mkstemp(prefix='.nas-flac-', suffix='.tmp', dir=source.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            _, error = command([os.getenv('FFMPEG', 'ffmpeg'), '-v', 'error', '-xerror', '-nostdin',
                '-y', '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
                '-map_metadata', '0', '-c:a', 'copy', '-f', 'flac', str(temporary)], self.cancel, 3600)
            if error.strip() or not temporary.stat().st_size or not flac_stream(temporary, self.cancel):
                raise ValueError('FLAC extraction failed; original retained')
            if pcm_hash(source, self.cancel) != pcm_hash(temporary, self.cancel):
                raise ValueError('Decoded audio differs; original retained')
            if self.cancel.is_set():
                raise Cancelled()
            # Recheck source and every parent after long-running media commands.
            source = self.finder.path(row['path'])
            if signature(source.lstat()) != tuple(row['signature']):
                raise ValueError('Source changed during extraction; original retained')
            os.chmod(temporary, stat.S_IMODE(original.st_mode))
            os.utime(temporary, ns=(original.st_atime_ns, original.st_mtime_ns))
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            # Exclusive publication: never replace even a concurrently-created target.
            # Same-directory hard links are supported on normal NAS filesystems.
            os.link(temporary, destination)
            try:
                if os.name != 'nt':
                    # Persist the new directory entry before removing the source.
                    directory_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                source = self.finder.path(row['path'])
                if signature(destination.lstat()) != signature(temporary.lstat()):
                    raise ValueError('Destination changed before deletion')
                if signature(source.lstat()) != tuple(row['signature']):
                    raise ValueError('Source changed before deletion')
                source.unlink()
            except Exception as error:
                raise ValueError('Verified FLAC saved but M4A retained: ' + str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)

    def shutdown(self):
        self.cancel.set()
        if self.thread:
            self.thread.join()
