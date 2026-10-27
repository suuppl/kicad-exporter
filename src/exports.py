"""Export job factories, shared by the GUI and the headless CLI. Nothing here imports wx.

Each make_*_job() builds an ExportJob from AppSettings; events go to `on_event`.

Tool locations, in order of precedence:
  kicad-cli      PATH, or next to `kicad_cmd_path` (kicad-cmd.bat) on Windows
  KiCad Python   $KICAD_PYTHON, python.exe next to kicad-cmd.bat on Windows, else python3
  board2pdf      $KICAD_EXPORT_BOARD2PDF, else settings.board2pdf_path
  Fab. Toolkit   $KICAD_EXPORT_FAB_PLUGINS_DIR, else settings.fab_plugins_dir, else auto-detect (Windows)
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import sys
import zipfile
from typing import Callable

from src.combined_pdf import CombinedPdfContent, build_combined_pdf
from src.export_job import ExportEvent, ExportJob, ExportStep
from src.pcb_file import make_bare_board_copy, read_title_block
from src.render_command import RenderOptions, build_kicad_cli_args, wrap_for_windows
from src.settings import AppSettings
from src.ui_constants import CORNER_ROTATE, SIDE_KEYS, SIDE_LABELS

OnEvent = Callable[[ExportEvent], None]

FAB_PKG = "com_github_bennymeg_JLC-Plugin-for-KiCad"

# Export steps, in run order (also the Bulk Export step names).
STEP_NAMES = ["PCB Images", "Schematic", "Layout", "STEP", "Fabrication", "Combined PDF"]


def side_file_tag(side_key: str) -> str:
    """File name tag for a render side; the corner pseudo-side is saved as 'corner'."""
    return "corner" if side_key == "top-left-front" else side_key


# ----------------------------------------------------------------------
# Tool resolution
# ----------------------------------------------------------------------

def kicad_python(s: AppSettings) -> str:
    """Python interpreter that can import pcbnew (needed by the plugins)."""
    env = os.environ.get("KICAD_PYTHON")
    if env:
        return env
    bat = s.kicad_cmd_path.strip()
    if sys.platform == "win32" and bat:
        candidate = os.path.join(os.path.dirname(bat), "python.exe")
        if os.path.isfile(candidate):
            return candidate
    return "python" if sys.platform == "win32" else "python3"


def board2pdf_path(s: AppSettings) -> str:
    return os.environ.get("KICAD_EXPORT_BOARD2PDF") or s.board2pdf_path.strip()


def detect_fab_plugin_dir(s: AppSettings) -> str | None:
    """Return the 3rdparty/plugins dir that contains the Fabrication Toolkit, or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        docs_raw, _ = winreg.QueryValueEx(key, "Personal")
        docs = os.path.expandvars(docs_raw)
    except Exception:
        return None

    m = re.search(r"KiCad[/\\](\d+\.\d+)[/\\]", s.kicad_cmd_path, re.IGNORECASE)
    version = m.group(1) if m else "9.0"

    plugins_dir = os.path.join(docs, "KiCad", version, "3rdparty", "plugins")
    marker = os.path.join(plugins_dir, FAB_PKG, "cli.py")
    return plugins_dir if os.path.isfile(marker) else None


def fab_plugins_dir(s: AppSettings) -> str:
    return (
        os.environ.get("KICAD_EXPORT_FAB_PLUGINS_DIR")
        or s.fab_plugins_dir.strip()
        or detect_fab_plugin_dir(s)
        or ""
    )


