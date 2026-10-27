from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field


def _global_settings_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "kicad-export-gui", "settings.json")


def project_settings_path(project_path: str) -> str:
    """Return the per-project settings file path next to the .kicad_pro file."""
    base = os.path.splitext(project_path)[0]
    return base + "_export_settings.json"


@dataclass
class AppSettings:
    # Paths
    kicad_cmd_path: str = r"C:\Program Files\KiCad\9.0\bin\kicad-cmd.bat"
    project_path: str = ""
    output_path: str = ""

    # PCB render
    resolution_preset: str = "1080p"
    width: int = 1920
    height: int = 1080
    selected_sides: list[str] = field(default_factory=lambda: ["top"])
    background: str = "default"
    quality: str = "basic"
    floor: bool = False
    perspective: bool = False
    zoom: str = "1"
    pan: str = "1,1,0"
    pivot: str = "0,0,0"
    rotate: str = "-50,0,27"
    light_top: str = ""
    light_bottom: str = ""
    light_side: str = ""
    light_camera: str = ""
    light_side_elevation: str = ""
    show_advanced: bool = False
    render_bare: bool = False   # also render each side without component 3D models

    # Layer selection (informational; shown in layout tab)
    selected_layer_names: list[str] = field(default_factory=list)

    # Bulk export
    bulk_pcb: bool = True
    bulk_sch: bool = True
    bulk_layout: bool = True
    bulk_combined: bool = True
    bulk_delete_renders: bool = False   # remove render PNGs once the combined PDF is written

    # board2pdf — e.g. "python 3rdparty/plugins/com_gitlab_dennevi_Board2Pdf/board2pdf-cli.py"
    board2pdf_path: str = ""

    # Schematic export (PDF)
    sch_plot_drawing_sheet: bool = True
    sch_black_and_white: bool = False
    sch_color_theme: str = ""
    sch_plot_background: bool = False
    sch_pdf_property_popups: bool = True
    sch_pdf_hierarchical_links: bool = True
    sch_pdf_metadata: bool = True

    # STEP export
    step_origin: str = "board-center"   # board-center | drill | grid | user
    step_user_origin: str = ""
    step_format: str = "STEP"           # STEP | GLB | XAO
    step_tolerance: str = "0.01"        # board outline chaining tolerance (mm)
    # Board options
    step_export_board_body: bool = True
    step_export_components: bool = True
    step_cut_vias: bool = False
    step_include_silkscreen: bool = False
    step_include_soldermask: bool = False
    step_include_inner_copper: bool = False
    # Conductor options
    step_include_tracks: bool = False
    step_include_pads: bool = False
    step_include_zones: bool = False
    step_fuse_shapes: bool = False
    step_fill_all_vias: bool = False
    step_net_filter: str = ""
    step_component_filter: str = ""
    # Other options
    step_no_dnp: bool = True
    step_no_unspecified: bool = False
    step_subst_models: bool = True
    step_force: bool = True
    step_no_prcurves: bool = True   # True = don't write P-curves (default); False = --no-optimize-step
    bulk_step: bool = True

    # Fabrication export (Fabrication Toolkit plugin CLI)
    fab_plugins_dir: str = ""          # 3rdparty/plugins dir; empty = auto-detect
    fab_exclude_dnp: bool = True
    fab_auto_translate: bool = True
    fab_auto_fill: bool = False
    fab_all_active_layers: bool = False
    fab_user1_vcut: bool = False
    fab_user2_alt_edge_cut: bool = False
    fab_generate_backup: bool = True
    fab_archive_name: str = ""
    fab_extra_layers: str = ""
    bulk_fab: bool = True


def _parse(data: dict) -> AppSettings:
    return AppSettings(**{k: v for k, v in data.items() if k in AppSettings.__dataclass_fields__})


def load_settings() -> AppSettings:
    """Load from global (APPDATA) location; return defaults on any error."""
    try:
        with open(_global_settings_path(), encoding="utf-8") as fh:
            return _parse(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return AppSettings()


def load_settings_from(path: str) -> AppSettings | None:
    """Load from an explicit path; return None if the file is absent or invalid."""
    try:
        with open(path, encoding="utf-8") as fh:
            return _parse(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return None


def save_settings(settings: AppSettings) -> None:
    """Save to global (APPDATA) location."""
    save_settings_to(settings, _global_settings_path())


def save_settings_to(settings: AppSettings, path: str) -> None:
    """Save to an explicit path, creating parent directories as needed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(settings), fh, indent=2)
