# Spec 1 — ExportJob module

[← index](README.md)

## Problem

Export logic is duplicated across two code paths:

- `_start_command_run` + `_run_command_worker` handle render and schematic exports. They reset the UI, start a daemon thread, run a list of shell commands, stream output to `log_queue`, and parse `Rendering: N%` progress lines.
- `_export_layout` contains a second inline `worker()` closure that re-implements the same daemon-thread/subprocess/queue pattern (~60 lines) and additionally manages the per-layer loop and `pdfunite` call.

The two copies have already diverged: `_run_command_worker` parses `Rendering: N%` progress output; the layout worker does not. Both are embedded inside `KiCadExportFrame`, making the subprocess/threading logic untestable without a live `wx.App`.

## New module: `src/export_job.py`

```python
from __future__ import annotations
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable

# Events posted to the caller on the worker thread.
# The caller must enqueue or use wx.CallAfter — do not touch wx objects directly.
ExportEvent = tuple  # ("line", str) | ("progress", float) | ("done", bool)

@dataclass
class ExportStep:
    cmd: str                      # complete shell command string
    progress_weight: float = 1.0  # relative contribution to overall progress

@dataclass
class ExportJob:
    steps: list[ExportStep]
    on_event: Callable[[ExportEvent], None]
    cleanup: Callable[[], None] | None = None  # called unconditionally after "done"

    def start(self) -> None:
        """Spawn a daemon thread and return immediately."""
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        ...
```

### `_run` behaviour

1. Iterates over `self.steps` in order.
2. For each step, runs `step.cmd` via `subprocess.Popen(shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=CREATE_NO_WINDOW on Windows)`.
3. Streams each stdout line as `("line", line)`.
4. Matches lines against `re.compile(r"Rendering:\s*(\d+)\s*%")` and emits `("progress", overall)` where `overall` is computed from `step.progress_weight` relative to the sum of all weights.
5. On non-zero exit code: emits `("done", False)` and stops.
6. After all steps succeed: emits `("progress", 100.0)` then `("done", True)`.
7. Calls `self.cleanup()` unconditionally in a `finally` block (if not `None`).

## Changes to `KiCadExportFrame`

Delete `_start_command_run` and `_run_command_worker`. Delete the inline `worker()` closure in `_export_layout`.

Add `_prepare_export_ui(status_text: str)` — the shared UI-reset that was previously duplicated:

```python
def _prepare_export_ui(self, status_text: str) -> None:
    for log in (self.log_text_pcb, self.log_text_sch, self.log_text_layout):
        log.SetValue("")
    for label in (self.status_label_pcb, self.status_label_sch, self.status_label_layout):
        label.SetLabel(status_text)
    self.render_button.Enable(False)
    self.export_schematic_button.Enable(False)
    self.export_layout_button.Enable(False)
    self.progress_pcb.SetValue(0)
    self.progress_sch.SetValue(0)
    self.progress_layout.SetValue(0)
    self.render_in_progress = True
```

All three handlers follow the same pattern after this change:

```python
def _run_render(self, _event):
    if self.render_in_progress:
        return
    # ... validation, build full_cmds list ...
    job = ExportJob(
        steps=[ExportStep(cmd=cmd) for cmd in full_cmds],
        on_event=lambda ev: self.log_queue.put(ev),
    )
    self._prepare_export_ui("Rendering...")
    self.current_action_label = "Render"
    job.start()
```

### Layout export

The layout export uses `progress_weight=0.0` for the `pdfunite` step (it completes near-instantly) and passes the temp-dir removal as `cleanup`:

```python
steps = [ExportStep(cmd=c, progress_weight=1.0) for c in layer_cmds]
steps.append(ExportStep(cmd=pdfunite_cmd, progress_weight=0.0))

job = ExportJob(
    steps=steps,
    on_event=lambda ev: self.log_queue.put(ev),
    cleanup=lambda: _cleanup_temp(temp_dir),
)
```

`_poll_log_queue` is unchanged.

## Files affected

| File | Change |
|------|--------|
| `src/export_job.py` | new |
| `src/kicad_export_gui.py` | delete `_start_command_run`, `_run_command_worker`, layout `worker()`; add `_prepare_export_ui`; update three export handlers |

## Testing

`ExportJob` has no `wx` dependency. Tests pass stub commands (`python -c "print('ok')"`) and a collecting `on_event` list, asserting the emitted event sequence without a running `wx.App`.