def _kicad_step(s: AppSettings, cli_args: list[str], progress_weight: float = 1.0) -> ExportStep:
    """
    Create an ExportStep for a kicad-cli command.

    On Windows, prefers shell=False with kicad-cli.exe found next to kicad-cmd.bat
    so that negative argument values (e.g. --rotate -60,0,30) reach kicad-cli's
    argv intact — no shell tokenisation can corrupt them.
    Falls back to shell=True + kicad-cmd.bat wrapper when kicad-cli.exe is not found.
    Elsewhere kicad-cli must be on PATH and runs without a shell.
    """
    bat = s.kicad_cmd_path.strip()
    if sys.platform != "win32":
        return ExportStep(args=cli_args, progress_weight=progress_weight)
    if bat:
        kicad_bin = os.path.dirname(bat)
        cli_exe = os.path.join(kicad_bin, "kicad-cli.exe")
        if os.path.isfile(cli_exe):
            env = os.environ.copy()
            env["PATH"] = kicad_bin + os.pathsep + env.get("PATH", "")
            return ExportStep(
                args=[cli_exe] + cli_args[1:],
                env=env,
                progress_weight=progress_weight,
            )
    # Fallback: shell=True, wrap with kicad-cmd.bat so kicad-cli is on PATH.
    # cmd.exe treats '=' as an argument separator, so --flag=value tokens must
    # be quoted explicitly; list2cmdline only quotes on spaces.
    parts = []
    for arg in cli_args:
        if arg.startswith("--") and "=" in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(subprocess.list2cmdline([arg]))
    cmd = " ".join(parts)
    if bat:
        cmd = wrap_for_windows(bat, cmd)
    return ExportStep(cmd=cmd, progress_weight=progress_weight)


def _failed_job(message: str, on_event: OnEvent) -> ExportJob:
    """A job that logs `message` and fails without running anything."""
    def fail() -> None:
        raise RuntimeError(message)
    return ExportJob(steps=[], on_event=on_event, on_success=fail)


# ----------------------------------------------------------------------
# PCB renders
# ----------------------------------------------------------------------

def make_pcb_job(s: AppSettings, project: str, output_dir: str, on_event: OnEvent) -> ExportJob:
    sides = [side for side in s.selected_sides if side in SIDE_KEYS]
    if not sides:
        return _failed_job("No render side selected.", on_event)

    base = os.path.splitext(project)[0]
    pcb = base + ".kicad_pcb"
    name = os.path.basename(base)

    # (board file, output-name suffix) per render pass. The bare pass renders a
    # temp copy of the board with all (model ...) blocks stripped.
    passes: list[tuple[str, str]] = [(pcb, "")]
    bare_dir: str | None = None
    if s.render_bare:
        try:
            bare_dir, bare_pcb = make_bare_board_copy(project)
        except OSError as exc:
            return _failed_job(f"Could not prepare board without components: {exc}", on_event)
        passes.append((bare_pcb, "_bare"))

    steps: list[ExportStep] = []
    for (board, suffix), side_key in ((p, k) for p in passes for k in sides):
        is_corner = side_key == "top-left-front"
        actual_side = "top" if is_corner else side_key
        out_name = f"{name}_{side_file_tag(side_key)}{suffix}.png"

        opts = RenderOptions(
            board=board,
            output=os.path.join(output_dir, out_name),
            width=s.width,
            height=s.height,
            side=actual_side,
            background=s.background,
            quality=s.quality,
            # Advanced settings apply to corner only.
            floor=s.floor if is_corner else False,
            perspective=is_corner,
            zoom=s.zoom.strip() if is_corner else "",
            pan=s.pan.strip() if is_corner else "",
            pivot=s.pivot.strip() if is_corner else "",
            rotate=(s.rotate.strip() or CORNER_ROTATE) if is_corner else "",
            light_top=s.light_top.strip() if is_corner else "",
            light_bottom=s.light_bottom.strip() if is_corner else "",
            light_side=s.light_side.strip() if is_corner else "",
            light_camera=s.light_camera.strip() if is_corner else "",
            light_side_elevation=s.light_side_elevation.strip() if is_corner else "",
        )
        step = _kicad_step(s, build_kicad_cli_args(opts))
        step.output_paths = [opts.output]
        steps.append(step)

    return ExportJob(
        steps=steps,
        on_event=on_event,
        cleanup=(lambda: shutil.rmtree(bare_dir, ignore_errors=True)) if bare_dir else None,
    )


# ----------------------------------------------------------------------
# Combined PDF
# ----------------------------------------------------------------------

