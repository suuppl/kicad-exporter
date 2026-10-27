# Spec 2 — Tab-panel subclasses

[← index](README.md)

## Problem

`TabsBuilder` in `src/gui_tabs.py` receives the entire `KiCadExportFrame` as `frame`, then sets ~20 of its instance attributes by direct assignment (`f.render_button = wx.Button(…)`, `f.log_text_pcb = wx.TextCtrl(…)`, etc.). The class is a purely organisational split: callers must still know which frame attributes will exist after each `build_*` call. Moving the code back into `KiCadExportFrame._build_ui` changes nothing about the total complexity.

Consequences:
- Adding a widget to a tab requires editing both `gui_tabs.py` (construction) and `kicad_export_gui.py` (binding and usage).
- The tab panels cannot be constructed or inspected without a full `KiCadExportFrame` instance.

## Design

Replace `TabsBuilder` with three `wx.Panel` subclasses. Each class owns its own sizer tree and widget instances, exposes a minimal set of named attributes, and accepts `(parent, colors, fonts)` — no frame reference.

### Theme objects

Add `src/app_theme.py`:

```python
from dataclasses import dataclass
import wx

@dataclass
class AppColors:
    app_bg: wx.Colour
    card_bg: wx.Colour
    text_primary: wx.Colour
    text_secondary: wx.Colour
    text_muted: wx.Colour
    button_bg: wx.Colour
    progress_green: wx.Colour

@dataclass
class AppFonts:
    header: wx.Font
    label: wx.Font
    label_bold: wx.Font
    sub: wx.Font
    status: wx.Font
    button: wx.Font
    banner: wx.Font
    banner_sub: wx.Font
```

`KiCadExportFrame._init_colors` and `_init_fonts` are replaced by factory functions that return `AppColors` and `AppFonts` instances. The frame stores them as `self._colors` and `self._fonts` and passes them to each panel constructor.

---

### `PcbTab(wx.Panel)`

```python
class PcbTab(wx.Panel):
    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None: ...

    # Public widget attributes (read by KiCadExportFrame for binding and value access)
    render_button: wx.Button
    advanced_toggle: wx.CheckBox
    resolution_combo: wx.ComboBox
    width_input: wx.TextCtrl
    height_input: wx.TextCtrl
    side_combo: wx.ComboBox
    background_combo: wx.ComboBox
    quality_combo: wx.ComboBox
    preset_combo: wx.ComboBox
    floor_check: wx.CheckBox
    perspective_check: wx.CheckBox
    zoom_input: wx.TextCtrl
    pan_input: wx.TextCtrl
    pivot_input: wx.TextCtrl
    rotate_input: wx.TextCtrl
    light_top_input: wx.TextCtrl
    light_bottom_input: wx.TextCtrl
    light_side_input: wx.TextCtrl
    light_camera_input: wx.TextCtrl
    light_side_elevation_input: wx.TextCtrl
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def show_log(self, visible: bool) -> None: ...      # shows/hides log panel; calls Layout()
    def show_advanced(self, visible: bool) -> None: ... # shows/hides advanced container; calls Layout()
```

---

### `SchematicTab(wx.Panel)`

```python
class SchematicTab(wx.Panel):
    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None: ...

    export_button: wx.Button
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def show_log(self, visible: bool) -> None: ...
```

---

### `LayoutTab(wx.Panel)`

```python
class LayoutTab(wx.Panel):
    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None: ...

    export_button: wx.Button
    change_layers_button: wx.Button
    layers_value: wx.StaticText
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def show_log(self, visible: bool) -> None: ...
```

---

## Changes to `KiCadExportFrame`

Construction in `_build_ui`:

```python
self._colors = make_app_colors()   # replaces _init_colors
self._fonts  = make_app_fonts()    # replaces _init_fonts

self.pcb_tab       = PcbTab(notebook, self._colors, self._fonts)
self.schematic_tab = SchematicTab(notebook, self._colors, self._fonts)
self.layout_tab    = LayoutTab(notebook, self._colors, self._fonts)
notebook.AddPage(self.pcb_tab,       "PCB Images Export")
notebook.AddPage(self.schematic_tab, "Schematic Export")
notebook.AddPage(self.layout_tab,    "Layout Export")
```

Event binding uses the explicit public attributes:

```python
self.pcb_tab.render_button.Bind(wx.EVT_BUTTON, self._run_render)
self.pcb_tab.resolution_combo.Bind(wx.EVT_COMBOBOX, self._apply_resolution)
self.pcb_tab.advanced_toggle.Bind(wx.EVT_CHECKBOX, self._on_toggle_advanced)
# etc.
```

`_toggle_log_all` becomes:

```python
def _toggle_log_all(self, show: bool) -> None:
    for tab in (self.pcb_tab, self.schematic_tab, self.layout_tab):
        tab.show_log(show)
```

`_toggle_advanced` becomes:

```python
def _toggle_advanced(self, show: bool) -> None:
    self.pcb_tab.show_advanced(show)
```

The ~20 per-widget frame attributes (`self.render_button`, `self.log_text_pcb`, `self.progress_pcb`, etc.) are removed from `KiCadExportFrame`; they live inside the panel objects. References in event handlers change from `self.render_button` to `self.pcb_tab.render_button`, and so on.

## Files affected

| File | Change |
|------|--------|
| `src/gui_tabs.py` | replaced by three `wx.Panel` subclasses (same file or `src/tabs/` package) |
| `src/app_theme.py` | new — `AppColors`, `AppFonts`, `make_app_colors()`, `make_app_fonts()` |
| `src/kicad_export_gui.py` | `_build_ui` simplified; `_init_colors` / `_init_fonts` removed; event bindings and handler attribute references updated |

## Invariants

- Each panel must be constructable with `(parent, colors, fonts)` only — no frame reference.
- `show_log` and `show_advanced` call `self.Layout()` internally; callers do not need to trigger layout.
- All event handlers remain on `KiCadExportFrame`; the panels are pure view objects.

## Open questions

- One file with three classes or a `src/tabs/` package? A package adds navigation overhead for a small codebase; a single file is probably fine.
- Should `log_text` remain per-tab or become a single shared `wx.TextCtrl` outside the notebook? Keeping it per-tab preserves the current "Show log" behaviour and the tab-local log state.
