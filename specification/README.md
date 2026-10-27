# KiCad Export GUI — Specification

## What the project is

KiCad Export GUI is a Python desktop application built with wxPython. It provides a graphical front-end for `kicad-cli`, the KiCad command-line tool, automating the most common export workflows for a KiCad electronics project.

The app is a single `wx.Frame` window. The user selects a `.kicad_pro` project file and an output folder; all other file paths (`.kicad_pcb`, `.kicad_sch`) are derived from the project name automatically.

---

## What the app does

### PCB Images Export (tab 1)

Renders a photorealistic 3-D image of the PCB by running `kicad-cli pcb render`. The user controls:

- **Resolution** — preset (720p / 1080p / 2K / 4K) or arbitrary pixel dimensions.
- **Side** — `top`, `bottom`, `left`, `right`, `front`, `back`, or `top + bottom` (two files).
- **Background** — `default`, `transparent`, `opaque`.
- **Quality** — `basic`, `high`, `user`.
- **Advanced options** (hidden by default, toggled by a checkbox):
  - Floor (shadow / post-processing), perspective projection.
  - Zoom, pan (X,Y,Z), pivot (X,Y,Z), rotate (X,Y,Z).
  - Light intensities: top, bottom, side, camera, side elevation.

Output: one PNG per requested side, written to the output folder.

### Schematic Export (tab 2)

Exports the project schematic to PDF by running `kicad-cli sch export pdf`. No user options beyond the shared project/output paths.

Output: `Project_schematics.pdf` in the output folder.

### Layout Export (tab 3)

Exports each selected PCB layer to a PDF by running `kicad-cli pcb export pdf` once per layer, then concatenates them into a single document using `pdfunite` (from `poppler-utils`). Layers are auto-detected by text-scanning the `.kicad_pcb` file. The user can override the selection via a `wx.MultiChoiceDialog`.

Output: `Project_board_layers.pdf` in the output folder. Intermediate per-layer PDFs are written to a temporary subdirectory and deleted after the merge.

---

## Technology

| Concern | Choice |
|---------|--------|
| Language | Python 3.13+ |
| GUI toolkit | wxPython 4.2+ |
| Dependency management | uv |
| External CLI | `kicad-cli` (ships with KiCad) |
| PDF concatenation | `pdfunite` (poppler-utils) |

---

## External dependencies

| Dependency | Required for | Notes |
|------------|-------------|-------|
| KiCad (`kicad-cli`) | all exports | On Windows, `kicad-cli` is not on PATH by default; the app wraps every command via `kicad-cmd.bat` to set up the environment first. |
| `pdfunite` | Layout Export only | Must be on PATH at runtime. |

---

## Source layout

```
main.py                       entry point — constructs wx.App, shows wx.Frame
src/
  __init__.py                 re-exports KiCadExportApp
  kicad_export_gui.py         KiCadExportFrame (wx.Frame) — all app state and event handlers
  gui_tabs.py                 TabsBuilder — constructs the three tab panels, mutates frame attrs
  render_command.py           build_kicad_cli_command(), build_cmd_exe_command()
  ui_constants.py             colour hex codes, dropdown option lists, resolution presets
  ui_helpers.py               dead code (tkinter mousewheel helper, unused)
  icons/                      PNG icons for toolbar buttons
```

---

## Architecture

### Main window

`KiCadExportFrame` owns all application state:

- Project and output paths (read from `wx.TextCtrl` inputs).
- Detected and selected layers (lists of strings).
- Layer alias maps between KiCad internal names (e.g. `F.SilkS`) and display names (e.g. `F.Silkscreen`).
- All widget references (attached directly as instance attributes, e.g. `self.render_button`).
- The `queue.Queue` used to communicate between the export worker thread and the UI.

### Threading model

Long-running exports run on a daemon thread. The thread posts events to `self.log_queue` (`queue.Queue`). A `wx.Timer` fires every 120 ms, draining the queue on the main thread via `_poll_log_queue`. Event tuples:

| Tuple | Meaning |
|-------|---------|
| `("line", str)` | Append text to the log `wx.TextCtrl`. |
| `("progress", float)` | Set the `wx.Gauge` value (0–100). |
| `("done", bool)` | Export finished; `True` = success, `False` = failure. |

### Tab construction

`TabsBuilder` is instantiated with the frame and called once per tab. It directly sets attributes on the frame object (e.g. `f.render_button = wx.Button(…)`). This is a known architectural weakness — see [spec 2](tab-panels.md).

### Windows PATH wrapping

On Windows, every `kicad-cli` command is wrapped as:

```
cmd.exe /c "<kicad-cmd.bat path>" && <original command>
```

The path to `kicad-cmd.bat` is currently hardcoded. See [spec 5](kicad-cmd-path.md).

---

## Planned specifications

| # | File | Kind | Status |
|---|------|------|--------|
| 1 | [ExportJob module](export-job.md) | refactor | proposed |
| 2 | [Tab-panel subclasses](tab-panels.md) | refactor | proposed |
| 3 | [RenderOptions dataclass](render-options.md) | refactor | proposed |
| 4 | [Remove dead code](remove-dead-code.md) | deletion | proposed |
| 5 | [User-settable KiCad command path](kicad-cmd-path.md) | feature | proposed |

Recommended implementation order: 4 → 1 → 3 → 5 → 2.