def make_combined_job(
    s: AppSettings, project: str, output_dir: str, on_event: OnEvent, delete_renders: bool = False
) -> ExportJob:
    """Merge whatever renders/PDFs exist in output_dir into one PDF.

    Inputs are collected when the job runs (on the worker thread), so it sees the
    files written by earlier steps of the same bulk export.
    """
    log = lambda line: on_event(("line", line))  # noqa: E731
    name = os.path.splitext(os.path.basename(project))[0]
    out_pdf = os.path.join(output_dir, f"{name}_combined.pdf")

    def run() -> None:
        content = collect_combined_content(project, output_dir, log)
        write_combined_pdf(content, out_pdf, delete_renders, log)

    return ExportJob(steps=[], on_event=on_event, on_success=run)


def collect_combined_content(project: str, output_dir: str, log: Callable[[str], None]) -> CombinedPdfContent:
    name = os.path.splitext(os.path.basename(project))[0]

    def out(fname: str) -> str:
        return os.path.join(output_dir, fname)

    image_groups: list[tuple[str, list[tuple[str, str]]]] = []
    for suffix, heading in (("", "3D renders"), ("_bare", "3D renders without components")):
        items = [
            (SIDE_LABELS[key], out(f"{name}_{side_file_tag(key)}{suffix}.png"))
            for key in SIDE_KEYS
        ]
        items = [(caption, path) for caption, path in items if os.path.isfile(path)]
        if items:
            image_groups.append((heading, items))

    cover = next(
        (p for p in (out(f"{name}_corner.png"), out(f"{name}_corner_bare.png")) if os.path.isfile(p)),
        None,
    )

    pdfs: list[tuple[str, str]] = []
    for label, fname in (
        ("Schematics", f"{name}_schematics.pdf"),
        ("Layout", f"{name}_assembly.pdf"),
        ("Layout", f"{name}_board_layers.pdf"),
    ):
        if os.path.isfile(out(fname)):
            pdfs.append((label, out(fname)))

    tb = read_title_block(project)
    subtitle = []
    if tb.get("rev"):
        subtitle.append(f"Rev. {tb['rev']}")
    if tb.get("date"):
        subtitle.append(tb["date"])
    if tb.get("company"):
        subtitle.append(tb["company"])

    if cover is None:
        log("Note: no corner render found — title page will have no image.")
    if not pdfs:
        log("Note: no schematic or layout PDF found in the output folder.")
    return CombinedPdfContent(
        title=tb.get("title") or name,
        subtitle_lines=subtitle,
        cover_image=cover,
        image_groups=image_groups,
        pdfs=pdfs,
    )


def write_combined_pdf(
    content: CombinedPdfContent, out_pdf: str, delete_renders: bool, log: Callable[[str], None]
) -> None:
    """Renders are only removed once the PDF has been written successfully."""
    build_combined_pdf(content, out_pdf, log)
    if not delete_renders:
        return
    renders = {path for _heading, items in content.image_groups for _caption, path in items}
    if content.cover_image:
        renders.add(content.cover_image)
    for path in sorted(renders):
        try:
            os.remove(path)
            log(f"Deleted {os.path.basename(path)}")
        except OSError as exc:
            log(f"Could not delete {os.path.basename(path)}: {exc}")


# ----------------------------------------------------------------------
# Schematic
# ----------------------------------------------------------------------

def make_sch_job(s: AppSettings, project: str, output_dir: str, on_event: OnEvent) -> ExportJob:
    base = os.path.splitext(project)[0]
    sch = base + ".kicad_sch"
    name = os.path.basename(base)
    out_pdf = os.path.join(output_dir, f"{name}_schematics.pdf")

    args = ["kicad-cli", "sch", "export", "pdf", "--output", out_pdf]
    if not s.sch_plot_drawing_sheet:
        args.append("--exclude-drawing-sheet")
    if s.sch_black_and_white:
        args.append("--black-and-white")
    if s.sch_color_theme.strip():
        args += ["--theme", s.sch_color_theme.strip()]
    if not s.sch_plot_background:
        args.append("--no-background-color")
    if not s.sch_pdf_property_popups:
        args.append("--exclude-pdf-property-popups")
    if not s.sch_pdf_hierarchical_links:
        args.append("--exclude-pdf-hierarchical-links")
    if not s.sch_pdf_metadata:
        args.append("--exclude-pdf-metadata")
    args.append(sch)

    step = _kicad_step(s, args, progress_weight=0.0)
    step.output_paths = [out_pdf]
    return ExportJob(steps=[step], on_event=on_event)


