# KMZ Exporter & Compare

Export a QGIS layer tree to KMZ or KML, reuse icons and balloons from a reference KMZ, and compare folder counts, names, fields, and coordinates.

- **QGIS:** 3.28 through 4.99 (Qt 5 and Qt 6)
- **Version:** 1.0.4
- **License:** GNU GPL v2 (see `LICENSE`)
- **Data:** local project layers and files you choose. This plugin does not download data or sign in to a website.

## Install

In QGIS: Plugins → Manage and Install Plugins → Install from ZIP, and choose a zip whose top folder is `kmz_exporter_compare`.

Or copy that folder to:

`[QGIS profile]/python/plugins/kmz_exporter_compare`

Restart QGIS completely. The menu and toolbar entry are **KMZ Exporter & Compare**. The window title shows the version.

## What you can do

Home shows five jobs. The window is independent on the system taskbar and can minimize on its own.

1. **Export KMZ:** choose layers, export names, display fields, categories, and an optional plain KML. Point icons and category colors match the QGIS map: single, categorized, and graduated symbols are written as they appear. A folder with no vector layer under it is listed and, when checked, is written as an empty folder. Bottom buttons: Select all/none, Back to home, Save settings, Export KMZ.
2. **Manual styling:** select the layer to replace and a reference KMZ, pair folders when names differ, then apply icons and balloons. Geometry and attributes stay from the layer to replace.
3. **Automatic styling:** same layout; apply a reference KMZ when folder names already match.
4. **Coordinate compare:** drag-pair layers, or auto-match names. Distance uses the **project CRS**. Top buttons: Back to home, Save settings, Batch run. Results go into a **KMZ comparison** group unless **Add to project** is off.
5. **Layer compare:** feature counts and Name, point/line/polygon totals, or layer names and fields including field order (table: QGIS, KMZ, type, result). Copy the result or save a report.

Layer panel shortcuts such as clear data, edit mode, and copy layer are in **Layers Panel Tools**, not on this home page.

Home toolbar (evenly spaced): Language, Import settings, Export settings, Help, Settings. Job pages open centered on the QGIS window; Back to home or Esc returns the window to where the home page was.

## Known limits

- Very large layers are compared with a spatial index, but a big batch can still take time. Use Cancel on the progress dialog.
- If a coordinate transform fails, those features are skipped and counted in the summary.
- The language catalogs cover the main window, job pages, help, and engine result messages. Non-Chinese UI falls back to English when a line is missing.
- Page: https://yuyouhui.online/tools/qgis/kmz-exporter-compare/
- Source: https://github.com/AutoFYQ323/kmz-exporter-compare
- Screenshots are optional on plugins.qgis.org and are not part of the zip.

## Pack a release zip

From the project folder (the parent of `kmz_exporter_compare`):

```text
python TEST/pack_release.py
```

The zip is written in `TEST`. The script checks `metadata.txt` and translations first.

The zip omits `__pycache__`, `.pyc` files, `check_i18n.py`, `tests/`, and this README.

## Tests without QGIS

```text
python -m unittest discover -s kmz_exporter_compare/tests -p "test_*.py"
```
