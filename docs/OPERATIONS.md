# NAS Audio Finder v2 operations

## Searches and presets

Choose formats in the checkbox dropdown. Dates are file modification timestamps
in a rolling window; **0 days** means all dates. Future timestamps are excluded.
Duration bounds are inclusive. Leave Subfolder empty to scan the mounted root.
Expand metadata filters for artist/album/codec substring filters, bitrate in
kbps, sample rate in Hz and size in MiB. Empty numeric fields mean unrestricted.
Save the current filters under a preset name; select and Load to reuse them.
Saved presets survive restarts and include health/duplicate options.

## Health checks

Metadata statuses: `metadata-ok`, `zero-duration`, `unreadable`, and optional
`low-bitrate`. The low-bitrate threshold applies only to known lossy codecs,
not FLAC/ALAC/APE/WavPack/PCM. Full decode is opt-in and produces `decode-ok` or
`decode-error`. Hover the health column for diagnostic detail. FFprobe failures
also appear in the error log. A metadata check alone does not prove that the
entire file decodes correctly.

The default health view includes matching files plus unreadable candidates
whose metadata cannot be trusted. These may not satisfy duration/tag filters.
The Health issues view deliberately ignores duration bounds for problematic
files (zero duration could otherwise never match a 25–35-second filter).
Healthy-only excludes all flagged files. Other metadata filters still apply
when the relevant metadata is available.

## Exact and acoustic duplicates

Select SHA256, acoustic, both, or off before scanning. SHA256 reads the whole
file and groups identical bytes. Different tags or containers change this hash.
Acoustic analysis decodes mono 8 kHz PCM from up to the first 120 seconds,
builds time-varying spectral band signatures and compares near-duration
candidates. Comparisons allow small alignment differences. A bounded index
limits candidate comparisons to protect large-library performance; results
are approximate and not exhaustive. Silence and featureless tone signatures
do not produce acoustic matches. Full songs with matching introductions can
still be different recordings. Review candidates before acting.

Only matching scan results are grouped. Use 0 days and a broad duration range
for a library-wide duplicate search. Duplicate groups persist with history;
they do not automatically select a copy to keep or remove. Use the Duplicate
groups only checkbox to narrow the results table/export.

## Persistent results and history

Results, errors, settings, presets, schedules and quarantine records live in
SQLite under `/config/durations.sqlite3`. The last viewed scan reopens after a
restart. Running scans are checkpointed about every 30 seconds; committed
partial results are restored as interrupted and do not automatically resume.
Loading a history changes the result view for all connected browsers. File
actions still verify that each historical file matches its saved signature.

History retains the latest 30 scans by default; `HISTORY_LIMIT` accepts 1–1000.
Older scan results are removed after a new scan completes. Quarantine manifests
are independent and are not removed by scan-history pruning. The UI lists up
to 100 recent scans. Cached metadata is invalidated when size/timestamp changes;
deep health validation is rerun when requested. Only one container may use an
appdata database at a time. Back up appdata while the container is stopped.

## Scheduling

Save a preset, choose it in Scheduled scans, set HH:MM in **UTC**, enable and
save. There is one daily schedule. It runs once per UTC day after that time,
waiting if the scanner is busy. If the container starts after the scheduled
time, it can perform that day's pending scan. It does not run while stopped
and does not replay every missed day. Removing its preset prevents future
runs until a valid preset is selected. Scheduled scans never modify library
files or quarantine their results.

## Quarantine, restore and cleanup

Select results and choose Quarantine. Review the complete path list and confirm.
Files move to `/music/.nas-audio-finder-quarantine` by default, named with unique
IDs. This location is always excluded from scanning. Moves on one filesystem
use a hard-link/unlink operation; cross-volume moves use an exclusive copy,
flush, metadata preservation and source-signature check before unlinking.
The manifest is written before moving. Interrupted moves are reconciled on
startup or marked needs-review without automatically deleting either copy.

Use the Quarantine table to restore selected files or permanently purge them.
Restore refuses existing destinations and file-change mismatches. A failed
cross-volume move can leave a partial file in quarantine; inspect needs-review
entries and the log manually. Never remove or rearrange manifest/data files
outside the app while operations are running.

Automatic cleanup is off. To enable it, expand its settings, choose retention
days, check Enable, save and acknowledge permanent cleanup. Existing items are
also subject to the policy. Cleanup runs when idle and refuses modified items.
It permanently deletes only previously quarantined files older than the policy.
Disabling the policy stops future cleanup, not a file action already underway.

Permanent delete from results remains available separately. Purge and delete
cannot be undone and can bypass SMB recycle plugins. Confirmation tokens expire
after two minutes. Errors and per-action counts remain visible. Avoid concurrent
file replacements: filesystem checks do not eliminate every path race.

## Permissions and tuning

Map music locally to `/music`, cache to `/config`; default PUID/PGID are 99/100.
File actions require write access to parent directories. Startup changes ownership
only on appdata and known SQLite files, never on the music tree. A read-only music
mount supports scanning/export; file actions will report permission failures.

Use 4 readers initially; compare 8/16 according to CPU and storage. Full decoding
and acoustic analysis use CPU; hashing uses full-file disk I/O. Progress reports
cumulative analysis worker-seconds, which can exceed wall time. Original v1
duration cache is retained but richer v2 metadata requires one fresh probe.

Use `docker logs nas-audio-finder` for startup errors. The UI shows the latest 100
stored errors; the downloadable log retains up to 2,000 per operation. Use generic
host paths in shared support reports, and never publish your password or appdata.

## Lossless authenticity screening

Enable **Check lossless authenticity** in the advanced scan options. To cover a
library, set modified days to 0, use a broad duration range, and select all desired
formats. Analysis runs only on matching files. The option is off by default and
is included in saved presets and scheduled scans.

The Authenticity column and CSV export include the status and evidence:

- `not-scanned`: the option was off, or the file could not be analyzed.
- `lossy-codec`: a recognized lossy codec, even when the filename suggests otherwise.
- `suspected-lossy-source`: a sharp, consistent high-frequency cutoff in at least
  two sampled excerpts of a lossless encoding.
- `possible-upsampling`: high sample rate audio with a consistent cutoff near
  ordinary sample-rate bandwidth limits.
- `inconclusive`: no consistent suspicious cutoff, insufficient material, or an
  unsupported encoding. **This is not a certificate of a lossless source.**
- `analysis-error`: a decoder or analysis error; separate from audio health.

Three 4-second excerpts are taken near the beginning, middle and end. The first
audio stream is used, with up to two channels analyzed separately. Rates above
96 kHz are analyzed at 96 kHz; checks look for edges between 12 and 24 kHz.
Hann-windowed 4096-sample FFTs estimate band power. The heuristic requires active,
broadband material, a drop over 35 dB, and agreeing cutoff estimates within 750 Hz.
Sampling can miss defects elsewhere and does not validate bit depth. Naturally
band-limited recordings, filtering, and mastering can trigger the same pattern;
high-quality lossy transcodes may evade detection. No accuracy percentage is claimed.
WavPack hybrid mode and unknown codecs remain inconclusive.

Successful results are cached with the existing file-size/modification-time
metadata cache and an analysis version, and persist in scan history. Changing the
file invalidates the cache; analysis errors are retried. Like the metadata cache,
a replacement preserving both size and timestamp can evade invalidation. The
scan adds CPU and disk work, supports cancellation, and never acts on files.

Build the updated source with `docker build -t nas-audio-finder:2.1.0 .`.
The published v2.0.0 image archives do not contain this feature. Download v2.1.0 for a prebuilt image; existing v2.0.0 assets remain unchanged.
