# Changelog

## [2.2.0] — 2026-11-12

### Added
- Same-folder peer counts beside suspected lossy-source and possible-upsampling warnings.
- False-positive guidance when other matching tracks show no suspicious cutoff and
  no other matching files are flagged; mixed evidence guidance when other files are flagged.
- Highlighted context in the web UI and a separate CSV context column, persisted in scan history.
- Tests for immediate-folder scope, excluded/unsupported/insufficient peers, mixed flags,
  silence, cancellation/errors, cached rescans, history, and CSV export.

### Changed
- Qualifying peers need enough active broadband audio in at least two sampled excerpts
  and no detected cutoff. Their status remains inconclusive, never verified lossless.
- Context is computed only after an error-free completed scan, from that scan's matching
  results. It is never cached as an intrinsic file property or used to clear warnings.
- Analysis cache version bumped for richer evidence; existing files are reanalyzed once
  when authenticity scanning is enabled. Old scan history and quarantine data are preserved.

### Validation and limitations
- 43 local tests passed with real FFmpeg/FFprobe fixtures, HTTP/API and CSV checks.
- Release CI tests and smoke scans cover mixed and isolated warnings in the built Linux image.
- Folder membership is context, not proof of a shared source or an accuracy estimate.
  Filters may exclude other album tracks; Unraid-specific throughput remains unverified.

## [2.1.0] — 2026-11-12

### Added
- Optional **Check lossless authenticity** scan for matching audio files.
- Recognized lossy-codec detection independent of the filename extension.
- Sampled spectral screening for suspected lossy-to-lossless transcodes and possible upsampling.
- A sortable Authenticity column with evidence, plus status and evidence in CSV exports.
- Versioned analysis caching, saved preset/schedule support, persistent scan results, and cancellation.
- Tests for spectral cutoffs, silence, tones, broadband audio, opposite channel phase,
  consensus, cancellation, cache invalidation, decoder retry, and real MP3-to-FLAC conversion.
- GitHub Actions release build: tests, Linux amd64 Docker image archive, Unraid template,
  source ZIP, SHA256 checksums, and build provenance.

### Behavior and limitations
- Disabled by default; no audio files are modified by authenticity scans.
- Decodes three 4-second excerpts near the beginning, middle, and end of matching lossless files.
- Reports lossy codec, suspected lossy source, possible upsampling, inconclusive,
  analysis error, or not scanned. Successful screening never certifies source provenance.
- Recording bandwidth and mastering may cause false positives; high-quality lossy
  encodes and defects outside the excerpts may be missed. Bit-depth authenticity is not tested.
- Existing v2.0.0 settings, cache, scan history, and quarantine data remain compatible.

### Validation
- 36 tests passed locally, including real FFmpeg/FFprobe fixtures and HTTP/API tests.
- JavaScript syntax validation passed.
- Docker image build and smoke checks run in the release workflow; Unraid-specific
  behavior and large-library performance still require target-system validation.

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

[2.1.0]: https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.1.0

[2.2.0]: https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.2.0