# ----------------------------------------------------------------------
# Layout (board2pdf)
# ----------------------------------------------------------------------

def make_layout_job(s: AppSettings, project: str, output_dir: str, on_event: OnEvent) -> ExportJob:
    base = os.path.splitext(project)[0]
    pcb = base + ".kicad_pcb"
    project_dir = os.path.dirname(project)
    name = os.path.basename(base)
    ini_path = os.path.join(project_dir, "board2pdf.config.ini")
    out_pdf = os.path.abspath(os.path.join(output_dir, f"{name}_assembly.pdf"))

    b2p_path = board2pdf_path(s)
    if not b2p_path:
        return _failed_job("board2pdf path is not configured. Set it in Project Paths.", on_event)
    # --output (absolute) puts the merged PDF in the output folder regardless of the
    # ini's output_dest_dir.
    cli_args = [pcb, "--output", out_pdf]
    if os.path.isfile(ini_path):
        cli_args += ["--ini", ini_path]
        cli_args += ["--merge", "pymupdf"]
        cli_args += ["--colorize", "pymupdf"]
    else:
        on_event(("line", f"Warning: board2pdf.config.ini not found in {project_dir} — running with board2pdf defaults."))

    step = ExportStep(
        args=[kicad_python(s), b2p_path, *cli_args],
        cwd=project_dir,
        progress_weight=1.0,
        output_paths=[out_pdf],
    )
    return ExportJob(steps=[step], on_event=on_event)


# ----------------------------------------------------------------------
# STEP
# ----------------------------------------------------------------------

def make_step_job(s: AppSettings, project: str, output_dir: str, on_event: OnEvent) -> ExportJob:
    base = os.path.splitext(project)[0]
    pcb = base + ".kicad_pcb"
    name = os.path.basename(base)

    fmt = s.step_format
    ext = {"GLB": "glb", "XAO": "xao"}.get(fmt, "step")
    out_file = os.path.join(output_dir, f"{name}.{ext}")

    args = ["kicad-cli", "pcb", "export", "step", "--output", out_file]

    if s.step_origin == "drill":
        args.append("--drill-origin")
    elif s.step_origin == "grid":
        args.append("--grid-origin")
    elif s.step_origin == "user" and s.step_user_origin.strip():
        args += ["--user-origin", s.step_user_origin.strip()]

    for enabled, flag in (
        (not s.step_export_board_body, "--no-board-body"),
        (not s.step_export_components, "--no-components"),
        (s.step_no_unspecified, "--no-unspecified"),
        (s.step_no_dnp, "--no-dnp"),
        (s.step_subst_models, "--subst-models"),
        (s.step_force, "--force"),
        (s.step_include_inner_copper, "--include-inner-copper"),
        (s.step_include_silkscreen, "--include-silkscreen"),
        (s.step_include_soldermask, "--include-soldermask"),
        (s.step_cut_vias, "--cut-vias-in-body"),
        (s.step_include_tracks, "--include-tracks"),
        (s.step_include_pads, "--include-pads"),
        (s.step_include_zones, "--include-zones"),
        (s.step_fuse_shapes, "--fuse-shapes"),
        (s.step_fill_all_vias, "--fill-all-vias"),
    ):
        if enabled:
            args.append(flag)
    if s.step_net_filter.strip():
        args += ["--net-filter", s.step_net_filter.strip()]
    if s.step_component_filter.strip():
        args += ["--component-filter", s.step_component_filter.strip()]
    if not s.step_no_prcurves:
        args.append("--no-optimize-step")

    if s.step_tolerance != "0.01":
        args += ["--min-distance", s.step_tolerance + "mm"]

    if fmt != "STEP":
        args += ["--format", fmt]

    args.append(pcb)

    step = _kicad_step(s, args, progress_weight=0.0)
    step.output_paths = [out_file]
    return ExportJob(steps=[step], on_event=on_event)


