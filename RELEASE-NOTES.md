# v2.3.0 — M4A to FLAC extraction

A new, separate **M4A to FLAC** WebGUI tab finds M4A files containing FLAC audio.
Select files and confirm to extract `Track.flac` beside `Track.m4a`, verify the
entire decoded audio, and permanently delete the M4A only after verification.
No re-encoding. AAC/ALAC and multiple audio streams are skipped. Existing FLAC
files are never overwritten; changed sources and failed conversions are retained.
Text metadata and modification times are preserved; embedded artwork is not copied.
The source filesystem must support hard links. Extraction jobs never run on a
schedule and do not resume automatically after a restart.

## Unraid installation or upgrade

Download `nas-audio-finder-v2.3.0-amd64.tar` and `unraid-template.xml`.
Stop the existing container and back up `/config`. Load the image with:

```sh
docker load -i /mnt/user/appdata/nas-audio-finder-v2.3.0-amd64.tar
```

Set the container repository to `nas-audio-finder:2.3.0` and recreate it using the
same `/music` and `/config` mappings. Music must be writable for extraction.
A restart alone does not replace the image. See README.md and docs/OPERATIONS.md.

Validation includes real FLAC-in-M4A fixtures, failure protection, and a Linux
container smoke test using a writable library mapping.
