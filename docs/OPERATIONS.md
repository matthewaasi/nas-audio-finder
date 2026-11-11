# NAS Audio Finder for Unraid

A self-hosted Docker application that scans local music files by modified date
and duration. It includes a web GUI, persistent metadata caching,
CSV export, and confirmed permanent deletion. There are no cloud services, CDNs,
or JavaScript dependencies.

## Install on Unraid

The separately supplied `nas-audio-finder-unraid-amd64.tar` is a prebuilt
Docker-load image archive. To use it, copy it to your appdata share and run:

```sh
docker load -i /mnt/user/appdata/nas-audio-finder-unraid-amd64.tar
```

Then install the XML template using steps 2–4 below (skip `docker build`).
No image is published to a registry. Keep repository `nas-audio-finder:local`.
The prebuilt archive uses verified official Python layers plus static FFmpeg
tools; the Dockerfile below alternatively installs Debian FFmpeg packages.

If building from this source package instead, build once on your Unraid server.
Docker is already part of Unraid.

1. Extract the ZIP onto an Unraid share, for example
   `/mnt/user/appdata/nas-audio-finder-build`. The directory containing
   `Dockerfile` is the build directory.
2. Open the Unraid terminal and run, adjusting the first path to that directory:

   ```sh
   cd /mnt/user/appdata/nas-audio-finder-build
   docker build -t nas-audio-finder:local .
   cp unraid-template.xml /boot/config/plugins/dockerMan/templates-user/my-nas-audio-finder.xml
   ```

3. In **Docker → Add Container**, choose the `nas-audio-finder` user template.
   Keep the repository `nas-audio-finder:local` (the image you just built).
   Check these mappings before clicking Apply:

   | Setting | Host value | Container value |
   | --- | --- | --- |
   | Web port | `8099` | `8080` TCP |
   | Music library | `/mnt/user/media/Music` | `/music`, read/write |
   | App data | `/mnt/user/appdata/nas-audio-finder` | `/config`, read/write |
   | PUID / PGID | `99` / `100` by default | User and group with music access |

   The default music mapping assumes the SMB path `\\YOUR-UNRAID-IP\media\Music`
   corresponds to Unraid's `media` share with a `Music` subfolder. Confirm this
   on your server; share names and paths are case-sensitive. Use the local
   `/mnt/user/...` path, not an SMB mount back to the NAS itself.

4. Open **WebUI** from the container menu, or visit
   `http://YOUR-UNRAID-IP:8099` if that is your Unraid server's address.
5. Enable autostart in the Unraid Docker page if desired.

Alternatively, with Docker Compose installed:

```sh
docker compose up -d --build
```

Or launch directly after building:

```sh
docker run -d --name nas-audio-finder --restart unless-stopped --stop-timeout 75 \
  -p 8099:8080 -e PUID=99 -e PGID=100 -e TZ=America/Chicago \
  -v /mnt/user/media/Music:/music:rw \
  -v /mnt/user/appdata/nas-audio-finder:/config:rw nas-audio-finder:local
```

Do not launch both Compose and the Unraid template for the same instance.
Rebuild the local image to update; this image has no registry update feed.
After rebuilding or loading a new archive, recreate the container with the
local image. Do not request a registry pull. Compose users can use
`up -d --build --force-recreate` when building from source.

## Search and inspect results

- Leave Subfolder blank for the whole library; enter `Artist/Album` to narrow it.
- Select formats in the **Audio formats** dropdown using its checkboxes.
  Supported extensions: M4A, MP3, FLAC, WAV, AAC, OGG, Opus, AIFF/AIF, WMA, APE.
  The default selection is M4A, MP3, FLAC, and WAV. Extension matching ignores case.
- Defaults: last 7 × 24 hours, 25–35 seconds inclusive, four readers.
- Dates refer to each file's modification timestamp, not arrival/creation date.
  Future-dated files are excluded. The browser displays dates in its local zone.
- Start a scan. Results appear as files are processed. Cancel retains partial
  results. Select the formats before each scan; changing them requires a new scan.
