# NAS Audio Finder v2.1.0 — Lossless authenticity screening

Adds an optional **Check lossless authenticity** scan to identify recognized lossy
codecs, suspected lossy-to-lossless transcodes, and possible upsampling.

## What's new

- Three short excerpts per matching lossless file, analyzed for consistent spectral cutoffs.
- A sortable Authenticity column with evidence, plus CSV status and evidence fields.
- Cached results, saved presets, daily schedules, persistent history and cancellation.
- Decoder errors reported separately and retried on later scans.
- No additional Python dependencies; analysis uses the FFmpeg already in the image.

**This is heuristic screening, not proof of a lossless original.** Mastering and
recording bandwidth can trigger similar cutoffs. High-quality lossy encodes may
be missed. Inconclusive does not mean verified lossless. No files are changed by scans.

## Download and upgrade

Download `nas-audio-finder-v2.1.0-amd64.tar` and `unraid-template.xml`.

```sh
docker load -i nas-audio-finder-v2.1.0-amd64.tar
```

Stop the existing container, back up `/config`, set the template Repository to
`nas-audio-finder:2.1.0`, and recreate with the same music and appdata mappings.
A restart alone does not update the image. Existing settings/history/quarantine
remain compatible. This archive targets Linux amd64.

Enable **Check lossless authenticity** under advanced scan options. For a whole
library, use all dates (`0` days), a broad duration range, and desired formats.

## Validation and limitations

36 tests passed locally, including real MP3-to-FLAC and FFmpeg/FFprobe fixtures.
JavaScript syntax validation passed. The release workflow also runs the tests,
builds the image, checks the version/API, and performs a container scan smoke test.
Unraid-specific behavior and large-library performance remain unverified.

See [CHANGELOG.md](https://github.com/matthewaasi/nas-audio-finder/blob/v2.1.0/CHANGELOG.md)
and the [operations guide](https://github.com/matthewaasi/nas-audio-finder/blob/v2.1.0/docs/OPERATIONS.md).