# ----------------------------------------------------------------------
# Fabrication (Fabrication Toolkit plugin CLI)
# ----------------------------------------------------------------------

def make_fab_job(
    s: AppSettings, project: str, output_dir: str, on_event: OnEvent, copy_to_output: bool = False
) -> ExportJob:
    """The plugin writes to production/ next to the board; `copy_to_output` also copies
    the result to <output_dir>/production (used by the CLI so CI artifacts live in one place)."""
    base = os.path.splitext(project)[0]
    pcb = os.path.abspath(base + ".kicad_pcb")
    log = lambda line: on_event(("line", line))  # noqa: E731

    plugins_dir = fab_plugins_dir(s)
    if not os.path.isfile(os.path.join(plugins_dir, FAB_PKG, "cli.py")):
        return _failed_job(f"Fabrication Toolkit not found in plugins dir {plugins_dir!r}.", on_event)

    argv: list[str] = ["Fabrication Toolkit", "--path", pcb, "--nonInteractive"]
    for enabled, flag in (
        (s.fab_exclude_dnp, "--excludeDNP"),
        (s.fab_auto_translate, "--autoTranslate"),
        (s.fab_auto_fill, "--autoFill"),
        (s.fab_all_active_layers, "--allActiveLayers"),
        (s.fab_user1_vcut, "--user1VCut"),
        (s.fab_user2_alt_edge_cut, "--user2AltVCut"),
        (not s.fab_generate_backup, "--noBackup"),
    ):
        if enabled:
            argv.append(flag)
    # NOTE: --archiveName is deliberately NOT passed. The plugin's CLI mode
    # crashes when it expands text variables for a custom archive name
    # (thread.py reads pcbnew.GetBoard(), which is None headless). Instead we
    # let the plugin use its default project-based name and rename the
    # outputs ourselves in rename_fab_outputs once the job succeeds.
    archive = s.fab_archive_name.strip()
    if s.fab_extra_layers.strip():
        argv += ["--additionalLayers", s.fab_extra_layers.strip()]

    python_code = (
        f"import sys, runpy; "
        f"sys.path.insert(0, {plugins_dir!r}); "
        f"sys.argv = {argv!r}; "
        f"runpy.run_module('{FAB_PKG}.cli', run_name='__main__')"
    )

    step = ExportStep(args=[kicad_python(s), "-c", python_code], progress_weight=1.0)

    prod_dir = os.path.join(os.path.dirname(pcb), "production")

    def finish() -> None:
        rename_fab_outputs(prod_dir, archive, log)
        if copy_to_output:
            copy_fab_outputs(prod_dir, os.path.join(output_dir, "production"), log)

    # The plugin merges its output into production/ and never deletes, so a
    # previous run's files (especially under a different archive name) would
    # linger. Clear them when the job starts — archived into backups/ when
    # backups are on.
    return ExportJob(
        steps=[step],
        on_event=on_event,
        on_start=lambda: reset_fab_production_dir(prod_dir, s.fab_generate_backup, log),
        on_success=finish,
    )


def reset_fab_production_dir(prod_dir: str, keep_backup: bool, log: Callable[[str], None]) -> None:
    """Clear a previous run's files from production/ before a new export.

    The Fabrication Toolkit copies its output into production/ with
    dirs_exist_ok=True and never removes anything, so a renamed archive or a
    changed archive name leaves orphaned files behind. Everything except
    backups/ is removed; when backups are enabled it is zipped into backups/
    first. Failures are logged and non-fatal (at worst a stale file survives).
    """
    if not os.path.isdir(prod_dir):
        return
    backups_dir = os.path.join(prod_dir, "backups")
    stale = [
        os.path.join(prod_dir, name)
        for name in os.listdir(prod_dir)
        if os.path.join(prod_dir, name) != backups_dir
    ]
    if not stale:
        return

    if keep_backup:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        zip_path = os.path.join(backups_dir, f"previous {ts}.zip")
        try:
            os.makedirs(backups_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in stale:
                    if os.path.isfile(path):
                        zf.write(path, os.path.basename(path))
                    elif os.path.isdir(path):
                        for root, _dirs, files in os.walk(path):
                            for fname in files:
                                fpath = os.path.join(root, fname)
                                zf.write(fpath, os.path.relpath(fpath, prod_dir))
        except OSError as exc:
            log(f"Could not archive previous fabrication output ({exc}); leaving it in place.")
            return
        log(f"Archived previous fabrication output -> backups/{os.path.basename(zip_path)}")

    removed = False
    for path in stale:
        try:
            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)
            removed = True
        except OSError as exc:
            log(f"Could not remove {os.path.basename(path)}: {exc}")
    if removed and not keep_backup:
        log("Cleared previous fabrication output from production/")


