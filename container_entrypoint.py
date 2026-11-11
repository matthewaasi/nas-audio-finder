"""Prepare only appdata, then drop privileges before serving the library."""
import os
from pathlib import Path

os.umask(0o002)
if os.getuid() == 0:
    uid = int(os.getenv("PUID", "99"))
    gid = int(os.getenv("PGID", "100"))
    config = Path(os.getenv("CONFIG_ROOT", "/config"))
    config.mkdir(parents=True, exist_ok=True)
    os.chown(config, uid, gid)
    for path in config.glob("durations.sqlite3*"):
        if path.is_file() and not path.is_symlink():
            os.chown(path, uid, gid)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
os.execvp("python", ["python", "/app/app.py"])
