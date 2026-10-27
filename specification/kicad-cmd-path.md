# Spec 5 — User-settable KiCad command path

[← index](README.md)

## Problem

On Windows, `kicad-cli` is not on the system PATH by default. The app wraps every export command via `kicad-cmd.bat`, which sets up the KiCad environment. The path to that batch file is hardcoded in `src/ui_constants.py`:

```python
KICAD_CMD_DEFAULT = r"C:\Program Files\KiCad\9.0\bin\kicad-cmd.bat"
```

Users with KiCad installed to a different drive or version directory must edit source code to fix this.

## Proposed behaviour

- The path is stored in a `settings.json` file in a platform-appropriate user config directory.
- A text field in the UI allows the user to view and change the path; saving writes to `settings.json`.
- The value is read at export time (not startup), so changes take effect immediately.
- If the field is empty, no wrapper is applied — `kicad-cli` is invoked directly.
- On non-Windows platforms the settings row is hidden (no wrapper is needed).

---

## New module: `src/settings.py`

```python
from __future__ import annotations
import json
import os
import sys
from dataclasses import asdict, dataclass


def _settings_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "kicad-export-gui", "settings.json")


@dataclass
class AppSettings:
    kicad_cmd_path: str = r"C:\Program Files\KiCad\9.0\bin\kicad-cmd.bat"


def load_settings() -> AppSettings:
    """Return settings from disk, or defaults if the file is absent or unreadable."""
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return AppSettings(**{k: v for k, v in data.items() if k in AppSettings.__dataclass_fields__})
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    """Write settings to disk, creating parent directories as needed."""
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(settings), fh, indent=2)
```

`KICAD_CMD_DEFAULT` is removed from `src/ui_constants.py`. The default lives in `AppSettings.kicad_cmd_path`.

---

## UI changes

A **KiCad command path** row is added to the "Project Paths" card in `_build_ui`, visible on Windows only (`if sys.platform == "win32"`):

```
┌─ Project Paths ──────────────────────────────────────────────────┐
│  Project file (.kicad_pro)                                       │
│  [___________________________________________] [Browse]          │
│                                                                  │
│  Output folder                                                   │
│  [___________________________________________] [Browse]          │
│                                                                  │
│  KiCad command path                              (Windows only)  │
│  [___________________________________________] [Save]            │
│  Path to kicad-cmd.bat used to set up the KiCad environment.    │
└──────────────────────────────────────────────────────────────────┘
```

New widgets (Windows only):

```python
self.kicad_cmd_input = wx.TextCtrl(paths_card)
self.kicad_cmd_input.SetValue(self._settings.kicad_cmd_path)

self.kicad_cmd_save = wx.Button(paths_card, label="Save")
self.kicad_cmd_save.Bind(wx.EVT_BUTTON, self._save_kicad_cmd_path)

hint = wx.StaticText(paths_card, label="Path to kicad-cmd.bat used to set up the KiCad environment.")
```

Handler:

```python
def _save_kicad_cmd_path(self, _event):
    self._settings.kicad_cmd_path = self.kicad_cmd_input.GetValue().strip()
    save_settings(self._settings)
```

---

## Changes to `KiCadExportFrame`

Load settings in `__init__`:

```python
from src.settings import load_settings, save_settings, AppSettings

class KiCadExportFrame(wx.Frame):
    def __init__(self):
        ...
        self._settings = load_settings()
        ...
```

Update `_wrap_kicad_cmd`:

```python
def _wrap_kicad_cmd(self, cmd: str) -> str:
    path = self._settings.kicad_cmd_path.strip()
    if os.name == "nt" and path:
        return wrap_for_windows(path, cmd)   # from render_command.py — see spec 3
    return cmd
```

---

## Files affected

| File | Change |
|------|--------|
| `src/settings.py` | new — `AppSettings`, `load_settings`, `save_settings` |
| `src/ui_constants.py` | remove `KICAD_CMD_DEFAULT` |
| `src/kicad_export_gui.py` | load settings in `__init__`; update `_wrap_kicad_cmd`; add path field and save handler |

## Invariants

- `load_settings` never raises; callers need no exception handling.
- `save_settings` creates parent directories unconditionally.
- Settings are never read or written from a worker thread.
- On non-Windows platforms the `kicad_cmd_path` field is still present in `AppSettings` and `settings.json` (harmless), but the UI row is hidden.

## Open questions

- Settings inline in the main window vs. a separate `wx.Dialog`? A dialog is cleaner if more settings are added later.
- Should the path be validated on save — show a `wx.MessageBox` warning if the file does not exist?
- Is `platformdirs` (a common Python package) worth adding as a dependency to resolve the config directory, or is the manual `sys.platform` check sufficient?
