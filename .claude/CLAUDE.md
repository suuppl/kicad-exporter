# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for dependency management (Python 3.13).

```bash
uv run main.py                              # GUI
uv run main.py hw/x.kicad_pro -t all -o out # headless CLI (same exports as the GUI)
uv add <package>                            # add a dependency
uv run pytest                               # run tests (once tests exist)
docker build -t kicad-exporter .            # CI image (KiCad + plugins + CLI)
docker run --rm -v "$PWD:/work" kicad-exporter hw/x.kicad_pro -t all -o export
```

wxPython is in the default `gui` dependency group; the CLI and the Docker image run
without it. The image uses KiCad's Python 3.11 (for `pcbnew`), so code must stay
3.11-compatible. After dependency changes regenerate `docker/requirements.txt`
(command in README.md).

## What this project is

**KiCad Export GUI** — a wxPython desktop app that provides a GUI front-end for `kicad-cli`. It automates common export workflows for KiCad electronics projects. The user picks a `.kicad_pro` file and output folder; all other paths are derived from the project name.

Three tabs:
1. **PCB Images** — runs `kicad-cli pcb render` to produce photorealistic PNG renders (resolution, side, background, quality, advanced camera options).
2. **Schematic** — runs `kicad-cli sch export pdf` → `<name>_schematics.pdf`.
3. **Layout** — runs `kicad-cli pcb export pdf` once per selected layer, then merges with `pdfunite` (poppler-utils) → `<name>_board_layers.pdf`.

## Architecture

### Source layout

```
main.py                    entry point — args → src.cli.main(), no args → GUI
Dockerfile                 CI image: kicad/kicad:9.0.7-full + Board2Pdf + Fabrication Toolkit + CLI
docker/                    image entry script, plugin installer, requirements, example CI workflow
src/
  cli.py                   headless front-end (argparse); runs targets in order via exports.py
  exports.py               make_*_job() factories + tool resolution — shared by GUI and CLI, no wx
  kicad_export_gui.py      KiCadExportFrame + KiCadExportApp — GUI state and event handlers
  gui_tabs.py              PcbTab, SchematicTab, LayoutTab (wx.Panel subclasses)
  app_theme.py             AppColors, AppFonts, make_app_colors(), make_app_fonts()
  render_command.py        RenderOptions dataclass, build_kicad_cli_command(), wrap_for_windows()
  export_job.py            ExportJob, ExportStep — subprocess/threading abstraction
  pcb_file.py              strip_3d_models(), make_bare_board_copy(), read_title_block()
  combined_pdf.py          build_combined_pdf() — title page + renders (fpdf2) + PDFs merged (pypdf)
  settings.py              AppSettings, load_settings(), save_settings()
  ui_constants.py          SIDES_FULL, BACKGROUNDS, QUALITIES, RESOLUTION_PRESETS
```

### Threading model

Long-running exports run on a daemon thread via `ExportJob.start()`. The thread posts
`(type, payload)` tuples to `KiCadExportFrame.log_queue` (`queue.Queue`). A `wx.Timer`
fires every 120 ms and drains the queue on the main thread via `_poll_log_queue`.

| Tuple | Meaning |
|-------|---------|
| `("line", str)` | Append to active tab's log `wx.TextCtrl` |
| `("progress", float)` | Set active tab's `wx.Gauge` (0–100) |
| `("done", bool)` | Export finished; re-enables buttons, shows log |

### Tab panel design

Each tab (`PcbTab`, `SchematicTab`, `LayoutTab`) is a `wx.Panel` subclass constructed with
`(parent, colors, fonts)` — no frame reference. All event handlers stay on `KiCadExportFrame`.
Tabs expose a minimal set of named widget attributes and `show_log(visible)` /
`show_advanced(visible)` (PcbTab only) methods that call `self.Layout()` internally.

### Tool resolution (src/exports.py)

| Tool | Lookup order |
|------|--------------|
| kicad-cli | Windows: `kicad-cli.exe` next to `kicad_cmd_path`, else `kicad-cmd.bat` wrapper; elsewhere PATH |
| KiCad Python (pcbnew) | `$KICAD_PYTHON`, `python.exe` next to `kicad-cmd.bat`, `python3` |
| board2pdf | `$KICAD_EXPORT_BOARD2PDF`, `settings.board2pdf_path` |
| Fabrication Toolkit | `$KICAD_EXPORT_FAB_PLUGINS_DIR`, `settings.fab_plugins_dir`, Windows auto-detect |

The Docker image sets the env vars, so Windows paths in a committed settings file are ignored there.

Job factories must not touch the filesystem when called — side effects such as clearing
`production/` belong in `ExportJob.on_start` (runs when the job starts).

### Windows PATH wrapping

On Windows, `kicad-cli` is not on PATH by default. Every command is wrapped:
```
cmd.exe /c ""<kicad-cmd.bat path>" && <original command>"
```
The path is stored in `%APPDATA%/kicad-export-gui/settings.json` and editable in the UI
(Project Paths card, visible on Windows only).

### Output path prepopulation

When the user selects or types a `.kicad_pro` path, the output folder is automatically set
to `<project_dir>/export/`. This happens in `_on_project_text_changed`.

### Layer detection

On project file change, `_detect_layers` reads the `.kicad_pcb` file, parses the
`(layers ...)` S-expression block, and builds `self._layers` (internal names) and
`self._layer_alias` (internal → display name map). All layers are selected by default;
the user can override via `wx.MultiChoiceDialog`.