- Adjust readers from 1 to 32. Start at 4; compare 8 and 16 for your storage.
  More readers can help SSDs or hurt spinning disks due to seek contention.
- Sort or filter results and navigate pages to inspect matching metadata.
- CSV exports every currently filtered result, not just the visible page.

## Delete files

Select individual rows, the current page, or **Select all matches** (all currently
filtered results, including other pages). Selections remain when paging/filtering;
the selected count is the deletion count. Clear selection to start over.

Deletion is disabled until the scan stops. The confirmation lists **every selected
path** and requires an acknowledgement. Confirmations expire after two minutes.
Successful deletions leave
the results and cache; failures remain listed with an error report.

**Deletion is permanent and bypasses any desktop recycle bin.** Unraid SMB recycle
plugins may not intercept local container deletions. Use an appropriate backup.
The app checks size, modification timestamp, inode, and device before unlinking.
Changed files are refused. Do not let other applications move/replace files during
deletion: path-based checks cannot eliminate every concurrent filesystem race.
Folders are never deleted; symlinks and symlinked directories are excluded.

Mount `/music` read-only for a scan-only deployment. Deletion then reports
a permission error. The app never changes library ownership or permissions.

## Performance and persistence

Directory enumeration and metadata readers run concurrently with a bounded queue.
Dates and extensions are checked before FFprobe opens a file. FFprobe handles
ordinary and fragmented M4A, plus the other formats, without decoding the audio
for scanning. It is limited to local file/pipe protocols. Unknown durations are
reported as errors, never treated as zero.

The SQLite cache in `/config` reuses duration when relative path, byte length, and
modification timestamp match. Cache writes are committed every 100 new durations
and at scan completion/cancellation. Stop the container before removing its cache
if you need fresh metadata. A restart retains the cache but clears scan results,
selections, and settings; rescan to reconstruct them. Only one container instance
should use a given appdata directory.

The GUI reports elapsed wall time, folder listing work, cumulative duration work,
and cached/read counts. Duration worker-seconds accumulate across parallel readers
and can exceed elapsed time. Rates are work-normalized averages, not disk bandwidth.
Timings update when individual operations finish. The error panel shows the latest
100 stored errors; the downloadable log retains the first 2,000 per operation.

FFprobe has a 60-second per-file timeout. Cancel interrupts active probes. Network
filesystem calls can still delay cancellation; local music mappings avoid that
network path. Audio playback and transcoding are not included. Only FFprobe is needed for metadata.

## Access and troubleshooting

This is a LAN application. Do not publish the port directly to the internet.
Set `APP_PASSWORD` to require HTTP Basic Auth (username `admin`); use an HTTPS
reverse proxy for access beyond your trusted LAN. Passwords in Basic Auth over
plain HTTP are not encrypted. Mutating requests also require a session token and
same-origin checks. There is one shared library/session for all browser tabs.

- **No files:** inspect `/music` mapping, case-sensitive subfolder, selected
  formats, the date window, future timestamps, and error panel.
- **Permissions:** ensure PUID/PGID can traverse/read the music tree and, for
  deletion, write its containing directories. Defaults are Unraid nobody/users.
- **Cache errors:** appdata must be writable. Startup changes ownership only on
  the config directory and known SQLite files, never on the music library.
- **Port busy:** change host port 8099; keep container port 8080.
- **Build fails:** Unraid needs internet access to fetch the Python base image
  and Debian FFmpeg packages. No registry account is needed.

## Validation

Run backend tests with `python -m unittest discover -s tests -v` and JavaScript
syntax checks with `node --check static/app.js`. Tests use temporary local files
and controlled metadata readers; no real music is deleted. The included tests
exercise scanning, format selection, caching, cancellation, deletion safeguards,
HTTP confirmation/CSRF flow, exports, and refusal of the removed playback endpoints.

The package was built on Windows without a Docker engine or connected Unraid
server. The actual Linux image build, NAS throughput, real FFprobe decoding, and
container startup must be verified after installation on Unraid.

Implementation references: [Unraid container mappings and settings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/),
[FFprobe metadata and JSON output](https://www.ffmpeg.org/ffprobe.html).
