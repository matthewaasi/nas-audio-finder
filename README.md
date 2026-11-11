# NAS Audio Finder — v1.0.0

This tag preserves the original version with audio playback. See the main branch for v1.1.0.

A lightweight, self-hosted audio metadata search tool for **Unraid and Docker**.
Find audio files by modification date and duration, inspect matches in a web GUI,
export CSV, and permanently delete selected files after confirmation.

Built for large music libraries: scan directly on the NAS instead of opening
thousands of files over SMB from a desktop computer.

## Releases

| Version | What it includes | Docker image archive |
| --- | --- | --- |
| **[v1.1.0 — current](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.1.0)** | Metadata search, export, and deletion; no playback | `nas-audio-finder-no-playback-amd64.tar` |
| [v1.0.0](https://github.com/matthewaasi/nas-audio-finder/releases/tag/v1.0.0) | Original Docker release with browser playback and compatible MP3 conversion | `nas-audio-finder-unraid-amd64.tar` |

Both releases target **Linux x86-64 (`linux/amd64`)**. Each includes an Unraid
template, source ZIP, checksums, and image provenance. Images are loaded from
release assets; they are **not published to Docker Hub or GHCR**.

## Features

- Search recursively by file modification date and inclusive duration range.
- Choose formats using a dropdown with checkboxes: M4A, MP3, FLAC, WAV, AAC,
  OGG, Opus, AIFF/AIF, WMA, and APE.
- Defaults: modified in the last seven days, duration 25–35 seconds.
- FFprobe metadata extraction, including fragmented M4A with zero main headers.
- Persistent SQLite cache; unchanged files reuse their duration.
- Adjustable concurrency (1–32 readers), cancellation, timing, and error reports.
- Sort, filter, paginate, and select results across pages.
- Export matching metadata to CSV.
- Confirmed permanent deletion with checks for files changed since scanning.

## Install on Unraid using `docker load`

1. Download the `.tar` image and `unraid-template.xml` from the desired release.
2. Copy them to your Unraid appdata share.
3. Open the Unraid terminal. For v1.1.0:

   ```sh
   docker load -i /mnt/user/appdata/nas-audio-finder-no-playback-amd64.tar
   mkdir -p /boot/config/plugins/dockerMan/templates-user
   cp /mnt/user/appdata/unraid-template.xml /boot/config/plugins/dockerMan/templates-user/my-nas-audio-finder.xml
   ```

4. Open **Docker → Add Container** and select **nas-audio-finder** in Template.
5. Use repository `nas-audio-finder:1.1.0` for the current release. The archive
   also supplies `nas-audio-finder:local`. The v1.0.0 archive supplies `:local`.
6. Verify your mappings:

   | Setting | Host | Container |
   | --- | --- | --- |
   | Web GUI | Port `8099` | Port `8080/TCP` |
   | Music library | Your local folder, e.g. `/mnt/user/media/Music` | `/music` (read/write for deletion) |
   | Persistent cache | `/mnt/user/appdata/nas-audio-finder` | `/config` (read/write) |
   | Permissions | `PUID=99`, `PGID=100` by default | Change to match library access |

7. Apply and open `http://YOUR-UNRAID-IP:8099`.

Use a **local Unraid path**, not an SMB mount back to the NAS. Paths are
case-sensitive. Do not request a registry pull for these locally loaded images.
The Unraid template can be downloaded directly from each release.

### Upgrade or switch versions

Stop the container, load the desired archive, and **recreate** the container
using your template and existing mappings. A restart alone does not replace its
image. Keep `/config` to preserve the duration cache. Both original archives
include the `:local` tag, so loading one changes which image that tag references.
For v1.1.0 use the immutable version tag `:1.1.0` to avoid that ambiguity.

### Run with Docker directly

After loading v1.1.0:

```sh
docker run -d --name nas-audio-finder --restart unless-stopped --stop-timeout 75 \
  -p 8099:8080 -e PUID=99 -e PGID=100 \
  -v /path/to/music:/music:rw \
  -v /path/to/appdata:/config:rw nas-audio-finder:1.1.0
```

Set `APP_PASSWORD` to require a web password (username `admin`). Use this app on
a trusted LAN; use HTTPS through a reverse proxy for access beyond that network.

## How it works

A Python HTTP server provides the web GUI and API. A directory walker checks
extensions and timestamps before adding recent files to a bounded queue.
Concurrent FFprobe workers read audio metadata without decoding the whole track.
SQLite caches duration by relative path, size, and modification timestamp.

Results stay on the server and are paginated to the browser. Deletion uses a
short-lived confirmation and rechecks size, timestamp, device, and inode before
unlinking. Symlinks and symlinked directories are skipped.

**Deletion is permanent.** Container-local deletion can bypass SMB recycle-bin
plugins. Review every selected path and maintain appropriate backups. Avoid
concurrent moves/replacements while deleting; path checks do not eliminate all
filesystem races. Mount `/music` read-only for scanning/export only.

## Development and validation

The default branch is v1.1.0. The `v1.0.0` tag preserves playback source.
See [CHANGELOG.md](CHANGELOG.md) for release history and [docs/OPERATIONS.md](docs/OPERATIONS.md)
for detailed behavior, cache management, and troubleshooting.

```sh
python -m unittest discover -s tests -v
node --check static/app.js
docker build -t nas-audio-finder:dev .
```

The Dockerfile builds from source using Debian FFprobe packages. Distributed
image archives use verified official Python base layers and upstream static
FFprobe tools (plus FFmpeg in v1.0.0); provenance is attached to each release.

Application tests and archive/layer integrity checks passed on Windows. The
Linux containers could not be runtime-tested in the build environment. Actual
Unraid startup, library throughput, and format compatibility need verification
on the target server. The symlink test is skipped on Windows without symlink
privileges and is intended to run on Linux as well.

## License and dependencies

The application source is MIT licensed. Bundled Python, Debian components, and
FFmpeg/FFprobe retain their respective upstream licenses. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and release provenance.
