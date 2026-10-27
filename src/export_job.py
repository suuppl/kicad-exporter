from __future__ import annotations

import os
import re
import subprocess
import sys
import threading

if sys.platform != "win32":
    import signal
from dataclasses import dataclass, field
from typing import Callable

ExportEvent = tuple  # ("line", str) | ("progress", float) | ("done", bool) | ("cancelled", None)

# kicad-cli render ("Rendering: 42 %") and board2pdf (" 42%: Plotting ...") progress.
_PROGRESS_RE = re.compile(r"Rendering:\s*(\d+)\s*%|^\s*(\d+)%:")
_CREATE_NO_WINDOW = 0x08000000
# kicad-cli is wx-based and emits its own wxWidgets startup noise on stdout/stderr;
# it's not relevant to the export outcome, so keep it out of the log.
_NOISE_RE = re.compile(r"^Adding duplicate image handler for ")


@dataclass
class ExportStep:
    # Provide either cmd (shell=True) or args (shell=False); args takes priority.
    cmd: str = ""
    args: list[str] | None = None
    env: dict | None = None
    progress_weight: float = 1.0
    cwd: str | None = None
    # Files this step writes. If the step is cancelled mid-run, these are
    # removed since they may contain a partial/corrupt write.
    output_paths: list[str] = field(default_factory=list)


@dataclass
class ExportJob:
    steps: list[ExportStep]
    on_event: Callable[[ExportEvent], None]
    cleanup: Callable[[], None] | None = None
    # Called on the worker thread before the first step. If it raises, ("done", False).
    on_start: Callable[[], None] | None = None
    # Called on the worker thread after all steps succeed, before ("done", True).
    # If it raises, ("done", False) is emitted instead.
    on_success: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        self._cancel_event = threading.Event()
        self._proc_lock = threading.Lock()
        self._current_proc: subprocess.Popen | None = None

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def run(self) -> None:
        """Run synchronously on the calling thread (headless CLI)."""
        self._run()

    def cancel(self) -> None:
        """Request cancellation. Safe to call from another thread (e.g. the UI thread)."""
        self._cancel_event.set()
        with self._proc_lock:
            proc = self._current_proc
        if proc is not None and proc.poll() is None:
            self._kill_process_tree(proc)

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen) -> None:
        # Steps may run shell=True (cmd.exe /c "... && kicad-cli ..." on Windows,
        # or /bin/sh -c "..." elsewhere), so proc.terminate() would only kill the
        # shell wrapper and leave the real export process running and still
        # writing output. Kill the whole process group/tree instead.
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except OSError:
                proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                proc.terminate()

    @staticmethod
    def _cleanup_outputs(step: ExportStep) -> None:
        for path in step.output_paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    def _run(self) -> None:
        total_weight = sum(s.progress_weight for s in self.steps)
        completed_weight = 0.0

        try:
            if self.on_start is not None:
                try:
                    self.on_start()
                except Exception as exc:
                    self.on_event(("line", f"Preparation failed: {exc}"))
                    self.on_event(("done", False))
                    return

            for step in self.steps:
                if self._cancel_event.is_set():
                    self.on_event(("cancelled", None))
                    return

                kwargs: dict = dict(
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if sys.platform == "win32":
                    kwargs["creationflags"] = _CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs["start_new_session"] = True
                if step.cwd is not None:
                    kwargs["cwd"] = step.cwd
                if step.env is not None:
                    kwargs["env"] = step.env

                if step.args is not None:
                    self.on_event(("line", f"[cmd] {subprocess.list2cmdline(step.args)}"))
                    proc = subprocess.Popen(step.args, **kwargs)
                else:
                    self.on_event(("line", f"[cmd] {step.cmd}"))
                    proc = subprocess.Popen(step.cmd, shell=True, **kwargs)
                with self._proc_lock:
                    self._current_proc = proc
                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    if self._cancel_event.is_set():
                        self._kill_process_tree(proc)
                        break
                    line = raw_line.rstrip("\n")
                    if _NOISE_RE.match(line):
                        continue
                    self.on_event(("line", line))
                    if total_weight > 0:
                        m = _PROGRESS_RE.search(line)
                        if m:
                            fraction = float(m.group(1) or m.group(2)) / 100.0
                            overall = (completed_weight + step.progress_weight * fraction) / total_weight * 100.0
                            self.on_event(("progress", overall))

                proc.wait()
                with self._proc_lock:
                    self._current_proc = None

                if self._cancel_event.is_set():
                    self._cleanup_outputs(step)
                    self.on_event(("cancelled", None))
                    return

                if proc.returncode != 0:
                    self._cleanup_outputs(step)
                    self.on_event(("done", False))
                    return

                completed_weight += step.progress_weight

            if self.on_success is not None:
                try:
                    self.on_success()
                except Exception as exc:
                    self.on_event(("line", f"Post-processing failed: {exc}"))
                    self.on_event(("done", False))
                    return

            if total_weight > 0:
                self.on_event(("progress", 100.0))
            self.on_event(("done", True))
        finally:
            # Unwinding from an exception (e.g. KeyboardInterrupt) mid-step: don't
            # leave the export process running.
            with self._proc_lock:
                proc = self._current_proc
            if proc is not None and proc.poll() is None:
                self._kill_process_tree(proc)
            if self.cleanup is not None:
                self.cleanup()
