# Spec 3 — RenderOptions dataclass

[← index](README.md)

## Problem

`build_kicad_cli_command` in `src/render_command.py` accepts a plain `dict` with 15 keys. Every caller must know every key name, which are optional, and that the "not set" convention is an empty string `""`. A typo in a key is silently ignored and produces a wrong command. The interface is as wide as the implementation — the function hides nothing from its callers.

`build_cmd_exe_command` is a one-liner that does not justify being a named function.

## Changes to `src/render_command.py`

Add `RenderOptions` and update the function signatures:

```python
from __future__ import annotations
import subprocess
from dataclasses import dataclass

@dataclass
class RenderOptions:
    # Required
    board: str
    output: str
    width: int
    height: int
    side: str
    background: str
    quality: str

    # Optional — empty string means the flag is omitted
    preset: str = ""
    floor: bool = False
    perspective: bool = False
    zoom: str = ""
    pan: str = ""
    pivot: str = ""
    rotate: str = ""
    light_top: str = ""
    light_bottom: str = ""
    light_side: str = ""
    light_camera: str = ""
    light_side_elevation: str = ""


def build_kicad_cli_command(options: RenderOptions) -> str:
    """Return a shell-quoted kicad-cli pcb render command string."""
    args = [
        "kicad-cli", "pcb", "render",
        "--output", options.output,
        "--width", str(options.width),
        "--height", str(options.height),
        "--side", options.side,
        "--background", options.background,
        "--quality", options.quality,
    ]
    if options.preset:
        args += ["--preset", options.preset]
    if options.floor:
        args.append("--floor")
    if options.perspective:
        args.append("--perspective")
    for flag, value in [
        ("--zoom", options.zoom),
        ("--pan", options.pan),
        ("--pivot", options.pivot),
        ("--rotate", options.rotate),
        ("--light-top", options.light_top),
        ("--light-bottom", options.light_bottom),
        ("--light-side", options.light_side),
        ("--light-camera", options.light_camera),
        ("--light-side-elevation", options.light_side_elevation),
    ]:
        if value:
            args += [flag, value]
    args.append(options.board)
    return subprocess.list2cmdline(args)


def wrap_for_windows(kicad_cmd_path: str, cmd: str) -> str:
    """Prepend kicad-cmd.bat so kicad-cli is on PATH when cmd runs."""
    return f'cmd.exe /c ""{kicad_cmd_path}" && {cmd}"'
```

`build_cmd_exe_command` is removed and replaced by `wrap_for_windows`. There are no other callers.

## Changes to `KiCadExportFrame`

`_collect_render_options` returns `RenderOptions` instead of a `dict`:

```python
def _collect_render_options(self, board: str, width: int, height: int) -> RenderOptions:
    return RenderOptions(
        board=board,
        output="",          # caller sets this before passing to build_kicad_cli_command
        width=width,
        height=height,
        side=self.side_combo.GetValue(),
        background=self.background_combo.GetValue(),
        quality=self.quality_combo.GetValue(),
        preset=self.preset_combo.GetValue().strip(),
        floor=self.floor_check.GetValue(),
        perspective=self.perspective_check.GetValue(),
        zoom=self.zoom_input.GetValue().strip(),
        pan=self.pan_input.GetValue().strip(),
        pivot=self.pivot_input.GetValue().strip(),
        rotate=self.rotate_input.GetValue().strip(),
        light_top=self.light_top_input.GetValue().strip(),
        light_bottom=self.light_bottom_input.GetValue().strip(),
        light_side=self.light_side_input.GetValue().strip(),
        light_camera=self.light_camera_input.GetValue().strip(),
        light_side_elevation=self.light_side_elevation_input.GetValue().strip(),
    )
```

(If [spec 2](tab-panels.md) is implemented first, the `self.` references become `self.pcb_tab.`.)

`_wrap_kicad_cmd` calls `wrap_for_windows`:

```python
def _wrap_kicad_cmd(self, cmd: str) -> str:
    path = self._settings.kicad_cmd_path.strip()  # see spec 5
    if os.name == "nt" and path:
        return wrap_for_windows(path, cmd)
    return cmd
```

## Files affected

| File | Change |
|------|--------|
| `src/render_command.py` | add `RenderOptions`; rename `build_cmd_exe_command` → `wrap_for_windows`; update `build_kicad_cli_command` signature |
| `src/kicad_export_gui.py` | `_collect_render_options` returns `RenderOptions`; update `_wrap_kicad_cmd`; update call sites |

## Invariants

- `build_kicad_cli_command` must produce identical output to the current implementation for equivalent inputs.
- Empty string optional fields → flag omitted (preserves existing `if value:` convention).

## Open questions

- Should `output` be a parameter to `build_kicad_cli_command(options, output_path)` rather than a field, to prevent constructing a `RenderOptions` with `output=""` and forgetting to set it?
- Should optional string fields use `str | None` with `None` as the "not set" sentinel instead of `""`?
