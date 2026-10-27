"""Install a KiCad PCM plugin zip: extract its plugins/ folder to <dest>.

    python3 install_plugin.py <package.zip> <dest dir>
"""
import os
import sys
import zipfile

src, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(src) as zf:
    for info in zf.infolist():
        if not info.filename.startswith("plugins/") or info.is_dir():
            continue
        target = os.path.join(dest, info.filename[len("plugins/"):])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info) as fsrc, open(target, "wb") as fdst:
            fdst.write(fsrc.read())
print(f"installed {os.path.basename(src)} -> {dest}")
