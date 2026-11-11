# Changelog

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
