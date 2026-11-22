# v2.4.0 — Parallel FLAC extraction and pagination

- Scan and extract multiple files in parallel. The M4A to FLAC tab defaults to four workers and accepts 1 to 32.
- Browse extraction results 100 files at a time. **Select all ready files** selects eligible files across every page, and individual selections persist while paging.
- Decoded-audio verification still runs before each original is deleted.

## Install or upgrade on Unraid

Download `nas-audio-finder-v2.4.0-amd64.tar` and `unraid-template.xml`. Load the image with:

```sh
docker load -i /mnt/user/appdata/nas-audio-finder-v2.4.0-amd64.tar
```

Set the container repository to `nas-audio-finder:2.4.0` and recreate it with the existing music and config mappings.
