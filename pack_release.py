# -*- coding: utf-8 -*-
"""Build a plugin zip for QGIS. Run from this folder (the parent of kmz_exporter_compare)."""

import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
PLUGIN = ROOT / "kmz_exporter_compare"
OUT = ROOT / "kmz_exporter_compare.zip"
SKIP_DIRS = {"__pycache__", "tests"}
SKIP_FILES = {"check_i18n.py", "README.md"}


def main():
    check = subprocess.run([sys.executable, str(PLUGIN / "check_i18n.py")], check=False)
    if check.returncode != 0:
        raise SystemExit(check.returncode)
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in PLUGIN.rglob("*"):
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts) or path.name in SKIP_FILES or path.suffix == ".pyc":
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(OUT)


if __name__ == "__main__":
    main()
