"""Verify the built container against real mounted fixtures before publishing."""
import csv
import io
import json
import os
import time
from urllib.request import Request, urlopen

BASE = os.getenv('SMOKE_URL', 'http://127.0.0.1:8099')


def request(path, data=None, csrf=''):
    headers = {'Origin': BASE, 'X-CSRF-Token': csrf}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = Request(BASE+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
    with urlopen(req, timeout=10) as response:
        raw = response.read().decode('utf-8-sig')
        return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw


for attempt in range(60):
    try:
        state = request('/api/state')
        break
    except OSError:
        time.sleep(1)
else:
    raise RuntimeError('Container did not start')
assert state['version'] == '2.2.0', state
request('/api/scan', dict(folder='', days=0, minimum=0, maximum=120,
        workers=2, formats=['flac', 'mp3'], authenticity_check=True), state['csrf'])
for attempt in range(120):
    state = request('/api/state')
    if not state['busy']:
        break
    time.sleep(1)
else:
    raise RuntimeError('Smoke scan did not finish')
assert state['progress']['errors'] == 0, state
rows = {r['name']: r for r in request('/api/results')['rows']}
assert len(rows) == 3, rows
assert rows['original.flac']['authenticity'] == 'inconclusive', rows
assert rows['lossy.mp3']['authenticity'] == 'lossy-codec', rows
assert rows['transcoded.flac']['authenticity'] == 'suspected-lossy-source', rows
export = list(csv.DictReader(io.StringIO(request('/api/export'))))
assert len(export) == 3 and all(r['Authenticity evidence'] for r in export), export
print('Container API, real audio authenticity scan and CSV smoke checks passed')
# MP3 is a known lossy sibling, so this first folder has mixed evidence.
flagged = rows['transcoded.flac']
assert flagged['authenticity_folder_counts'] == dict(no_suspicious_cutoff=1,other_matching_files=2,other_flags=1), flagged
assert 'folder evidence is mixed' in flagged['authenticity_folder_detail'], flagged
# Exclude the MP3 and reuse the cache: context must be recomputed for this scope.
request('/api/scan', dict(folder='', days=0, minimum=0, maximum=120,
        workers=2, formats=['flac'], authenticity_check=True), state['csrf'])
for attempt in range(120):
    state = request('/api/state')
    if not state['busy']:
        break
    time.sleep(1)
else:
    raise RuntimeError('Second smoke scan did not finish')
assert state['progress']['errors'] == 0, state
assert state['progress']['cached'] == 2, state
rows = {r['name']: r for r in request('/api/results')['rows']}
flagged = rows['transcoded.flac']
assert flagged['authenticity_folder_counts'] == dict(no_suspicious_cutoff=1,other_matching_files=1,other_flags=0), flagged
assert 'false positive is more plausible' in flagged['authenticity_folder_detail'], flagged
assert flagged['authenticity'] == 'suspected-lossy-source', flagged
export = list(csv.DictReader(io.StringIO(request('/api/export'))))
assert any('false positive is more plausible' in r['Authenticity folder context'] for r in export), export
print('Folder context, cached rescan scope and CSV smoke checks passed')
