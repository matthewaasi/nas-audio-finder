# Changelog

## [2.0.0] — 2026-11-11

### Added
- Quarantine, restore without overwrite, persistent manifests and interrupted-move recovery.
- Explicitly enabled retention cleanup for expired quarantine files (off by default).
- Saved search presets including formats, metadata filters and analysis options.
- Persistent results, interrupted-scan checkpoints, settings and scan-history loading.
- Configurable history retention (30 scans by default).
- One daily UTC scan schedule using a preset; no automatic actions on scan matches.
- Metadata filters for artist, album, codec, bitrate, sample rate and file size.
- Health views for unreadable/no-audio, zero-duration and low lossy-bitrate candidates.
- Optional full audio decoding to report corruption and decode failures.
- SHA256 exact duplicate groups and bounded perceptual cross-format similarity candidates.
- Richer result rows and CSV exports, plus duplicate-only filtering.

### Changed
- Quarantine is the primary file action; confirmed permanent deletion is still available.
- FFmpeg is included for optional analysis; browser playback remains removed.
- Days=0 searches all modification dates, excluding future timestamps.
- Added SQLite tables alongside the existing duration cache; rich metadata is probed afresh once.
- Generic UTC and server placeholders remain the distribution defaults.

### Validation and limitations
- 30 tests completed successfully (29 passed; one Windows symlink test skipped).
- Real WAV/FLAC/MP3/fragmented-M4A metadata, decoding and acoustic fixtures passed.
- Cross-volume moves, overwrite/tamper refusal, restore/purge, retention opt-in,
  restart persistence, daily scheduling and API confirmation flows checked.
- Browser scan/result QA passed. Image layer/source integrity verified.
- Acoustic results are approximate candidates, not proof of duplicate recordings.
- Linux image startup and Unraid throughput remain untested on the Windows build host.

## [1.1.0] — 2026-11-11

### Documentation update
- Replaced server-specific IP examples with `YOUR-UNRAID-IP`. Docker image binaries are unchanged.

### Removed
- Browser audio player, per-result Play buttons, and Previous/Next track controls.
- Original audio streaming and compatible MP3 conversion endpoints.
- FFmpeg converter executable from the prebuilt image; FFprobe remains for metadata.

### Changed
- Focused the web GUI on metadata search, inspection, export, and deletion.
- Reduced the image archive from 288,061,440 to 208,220,160 bytes.
- Added a `nas-audio-finder:1.1.0` image tag alongside `:local`.

### Preserved
- Multi-format checkbox dropdown, recursive date/duration filters, adjustable
  concurrency, SQLite duration cache, progress/timings, cancellation, error logs,
  sortable/filterable/paginated results, CSV export, and confirmed deletion.

### Validation
- Application/API checks cover removed playback routes and retained operations.
- All image layer checksums and embedded application files verified.
- Linux container runtime not tested in the Windows build environment.

## [1.0.0] — 2026-11-11

### Documentation update
- Replaced server-specific IP examples with `YOUR-UNRAID-IP`. Docker image binaries are unchanged.

### Added
- Initial Docker/Unraid version with a browser-based GUI.
- M4A, MP3, FLAC, WAV, AAC, OGG, Opus, AIFF/AIF, WMA, and APE format selection.
- Modified-date and inclusive duration filters; defaults of seven days and 25–35 seconds.
- FFprobe extraction supporting ordinary and fragmented M4A.
- Persistent SQLite cache, a bounded work queue, and 1–32 configurable readers.
- Progress counters, timing, cancellation, and downloadable error reports.
- Result filtering, sorting, pagination, multi-selection, and CSV export.
- Browser playback with byte-range seeking and optional compatible MP3 conversion.
- Confirmed deletion with file-change checks and partial-failure reporting.
- Optional HTTP Basic Auth, session-token checks, and same-origin mutation checks.
- Unraid template, Dockerfile, Compose configuration, and `docker load` archive.

### Validation
- Application tests and image archive/layer checks passed.
- Linux startup, actual FFprobe compatibility, and playback require target-server verification.

[1.1.0]: https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.1.0
[1.0.0]: https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.0.0

[2.0.0]: https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.0.0
