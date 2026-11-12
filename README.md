# NAS Audio Finder

Self-hosted audio metadata search and library cleanup for **Unraid and Docker**.
Scan files directly on the NAS, inspect matches in a web GUI, and quarantine
unwanted files with a restore option. No cloud service and no audio playback.

## v2.0.0: library management

| Feature | Behavior |
| --- | --- |
| Quarantine and restore | Move selected files out of the library; restore to the original path without overwriting existing files |
| Optional retention cleanup | Automatically purge expired quarantine items only after you explicitly enable and acknowledge the policy |
| Saved presets | Save date, duration, format, metadata, health and duplicate-analysis settings |
| Persistent results and history | Reopen previous results, restore partial checkpoints after a restart, retain the most recent 30 scans by default |
| Scheduled scans | One daily UTC scan using a saved preset; never automatically deletes or quarantines scan results |
| Audio health | Identify unreadable/no-audio files, zero duration, optional low lossy bitrate and optional full-decode errors |
| Metadata filters | Artist, album, codec, bitrate, sample rate and file size |
| Duplicates | SHA256 exact-file groups and optional perceptual acoustic candidates across formats |

Existing recursive searches, format checkboxes, date and duration filters,
adjustable readers, cancellation, sorting, pagination, CSV export, and confirmed
permanent deletion remain available. Supported extensions: M4A, MP3, FLAC, WAV,
AAC, OGG, Opus, AIFF/AIF, WMA, and APE. Default filter: seven days, 25–35 seconds.

## v2.1.0: lossless authenticity screening

The optional **Check lossless authenticity** scan flags recognized lossy codecs,
suspected lossy-to-lossless transcodes, and possible upsampling. Results include
evidence in the web UI and CSV, with caching, presets, and scan-history support.
This is heuristic screening and cannot prove the original source was lossless.
See [the operations guide](docs/OPERATIONS.md#lossless-authenticity-screening).
Download the v2.1.0 release assets below, or build from source. Existing v2.0.0 images do not include this feature.

## Download and install on Unraid

[Download v2.1.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.1.0)
and get **`nas-audio-finder-v2.1.0-amd64.tar`** plus **`unraid-template.xml`**.
The prebuilt image targets Linux x86-64. No local image build is required.

1. Copy both files to your Unraid appdata share.
2. In the Unraid terminal:

   ```sh
   docker load -i /mnt/user/appdata/nas-audio-finder-v2.1.0-amd64.tar
   mkdir -p /boot/config/plugins/dockerMan/templates-user
   cp /mnt/user/appdata/unraid-template.xml /boot/config/plugins/dockerMan/templates-user/my-nas-audio-finder.xml
   ```

3. Open **Docker → Add Container**, select **nas-audio-finder**, and verify:

   | Setting | Host example | Container |
   | --- | --- | --- |
   | Repository | `nas-audio-finder:2.1.0` | Locally loaded image |
   | Web port | `8099` | `8080/TCP` |
   | Music library | `/mnt/user/media/Music` — change to your actual local folder | `/music`, read/write for file actions |
   | Appdata | `/mnt/user/appdata/nas-audio-finder` | `/config`, read/write |
   | Permissions | PUID `99`, PGID `100` by default | Change if your library uses different permissions |

4. Apply and open `http://YOUR-UNRAID-IP:8099`.

Use local Unraid folders, not an SMB mount back to the NAS. The images are
release assets, not Docker Hub/GHCR images; do not request a registry pull.

### Upgrade from v1.x or v2.0.0

Stop the container and back up its `/config` directory. Load the new archive,
set the existing template's Repository to `nas-audio-finder:2.1.0`, and recreate
the container with the same music/appdata mappings. A restart alone does not
replace the image. SQLite tables are added without removing the v1 duration
cache; the first v2 scan rereads metadata to populate richer fields. Library
files are not changed by upgrading or scanning.

Quarantine defaults to `/music/.nas-audio-finder-quarantine` and is excluded
from scanning. No new volume mapping is necessary. Keep both `/config` and the
quarantine files to preserve restore information. For a separate quarantine
volume, map a dedicated writable folder and set `QUARANTINE_ROOT` to that mount;
do not change the root while it contains quarantined files.

## Safety and analysis scope

- Quarantine is the primary action. Restore never overwrites an existing path.
- Permanent delete and quarantine purge require confirmation. **They cannot be undone.**
  Container-local deletion may bypass SMB recycle-bin plugins.
- Automatic quarantine cleanup is **disabled by default** and requires explicit
  acknowledgement. Once enabled, it also applies to already quarantined files.
- Schedules only scan. They never act on matches. Retention cleanup is a separate,
  explicitly enabled policy for files you already quarantined.
- Size, timestamp, device and inode checks refuse changed files. Symlinks are
  skipped. Avoid other applications moving/replacing files during file actions;
  path-based checks cannot eliminate every filesystem race.
- SHA256 means identical file bytes, including tags. Acoustic grouping is
  approximate, uses up to the first 120 seconds, skips silence/featureless
  signatures, and compares bounded near-duration candidates. False positives
  and missed matches are possible. Review every candidate; nothing is deleted
  automatically because it is marked a duplicate.
- Hashing/full decoding read entire files; acoustic analysis decodes up to 120
  seconds. All are opt-in and can increase CPU, disk traffic and scan time.
- Duplicate groups cover the **matching results of that scan**. Use all dates,
  broad durations and chosen formats to check a wider library.

## Usage

See [Operations guide](docs/OPERATIONS.md) for presets, history, UTC scheduling,
quarantine management, health statuses, persistence, permissions, and tuning.
[CHANGELOG.md](CHANGELOG.md) covers every release.

| Release | Description |
| --- | --- |
| [v2.1.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.1.0) | Lossless authenticity screening, evidence and cached results |
| [v2.0.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v2.0.0) | Library management, quarantine, schedules, health checks, richer filters, duplicates |
| [v1.1.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.1.0) | Original metadata-only version |
| [v1.0.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.0.0) | Original version with browser playback |

## Development and validation

Python's standard library supplies HTTP, SQLite, queues, hashing and persistence.
FFprobe reads metadata. FFmpeg is included **only for optional decoding and
acoustic analysis**, not for browser playback. Application source is MIT licensed;
bundled tools retain their upstream licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).

```sh
python -m unittest discover -s tests -v
node --check static/app.js
docker build -t nas-audio-finder:dev .
```

30 tests completed successfully (29 passed; one Windows symlink test skipped). Tests include real
WAV, FLAC, MP3 and fragmented M4A files, full decoding, cross-format acoustic
matching, cross-volume moves, overwrite/tampering protections, persistence,
scheduling and API confirmation flows. Browser QA verified a scan and metadata
results. Image configuration, source contents and layer SHA256s are verified.
The build host has no Docker/Linux runtime, so Linux container startup and
performance on Unraid remain unverified in this environment.

Use on a trusted LAN. Set `APP_PASSWORD` for Basic Auth (username `admin`) and
use HTTPS through a reverse proxy for access outside that LAN. Multiple tabs
share one scanner, current result view, presets and configuration.
