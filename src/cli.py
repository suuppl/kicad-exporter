"""Headless front-end for CI: run the same exports as the GUI from the command line.

    kicad-export hw/board.kicad_pro                       # bulk selection from the settings
    kicad-export hw/board.kicad_pro -t renders,schematic -o out/

Settings come from --settings, else <name>_export_settings.json next to the project
(GUI: Project settings → Export…), else defaults. Paths in the settings file that only
make sense on the machine that wrote it (kicad-cmd.bat, plugin dirs) are overridden by
the KICAD_PYTHON / KICAD_EXPORT_* environment variables, which the Docker image sets.
"""
from __future__ import annotations

import argparse
import os
import sys

from src.exports import STEP_NAMES, make_step_job_by_name
from src.settings import AppSettings, load_settings_from, project_settings_path

# CLI target name -> (export step, AppSettings bulk flag)
TARGETS: dict[str, tuple[str, str]] = {
    "renders":   ("PCB Images", "bulk_pcb"),
    "schematic": ("Schematic", "bulk_sch"),
    "layout":    ("Layout", "bulk_layout"),
    "step":      ("STEP", "bulk_step"),
    "fab":       ("Fabrication", "bulk_fab"),
    "combined":  ("Combined PDF", "bulk_combined"),
}


def _settings_for(project: str, settings_path: str | None) -> AppSettings:
    if settings_path:
        loaded = load_settings_from(settings_path)
        if loaded is None:
            sys.exit(f"error: settings file not found or invalid: {settings_path}")
        return loaded
    return load_settings_from(project_settings_path(project)) or AppSettings()


def _targets(arg: str | None, settings: AppSettings) -> list[str]:
    if not arg:
        return [t for t, (_, flag) in TARGETS.items() if getattr(settings, flag)]
    wanted = [t.strip() for t in arg.split(",") if t.strip()]
    if "all" in wanted:
        return list(TARGETS)
    unknown = [t for t in wanted if t not in TARGETS]
    if unknown:
        sys.exit(f"error: unknown target(s) {', '.join(unknown)}; choose from {', '.join(TARGETS)}, all")
    # Run in the fixed step order: the combined PDF needs the others' outputs.
    return [t for t in TARGETS if t in wanted]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kicad-export", description="Export a KiCad project (renders, PDFs, STEP, fab files).")
    p.add_argument("project", help=".kicad_pro file")
    p.add_argument("-o", "--output", help="output folder (default: <project dir>/export)")
    p.add_argument("-t", "--targets", help=f"comma-separated: {', '.join(TARGETS)}, all "
                   "(default: the Bulk Export selection in the settings)")
    p.add_argument("-s", "--settings", help="settings JSON (default: <project>_export_settings.json if present)")
    p.add_argument("--delete-renders", action="store_true",
                   help="remove the render PNGs once the combined PDF is written")
    p.add_argument("--no-fab-copy", action="store_true",
                   help="keep fabrication files only in production/ next to the board, "
                   "don't copy them to <output>/production")
    p.add_argument("--keep-going", action="store_true", help="run the remaining targets after a failure")
    return p


def main(argv: list[str] | None = None) -> int:
    # Tool output contains non-ASCII (µ, Ω, …); don't die on a legacy console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = _parser().parse_args(argv)
    project = os.path.abspath(args.project)
    if not os.path.isfile(project):
        sys.exit(f"error: project file not found: {project}")
    settings = _settings_for(project, args.settings)
    targets = _targets(args.targets, settings)
    if not targets:
        sys.exit("error: no targets selected")
    output_dir = os.path.abspath(args.output or os.path.join(os.path.dirname(project), "export"))
    os.makedirs(output_dir, exist_ok=True)

    print(f"{os.path.basename(project)}: {', '.join(targets)} -> {output_dir}", flush=True)
    failed: list[str] = []
    for target in targets:
        step_name = TARGETS[target][0]
        assert step_name in STEP_NAMES
        print(f"\n=== {step_name} ===", flush=True)
        result: dict[str, bool] = {}

        def on_event(event: tuple) -> None:
            kind, payload = event
            if kind == "line":
                print(payload, flush=True)
            elif kind == "done":
                result["ok"] = bool(payload)

        job = make_step_job_by_name(
            step_name, settings, project, output_dir, on_event,
            delete_renders=args.delete_renders, copy_fab_to_output=not args.no_fab_copy,
        )
        try:
            job.run()
        except KeyboardInterrupt:
            job.cancel()
            return 130
        if not result.get("ok"):
            print(f"!!! {step_name} failed", file=sys.stderr, flush=True)
            failed.append(target)
            if not args.keep_going:
                break

    if failed:
        print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nAll targets completed.")
    return 0
