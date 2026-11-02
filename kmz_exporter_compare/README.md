# KMZ Exporter & Compare

Export a QGIS layer tree to KMZ or KML, reuse icons and balloons from a reference KMZ, and compare folder counts, names, and coordinates.

- **QGIS:** 3.28 through 4.99 (Qt 5 and Qt 6)
- **License:** GNU GPL v2 (see `LICENSE`)
- **Data:** local project layers and files you choose. This plugin does not download data or sign in to a website.

## Install

In QGIS: Plugins → Manage and Install Plugins → Install from ZIP, and choose a zip whose top folder is `kmz_exporter_compare`.

Or copy that folder to:

`[QGIS profile]/python/plugins/kmz_exporter_compare`

Restart QGIS. The menu and toolbar entry are **KMZ Exporter & Compare**. The window title shows the version.

## What you can do

1. **Layer tools** (home, left): clear features, turn editing on, and save/close apply to every vector layer. Copy as empty and copy layer use only the layer selected in the Layers panel. Clear asks you to type OK, then confirm again.
2. **Export KMZ:** choose layers, export names, display fields, categories, and an optional plain KML. Point icons and category colors match the QGIS map: single, categorized, and graduated symbols are written as they appear. The last save folder is remembered. You can cancel a long export.
3. **Manual styling:** pair source and reference folders, then apply icons and balloons.
4. **Automatic styling:** apply a reference KMZ when folder names already match.
5. **Coordinate compare:** drag-pair layers, or auto-match names. Distance uses the **project CRS**. Folder layers without geometry are hidden. **Empty layers** (bottom right) shows or hides layers with zero features; they are shown by default. Results go into a **KMZ comparison** group unless **Add to project** is off. **Clear pairs** removes every pair.
6. **Layer compare:** counts, Name values, or point/line/polygon totals. Copy the result or save it as text or CSV.

Home toolbar: Help, Import settings, Export settings, Language, then Settings. Settings restores default window sizes or clears remembered options. The interface language stays. Language choices are Chinese, English, Spanish, French, and Arabic.

## Known limits

- Very large layers are compared with a spatial index, but a big batch can still take time. Use Cancel.
- If a coordinate transform fails, those features are skipped and counted in the summary.
- The language catalogs cover the main window, job pages, help, and the messages this plugin shows. A few rare engine notes may stay in Chinese.
- Page: https://yuyouhui.online/tools/qgis/kmz-exporter-compare/
- Source: https://github.com/AutoFYQ323/kmz-exporter-compare
- Screenshots are optional on plugins.qgis.org and are not part of the zip.

## Pack a release zip

From the folder that contains `kmz_exporter_compare`:

```text
python pack_release.py
```

The zip omits `__pycache__`, `.pyc` files, `check_i18n.py`, `tests/`, and this README. The translation check still runs before the zip is written.

## Tests without QGIS

```text
python -m unittest discover -s kmz_exporter_compare/tests -p "test_*.py"
```
