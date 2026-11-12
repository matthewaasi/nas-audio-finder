# NAS Audio Finder v2.2.0 — Folder context for authenticity warnings

Flagged tracks now call out when other matching files in the same folder completed
spectral screening without a suspicious cutoff, making an isolated warning more
plausibly a false positive—especially when the tracks share a source.

## What's new

- Counts of qualifying peers beside suspected lossy-source and possible-upsampling warnings.
- Highlighted false-positive guidance for isolated warnings and mixed-evidence guidance
  when other files in the folder are also flagged.
- Context in scan history and a separate **Authenticity folder context** CSV column.
- Only peers with sufficient active broadband material and no suspicious cutoff count;
  silence, unsupported/short files, errors and unscanned files are excluded.

Peer results remain **inconclusive, not verified lossless**. The original warning
is never cleared. Folder context is qualitative and cannot establish source history.
Only matching results in the immediate folder are compared, after an error-free
completed scan. Use broad filters to include the rest of an album.

## Download and upgrade

Download `nas-audio-finder-v2.2.0-amd64.tar` and `unraid-template.xml`.

```sh
docker load -i nas-audio-finder-v2.2.0-amd64.tar
```

Stop the existing container, back up `/config`, set the Unraid Repository field to
`nas-audio-finder:2.2.0`, and recreate with the same music and appdata mappings.
A restart alone does not replace the image. The archive targets Linux amd64.

**Run a new authenticity scan after upgrading.** Historical results remain unchanged.
The analysis cache is upgraded automatically and existing files are reanalyzed once.
Settings, history and quarantine data are preserved; no audio files are modified.

## Validation

43 local tests passed, including real audio, folder scope, mixed/isolated warnings,
cache behavior, cancelled/error scans, history and CSV export. JavaScript syntax
validation passed. Release CI builds the Linux amd64 image and checks real audio,
API/CSV output, and mixed-to-isolated context across cached container scans.
Unraid-specific performance remains unverified.

[Full changelog](https://github.com/matthewaasi/nas-audio-finder/blob/v2.2.0/CHANGELOG.md) ·
[Operations guide](https://github.com/matthewaasi/nas-audio-finder/blob/v2.2.0/docs/OPERATIONS.md)
