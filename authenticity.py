"""Conservative, sampled spectral screening. Never a provenance certificate."""
import array
import cmath
import math
import os
from pathlib import Path
import sys

ANALYSIS_VERSION = 2
LOSSLESS = {'flac', 'alac', 'ape', 'tta', 'truehd', 'mlp', 'shorten', 'wmalossless'}
LOSSY = {'mp3', 'mp2', 'mp1', 'aac', 'vorbis', 'opus', 'ac3', 'eac3', 'wmav1', 'wmav2', 'wmapro'}


def spectrum(samples):
    """Hann-windowed radix-2 FFT, using only the standard library."""
    n = len(samples)
    values = [complex(x * (.5 - .5 * math.cos(2 * math.pi * i / (n - 1)))) for i, x in enumerate(samples)]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]
    width = 2
    while width <= n:
        step = cmath.exp(-2j * math.pi / width)
        for start in range(0, n, width):
            factor = 1
            for k in range(width // 2):
                a = values[start + k]
                b = factor * values[start + k + width // 2]
                values[start + k], values[start + k + width // 2] = a + b, a - b
                factor *= step
        width *= 2
    return [abs(x) ** 2 for x in values[:n // 2]]


def cutoff(data, rate, channels, cancel, evidence=None):
    """Find a sustained >35 dB edge in otherwise broadband active material."""
    from app import Cancelled
    pcm = array.array('f')
    pcm.frombytes(data[:len(data) // 4 * 4])
    if sys.byteorder != 'little':
        pcm.byteswap()
    n = 4096
    powers = [0.] * (n // 2)
    active = 0
    frames = len(pcm) // channels
    # Separate channels avoid phase cancellation in a mono downmix.
    for channel in range(channels):
        for start in range(0, max(0, frames - n + 1), max(n, frames // 8)):
            if cancel.is_set():
                raise Cancelled()
            block = pcm[start * channels + channel:(start + n) * channels:channels]
            if any(not math.isfinite(x) for x in block):
                continue
            if sum(x*x for x in block) / n < 1e-8:
                continue
            active += 1
            for i, power in enumerate(spectrum(block)):
                powers[i] += power
    if active < 4:
        return None
    def band(lo, hi):
        values = powers[max(1, int(lo*n/rate)):min(len(powers), int(hi*n/rate))]
        return sum(values) / max(1, len(values))
    baseline = band(2000, 8000)
    # Tones, silence and narrow-band material cannot support this heuristic.
    if baseline <= 0 or any(band(f, f+1000) < baseline * .01 for f in range(2000, 8000, 1000)):
        return None
    if evidence is not None:
        evidence["sufficient_material"] = True
    for hz in range(12000, min(24001, int(rate*.45)), 250):
        below = band(hz-1500, hz-500)
        above = band(hz+500, min(rate*.48, hz+4000))
        if below > baseline*.01 and above < below * 10**(-35/10):
            return hz
    return None


def analyze(path, info, cancel, command):
    codec = info.get('codec', '')
    def result(status, detail, **extra):
        return dict(version=ANALYSIS_VERSION, status=status, detail=detail, **extra)
    if codec in LOSSY:
        return result('lossy-codec', f'{codec} uses lossy encoding, regardless of filename.')
    # WavPack can be hybrid/lossy; require more evidence than its codec name.
    if codec not in LOSSLESS and not codec.startswith('pcm_'):
        return result('inconclusive', f'Encoding {codec or "unknown"} is not supported for authenticity screening.')
    rate = int(info.get('sample_rate') or 0)
    duration = float(info.get('duration') or 0)
    if rate < 32000 or duration < 6:
        return result('inconclusive', 'Too short or sample rate too low for this spectral check.')
    rate = min(rate, 96000)
    channels = min(2, max(1, int(info.get('channels') or 1)))
    positions = [max(0, (duration-4)*fraction) for fraction in (.1, .5, .9)]
    edges = []
    sufficient = 0
    for position in positions:
        output, _ = command([os.getenv('FFMPEG', 'ffmpeg'), '-v', 'error', '-nostdin',
            '-ss', str(position), '-protocol_whitelist', 'file,pipe', '-i', str(path),
            '-map', '0:a:0', '-vn', '-t', '4', '-threads', '1', '-ac', str(channels),
            '-ar', str(rate), '-f', 'f32le', 'pipe:1'], cancel, 90)
        evidence = {}
        edges.append(cutoff(output, rate, channels, cancel, evidence))
        sufficient += bool(evidence.get("sufficient_material"))
    found = [x for x in edges if x is not None]
    if len(found) >= 2 and max(found)-min(found) <= 750:
        edge = round(sum(found)/len(found))
        status = 'possible-upsampling' if info['sample_rate'] > 48000 and edge >= 20000 else 'suspected-lossy-source'
        return result(status, f'Consistent sharp spectral cutoff near {edge/1000:.1f} kHz in {len(found)}/3 excerpts. '
            'Mastering or recording bandwidth can produce the same pattern; review manually.', cutoff_hz=edge, excerpts=3)
    return result('inconclusive', 'No consistent suspicious cutoff found in three 4-second excerpts. '
        'This does not establish a lossless source; silence, limited bandwidth and high-quality lossy encodes may be inconclusive.', excerpts=3,
        screening_outcome='no-suspicious-cutoff' if sufficient >= 2 and not found else 'insufficient-or-mixed-evidence')


def folder_context(rows):
    """Derive context from this completed scan, never from cached folder summaries."""
    groups = {}
    flags = {'suspected-lossy-source', 'possible-upsampling'}
    for row in rows:
        group = groups.setdefault(str(Path(row['path']).parent), {'total': 0, 'clear': 0, 'flags': 0})
        group['total'] += 1
        if (row.get('health') in ('metadata-ok', 'decode-ok')
                and row.get('authenticity') == 'inconclusive'
                and row.get('authenticity_analysis', {}).get('screening_outcome') == 'no-suspicious-cutoff'):
            group['clear'] += 1
        if row.get('authenticity') in flags or row.get('authenticity') == 'lossy-codec':
            group['flags'] += 1
    result = []
    for original in rows:
        row = dict(original)
        row.pop('authenticity_folder_detail', None)
        row.pop('authenticity_folder_counts', None)
        group = groups[str(Path(row['path']).parent)]
        if row.get('authenticity') in flags and group['clear']:
            peers = group['total'] - 1
            other_flags = group['flags'] - 1
            explanation = ('A false positive is more plausible, especially if these tracks share a source.'
                if not other_flags else
                f'{other_flags} other file(s) also have authenticity flags; folder evidence is mixed.')
            row['authenticity_folder_detail'] = (
                f'Folder context: {group["clear"]} of {peers} other matching file(s) in this folder '
                f'completed spectral screening with no suspicious cutoff. {explanation} '
                'These results remain inconclusive, not verified lossless. '
                'Only matching files in this completed scan were compared.')
            row['authenticity_folder_counts'] = dict(no_suspicious_cutoff=group['clear'],
                other_matching_files=peers, other_flags=other_flags)
        result.append(row)
    return result
