# Third-party notices

The MIT license applies to NAS Audio Finder application source only.

- **Python / Debian base image:** official `python:3.12-slim-bookworm` image;
  upstream licenses and package notices remain in the image. Python source and
  license: https://www.python.org/downloads/source/ and https://docs.python.org/3/license.html.
  Debian package sources: https://sources.debian.org/.
- **FFmpeg / FFprobe static tools:** John Van Sickle's unmodified FFmpeg 7.0.2
  amd64 static build, distributed under GPLv3. The image retains the supplied
  GPLv3 license and build readme under `/usr/local/share/nas-audio-finder/`.
  Upstream build/download and corresponding source links:
  https://johnvansickle.com/ffmpeg/ and https://johnvansickle.com/ffmpeg/release-source/.
  FFmpeg release sources: https://ffmpeg.org/releases/ffmpeg-7.0.2.tar.xz.
  The build readme lists linked dependency versions and retains upstream notices.
- **Source-built images:** the Dockerfile installs Debian's FFmpeg/FFprobe
  packages rather than the static binaries; Debian's package license/source
  notices apply to those builds.

Release provenance records the base image manifest and tool archive SHA256.
The v1.0.0 image includes FFmpeg and FFprobe; v1.1.0 includes only FFprobe.