def rename_fab_outputs(prod_dir: str, archive_name: str, log: Callable[[str], None]) -> None:
    """Give the Fabrication Toolkit outputs a consistent base name.

    With a custom archive name the gerber zip and the designators/positions/bom
    CSVs are all renamed to '<name>...'. With a blank name the plugin already
    names the zip from the board title block; the three CSVs are aligned to that
    same stem. Naming mirrors the plugin (ProcessManager.normalize_filename):
    whitespace collapses to '_', characters outside [\\w\\s.-] are stripped.
    """
    if not os.path.isdir(prod_dir):
        raise FileNotFoundError(f"production folder not found: {prod_dir}")

    # The plugin writes exactly one top-level *.zip per run (backups live in
    # production/backups/). Pick the newest to be safe.
    zips = [
        os.path.join(prod_dir, n)
        for n in os.listdir(prod_dir)
        if n.lower().endswith(".zip") and os.path.isfile(os.path.join(prod_dir, n))
    ]
    if not zips:
        raise FileNotFoundError(f"no gerber archive (*.zip) in {prod_dir}")
    newest_zip = max(zips, key=os.path.getmtime)

    if archive_name:
        base = re.sub(r"[^\w\s.\-]", "", "_".join(archive_name.split()))
        if not base:
            raise ValueError(f"archive name {archive_name!r} is empty after normalization")
        renames = [(newest_zip, base + ".zip")]
    else:
        base = os.path.splitext(os.path.basename(newest_zip))[0]
        renames = []

    renames += [
        (os.path.join(prod_dir, "designators.csv"), base + "_designators.csv"),
        (os.path.join(prod_dir, "positions.csv"), base + "_positions.csv"),
        (os.path.join(prod_dir, "bom.csv"), base + "_bom.csv"),
    ]
    for src, dst_name in renames:
        dst = os.path.join(prod_dir, dst_name)
        if not os.path.isfile(src):
            continue
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        os.replace(src, dst)
        log(f"Renamed {os.path.basename(src)} -> {dst_name}")


def copy_fab_outputs(prod_dir: str, dest_dir: str, log: Callable[[str], None]) -> None:
    """Copy production/ (without backups/) into the output folder."""
    if os.path.abspath(prod_dir) == os.path.abspath(dest_dir):
        return
    shutil.rmtree(dest_dir, ignore_errors=True)
    shutil.copytree(prod_dir, dest_dir, ignore=shutil.ignore_patterns("backups"))
    log(f"Copied fabrication files to {dest_dir}")


# ----------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------

def make_step_job_by_name(
    name: str,
    s: AppSettings,
    project: str,
    output_dir: str,
    on_event: OnEvent,
    delete_renders: bool = False,
    copy_fab_to_output: bool = False,
) -> ExportJob:
    """The job for one of STEP_NAMES."""
    if name == "PCB Images":
        return make_pcb_job(s, project, output_dir, on_event)
    if name == "Schematic":
        return make_sch_job(s, project, output_dir, on_event)
    if name == "Layout":
        return make_layout_job(s, project, output_dir, on_event)
    if name == "STEP":
        return make_step_job(s, project, output_dir, on_event)
    if name == "Fabrication":
        return make_fab_job(s, project, output_dir, on_event, copy_fab_to_output)
    if name == "Combined PDF":
        return make_combined_job(s, project, output_dir, on_event, delete_renders)
    raise ValueError(f"unknown export step {name!r}")
