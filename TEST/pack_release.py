# -*- coding: utf-8 -*-
"""Build a plugin zip for QGIS.

Run from the project folder or from TEST:

    python TEST/pack_release.py

The zip is written in TEST. Its top folder is kmz_exporter_compare.
"""

import configparser
import pathlib
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PLUGIN = ROOT / "kmz_exporter_compare"
OUT = HERE / "kmz_exporter_compare.zip"
SKIP_DIRS = {"__pycache__", "tests"}
SKIP_FILES = {"check_i18n.py", "README.md"}


def _check_metadata():
    """QGIS reads metadata.txt with ConfigParser; continuation lines must be indented."""
    path = PLUGIN / "metadata.txt"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parsed = parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise SystemExit("metadata.txt parse failed: {0}".format(exc))
    if not parsed or "general" not in parser:
        raise SystemExit("metadata.txt missing [general]")
    general = parser["general"]
    for key in ("name", "qgisMinimumVersion", "description", "version", "author", "email"):
        if key not in general or not str(general.get(key, "")).strip():
            raise SystemExit("metadata.txt missing required key: {0}".format(key))
    version = general.get("version", "").strip()
    if not version:
        raise SystemExit("metadata.txt version is empty")
    print("metadata ok: version={0}".format(version))


def main():
    _check_metadata()
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
