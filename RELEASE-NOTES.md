# Matt's Audio Scout v2.4.1

- The web app now displays the name Matt's Audio Scout.
- The Unraid template includes the new icon.

## Install or upgrade on Unraid

Download `nas-audio-finder-v2.4.1-amd64.tar` and `unraid-template.xml`. Load the image with:

```sh
docker load -i /mnt/user/appdata/nas-audio-finder-v2.4.1-amd64.tar
```

For an existing installation, edit the container and set **Repository** to
`nas-audio-finder:2.4.1`. Keep the existing music and config mappings and apply
the changes. To add the new icon to an existing container, set **Icon URL** in
Advanced View to:

```text
https://raw.githubusercontent.com/matthewaasi/nas-audio-finder/main/docs/assets/icon.png
```
