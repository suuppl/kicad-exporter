from __future__ import annotations

import configparser
import os
import queue
import re
import sys

import wx

from src.app_theme import AppColors, AppFonts, make_app_colors, make_app_fonts
from src.export_job import ExportJob
from src.exports import make_step_job_by_name
from src.gui_tabs import BulkExportTab, FabricationTab, LayoutTab, PcbTab, SchematicTab, StepTab
from src.settings import (
    AppSettings,
    load_settings,
    load_settings_from,
    project_settings_path,
    save_settings,
    save_settings_to,
)
from src.ui_constants import RESOLUTION_PRESETS

_POLL_MS = 120

class KiCadExportFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title="KiCad Export", size=wx.Size(900, 740))
        self._settings: AppSettings = load_settings()
        self._colors: AppColors = make_app_colors()
        self._fonts: AppFonts = make_app_fonts()

        # Layer state (informational; used when board2pdf.config.ini is absent)
        self._layers: list[str] = []
        self._selected_layers: list[str] = []
        self._layer_alias: dict[str, str] = {}
        self._using_board2pdf_config: bool = False

        # Export state
        self.render_in_progress: bool = False
        self.log_queue: queue.Queue = queue.Queue()
        self._active_tab: PcbTab | SchematicTab | LayoutTab | StepTab | FabricationTab | None = None

        # Bulk-export state
        self._bulk_active: bool = False
        self._bulk_pending: list[str] = []   # step names still to run
        self._bulk_current: str = ""          # name of currently running step
        self._bulk_step_idx: int = 0
        self._bulk_total: int = 0
        self._bulk_job: ExportJob | None = None
        self._bulk_cancelled: bool = False

        self._build_ui()
        self._restore_settings()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll_log_queue, self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._timer.Start(_POLL_MS)
        self.Centre()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        c = self._colors
        f = self._fonts

        main_panel = wx.Panel(self)
        main_panel.SetBackgroundColour(c.app_bg)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        main_sizer.Add(self._make_banner(main_panel, c, f), 0, wx.EXPAND)
        main_sizer.Add(self._make_paths_card(main_panel, c, f), 0, wx.EXPAND | wx.ALL, 8)

        notebook = wx.Notebook(main_panel)
        notebook.SetBackgroundColour(c.app_bg)
        self.pcb_tab = PcbTab(notebook, c, f)
        self.schematic_tab = SchematicTab(notebook, c, f)
        self.layout_tab = LayoutTab(notebook, c, f)
        self.step_tab = StepTab(notebook, c, f)
        self.fab_tab = FabricationTab(notebook, c, f)
        self.bulk_tab = BulkExportTab(notebook, c, f)
        notebook.AddPage(self.pcb_tab,       "PCB Images")
        notebook.AddPage(self.schematic_tab,  "Schematic")
        notebook.AddPage(self.layout_tab,     "Layout")
        notebook.AddPage(self.step_tab,       "STEP")
        notebook.AddPage(self.fab_tab,        "Fabrication")
        notebook.AddPage(self.bulk_tab,       "Bulk Export")
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        main_panel.SetSizer(main_sizer)

        # Event bindings
        self.pcb_tab.render_button.Bind(wx.EVT_BUTTON, self._run_render)
        self.pcb_tab.resolution_combo.Bind(wx.EVT_COMBOBOX, self._apply_resolution)
        self.pcb_tab.advanced_toggle.Bind(wx.EVT_CHECKBOX, self._on_toggle_advanced)
        self.schematic_tab.export_button.Bind(wx.EVT_BUTTON, self._run_schematic)
        self.layout_tab.export_button.Bind(wx.EVT_BUTTON, self._run_layout)
        self.layout_tab.change_layers_button.Bind(wx.EVT_BUTTON, self._open_board2pdf_config)
        self.step_tab.export_button.Bind(wx.EVT_BUTTON, self._run_step)
        self.fab_tab.export_button.Bind(wx.EVT_BUTTON, self._run_fab)
        self.bulk_tab.generate_button.Bind(wx.EVT_BUTTON, self._run_bulk)
        self.bulk_tab.cancel_button.Bind(wx.EVT_BUTTON, self._cancel_bulk)

    def _make_banner(self, parent: wx.Window, c: AppColors, f: AppFonts) -> wx.Panel:
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(20, 20, 35))
        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label="KiCad Export")
        title.SetFont(f.banner)
        title.SetForegroundColour(c.text_primary)
        sub = wx.StaticText(panel, label="Export PCB images, schematics, and layout PDFs")
        sub.SetFont(f.banner_sub)
        sub.SetForegroundColour(c.text_secondary)
        sizer.Add(title, 0, wx.LEFT | wx.TOP, 12)
        sizer.Add(sub, 0, wx.LEFT | wx.BOTTOM, 12)
        panel.SetSizer(sizer)
        return panel

    def _make_paths_card(self, parent: wx.Window, c: AppColors, f: AppFonts) -> wx.Panel:
        card = wx.Panel(parent)
        card.SetBackgroundColour(c.card_bg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(card, label="Project Paths")
        heading.SetFont(f.header)
        heading.SetForegroundColour(c.text_primary)
        sizer.Add(heading, 0, wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=6)
        grid.AddGrowableCol(1)

        lbl = wx.StaticText(card, label="Project file (.kicad_pro)")
        lbl.SetFont(f.label)
        lbl.SetForegroundColour(c.text_secondary)
        inp = wx.TextCtrl(card)
        self.project_input = inp
        btn = wx.Button(card, label="Browse…")
        btn.SetFont(f.label)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(inp, 1, wx.EXPAND)
        grid.Add(btn, 0)

        lbl = wx.StaticText(card, label="Output folder")
        lbl.SetFont(f.label)
        lbl.SetForegroundColour(c.text_secondary)
        inp = wx.TextCtrl(card)
        self.output_input = inp
        btn = wx.Button(card, label="Browse…")
        btn.SetFont(f.label)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(inp, 1, wx.EXPAND)
        grid.Add(btn, 0)

        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Settings import/export row
        settings_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(card, label="Project settings:")
        lbl.SetFont(f.label)
        lbl.SetForegroundColour(c.text_secondary)
        self._import_btn = wx.Button(card, label="Import…")
        self._export_btn = wx.Button(card, label="Export…")
        for b in (self._import_btn, self._export_btn):
            b.SetFont(f.label)
        settings_row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        settings_row.Add(self._import_btn, 0, wx.RIGHT, 4)
        settings_row.Add(self._export_btn, 0)
        hint = wx.StaticText(card, label="Save/load all settings as JSON next to the project file.")
        hint.SetFont(f.sub)
        hint.SetForegroundColour(c.text_muted)
        sizer.Add(settings_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(hint, 0, wx.LEFT | wx.BOTTOM, 8)

        # KiCad command path (Windows only)
        if sys.platform == "win32":
            cmd_grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=4)
            cmd_grid.AddGrowableCol(1)
            cmd_lbl = wx.StaticText(card, label="KiCad command path")
            cmd_lbl.SetFont(f.label)
            cmd_lbl.SetForegroundColour(c.text_secondary)
            self.kicad_cmd_input = wx.TextCtrl(card)
            self.kicad_cmd_save = wx.Button(card, label="Save")
            self.kicad_cmd_save.SetFont(f.label)
            cmd_grid.Add(cmd_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            cmd_grid.Add(self.kicad_cmd_input, 1, wx.EXPAND)
            cmd_grid.Add(self.kicad_cmd_save, 0)
            cmd_hint = wx.StaticText(card, label="kicad-cmd.bat for setting up the KiCad environment for kicad-cli.")
            cmd_hint.SetFont(f.sub)
            cmd_hint.SetForegroundColour(c.text_muted)
            sizer.Add(cmd_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            sizer.Add(cmd_hint, 0, wx.LEFT | wx.BOTTOM, 8)
            self.kicad_cmd_save.Bind(wx.EVT_BUTTON, self._on_save_settings_click)

        # board2pdf command row
        b2p_grid = wx.FlexGridSizer(cols=3, hgap=6, vgap=4)
        b2p_grid.AddGrowableCol(1)
        b2p_lbl = wx.StaticText(card, label="board2pdf path")
        b2p_lbl.SetFont(f.label)
        b2p_lbl.SetForegroundColour(c.text_secondary)
        self.board2pdf_cmd_input = wx.TextCtrl(card)
        b2p_save = wx.Button(card, label="Save")
        b2p_save.SetFont(f.label)
        b2p_grid.Add(b2p_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        b2p_grid.Add(self.board2pdf_cmd_input, 1, wx.EXPAND)
        b2p_grid.Add(b2p_save, 0)
        b2p_hint = wx.StaticText(card, label='e.g. "C:/Users/username/Documents/KiCad/9.0/3rdparty/plugins/com_gitlab_dennevi_Board2Pdf/board2pdf-cli.py')
        b2p_hint.SetFont(f.sub)
        b2p_hint.SetForegroundColour(c.text_muted)
        sizer.Add(b2p_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(b2p_hint, 0, wx.LEFT | wx.BOTTOM, 8)
        b2p_save.Bind(wx.EVT_BUTTON, self._on_save_settings_click)

        card.SetSizer(sizer)

        # Bind browse buttons
        browse_btns = [w for w in card.GetChildren() if isinstance(w, wx.Button) and w.GetLabel() == "Browse…"]
        browse_btns[0].Bind(wx.EVT_BUTTON, self._browse_project)
        browse_btns[1].Bind(wx.EVT_BUTTON, self._browse_output)
        self.project_input.Bind(wx.EVT_TEXT, self._on_project_text_changed)
        self._import_btn.Bind(wx.EVT_BUTTON, self._on_import_settings)
        self._export_btn.Bind(wx.EVT_BUTTON, self._on_export_settings)

        return card

    # ------------------------------------------------------------------
    # Settings save / restore
    # ------------------------------------------------------------------

    def _restore_settings(self) -> None:
        s = self._settings
        tab = self.pcb_tab

        if s.project_path:
            self.project_input.ChangeValue(s.project_path)
            self._load_project_info(s.project_path)

        if s.output_path:
            self.output_input.SetValue(s.output_path)
        elif s.project_path:
            self.output_input.SetValue(
                os.path.join(os.path.dirname(s.project_path), "export")
            )

        if s.resolution_preset in RESOLUTION_PRESETS:
            tab.resolution_combo.SetValue(s.resolution_preset)
        tab.width_input.SetValue(str(s.width))
        tab.height_input.SetValue(str(s.height))
        tab.set_selected_sides(s.selected_sides)
        tab.background_combo.SetValue(s.background)
        tab.quality_combo.SetValue(s.quality)
        tab.floor_check.SetValue(s.floor)
        tab.perspective_check.SetValue(s.perspective)
        tab.zoom_input.SetValue(s.zoom)
        tab.pan_input.SetValue(s.pan)
        tab.pivot_input.SetValue(s.pivot)
        tab.rotate_input.SetValue(s.rotate)
        tab.light_top_input.SetValue(s.light_top)
        tab.light_bottom_input.SetValue(s.light_bottom)
        tab.light_side_input.SetValue(s.light_side)
        tab.light_camera_input.SetValue(s.light_camera)
        tab.light_side_elevation_input.SetValue(s.light_side_elevation)
        tab.advanced_toggle.SetValue(s.show_advanced)
        tab.bare_check.SetValue(s.render_bare)
        if s.show_advanced:
            tab.show_advanced(True)

        # Apply saved layer selection (intersect with detected layers)
        if s.selected_layer_names and self._layers:
            saved = set(s.selected_layer_names)
            self._selected_layers = [layer for layer in self._layers if layer in saved]
            if self._selected_layers:
                self._update_layers_display()

        self.bulk_tab.pcb_check.SetValue(s.bulk_pcb)
        self.bulk_tab.sch_check.SetValue(s.bulk_sch)
        self.bulk_tab.layout_check.SetValue(s.bulk_layout)
        self.bulk_tab.step_check.SetValue(s.bulk_step)
        self.bulk_tab.fab_check.SetValue(s.bulk_fab)
        self.bulk_tab.combined_check.SetValue(s.bulk_combined)
        self.bulk_tab.delete_renders_check.SetValue(s.bulk_delete_renders)
        self.bulk_tab.update_delete_renders_enabled()

        ft = self.fab_tab
        ft.plugin_dir_input.SetValue(s.fab_plugins_dir)
        ft.exclude_dnp_check.SetValue(s.fab_exclude_dnp)
        ft.auto_translate_check.SetValue(s.fab_auto_translate)
        ft.auto_fill_check.SetValue(s.fab_auto_fill)
        ft.all_active_layers_check.SetValue(s.fab_all_active_layers)
        ft.user1_vcut_check.SetValue(s.fab_user1_vcut)
        ft.user2_alt_edge_cut_check.SetValue(s.fab_user2_alt_edge_cut)
        ft.generate_backup_check.SetValue(s.fab_generate_backup)
        ft.archive_name_input.SetValue(s.fab_archive_name)
        ft.extra_layers_input.SetValue(s.fab_extra_layers)

        sc = self.schematic_tab
        sc.plot_drawing_sheet_check.SetValue(s.sch_plot_drawing_sheet)
        sc.output_mode_combo.SetSelection(1 if s.sch_black_and_white else 0)
        sc.color_theme_input.SetValue(s.sch_color_theme)
        sc.plot_background_check.SetValue(s.sch_plot_background)
        sc.pdf_property_popups_check.SetValue(s.sch_pdf_property_popups)
        sc.pdf_hierarchical_links_check.SetValue(s.sch_pdf_hierarchical_links)
        sc.pdf_metadata_check.SetValue(s.sch_pdf_metadata)

        st = self.step_tab
        st.set_origin_key(s.step_origin)
        st.user_origin_input.SetValue(s.step_user_origin)
        st.format_combo.SetValue(s.step_format)
        st.set_tolerance(s.step_tolerance)
        st.export_board_body_check.SetValue(s.step_export_board_body)
        st.export_components_check.SetValue(s.step_export_components)
        st.cut_vias_check.SetValue(s.step_cut_vias)
        st.include_silkscreen_check.SetValue(s.step_include_silkscreen)
        st.include_soldermask_check.SetValue(s.step_include_soldermask)
        st.include_inner_copper_check.SetValue(s.step_include_inner_copper)
        st.include_tracks_check.SetValue(s.step_include_tracks)
        st.include_pads_check.SetValue(s.step_include_pads)
        st.include_zones_check.SetValue(s.step_include_zones)
        st.fuse_shapes_check.SetValue(s.step_fuse_shapes)
        st.fill_all_vias_check.SetValue(s.step_fill_all_vias)
        st.net_filter_input.SetValue(s.step_net_filter)
        st.component_filter_input.SetValue(s.step_component_filter)
        st.no_dnp_check.SetValue(s.step_no_dnp)
        st.no_unspecified_check.SetValue(s.step_no_unspecified)
        st.subst_models_check.SetValue(s.step_subst_models)
        st.force_check.SetValue(s.step_force)
        st.no_prcurves_check.SetValue(s.step_no_prcurves)

        if sys.platform == "win32":
            self.kicad_cmd_input.SetValue(s.kicad_cmd_path)
        self.board2pdf_cmd_input.SetValue(s.board2pdf_path)

    def _collect_settings(self) -> None:
        s = self._settings
        tab = self.pcb_tab
        s.project_path = self.project_input.GetValue().strip()
        s.output_path = self.output_input.GetValue().strip()
        s.resolution_preset = tab.resolution_combo.GetValue()
        try:
            s.width = int(tab.width_input.GetValue())
            s.height = int(tab.height_input.GetValue())
        except ValueError:
            pass
        s.selected_sides = tab.get_selected_sides()
        s.background = tab.background_combo.GetValue()
        s.quality = tab.quality_combo.GetValue()
        s.floor = tab.floor_check.GetValue()
        s.perspective = tab.perspective_check.GetValue()
        s.zoom = tab.zoom_input.GetValue()
        s.pan = tab.pan_input.GetValue()
        s.pivot = tab.pivot_input.GetValue()
        s.rotate = tab.rotate_input.GetValue()
        s.light_top = tab.light_top_input.GetValue()
        s.light_bottom = tab.light_bottom_input.GetValue()
        s.light_side = tab.light_side_input.GetValue()
        s.light_camera = tab.light_camera_input.GetValue()
        s.light_side_elevation = tab.light_side_elevation_input.GetValue()
        s.show_advanced = tab.advanced_toggle.GetValue()
        s.render_bare = tab.bare_check.GetValue()
        s.selected_layer_names = list(self._selected_layers)
        s.bulk_pcb = self.bulk_tab.pcb_check.GetValue()
        s.bulk_sch = self.bulk_tab.sch_check.GetValue()
        s.bulk_layout = self.bulk_tab.layout_check.GetValue()
        s.bulk_step = self.bulk_tab.step_check.GetValue()
        s.bulk_fab = self.bulk_tab.fab_check.GetValue()
        s.bulk_combined = self.bulk_tab.combined_check.GetValue()
        s.bulk_delete_renders = self.bulk_tab.delete_renders_check.GetValue()
        ft = self.fab_tab
        s.fab_plugins_dir = ft.plugin_dir_input.GetValue().strip()
        s.fab_exclude_dnp = ft.exclude_dnp_check.GetValue()
        s.fab_auto_translate = ft.auto_translate_check.GetValue()
        s.fab_auto_fill = ft.auto_fill_check.GetValue()
        s.fab_all_active_layers = ft.all_active_layers_check.GetValue()
        s.fab_user1_vcut = ft.user1_vcut_check.GetValue()
        s.fab_user2_alt_edge_cut = ft.user2_alt_edge_cut_check.GetValue()
        s.fab_generate_backup = ft.generate_backup_check.GetValue()
        s.fab_archive_name = ft.archive_name_input.GetValue().strip()
        s.fab_extra_layers = ft.extra_layers_input.GetValue().strip()
        sc = self.schematic_tab
        s.sch_plot_drawing_sheet = sc.plot_drawing_sheet_check.GetValue()
        s.sch_black_and_white = sc.output_mode_combo.GetSelection() == 1
        s.sch_color_theme = sc.color_theme_input.GetValue().strip()
        s.sch_plot_background = sc.plot_background_check.GetValue()
        s.sch_pdf_property_popups = sc.pdf_property_popups_check.GetValue()
        s.sch_pdf_hierarchical_links = sc.pdf_hierarchical_links_check.GetValue()
        s.sch_pdf_metadata = sc.pdf_metadata_check.GetValue()
        st = self.step_tab
        s.step_origin = st.get_origin_key()
        s.step_user_origin = st.user_origin_input.GetValue().strip()
        s.step_format = st.format_combo.GetValue()
        s.step_tolerance = st.get_tolerance()
        s.step_export_board_body = st.export_board_body_check.GetValue()
        s.step_export_components = st.export_components_check.GetValue()
        s.step_cut_vias = st.cut_vias_check.GetValue()
        s.step_include_silkscreen = st.include_silkscreen_check.GetValue()
        s.step_include_soldermask = st.include_soldermask_check.GetValue()
        s.step_include_inner_copper = st.include_inner_copper_check.GetValue()
        s.step_include_tracks = st.include_tracks_check.GetValue()
        s.step_include_pads = st.include_pads_check.GetValue()
        s.step_include_zones = st.include_zones_check.GetValue()
        s.step_fuse_shapes = st.fuse_shapes_check.GetValue()
        s.step_fill_all_vias = st.fill_all_vias_check.GetValue()
        s.step_net_filter = st.net_filter_input.GetValue().strip()
        s.step_component_filter = st.component_filter_input.GetValue().strip()
        s.step_no_dnp = st.no_dnp_check.GetValue()
        s.step_no_unspecified = st.no_unspecified_check.GetValue()
        s.step_subst_models = st.subst_models_check.GetValue()
        s.step_force = st.force_check.GetValue()
        s.step_no_prcurves = st.no_prcurves_check.GetValue()
        if sys.platform == "win32":
            s.kicad_cmd_path = self.kicad_cmd_input.GetValue().strip()
        s.board2pdf_path = self.board2pdf_cmd_input.GetValue().strip()

    def _on_close(self, event: wx.Event) -> None:
        self._collect_settings()
        save_settings(self._settings)
        self._save_project_settings_if_loaded()
        event.Skip()

    def _on_save_settings_click(self, _event: wx.Event) -> None:
        self._collect_settings()
        save_settings(self._settings)

    def _save_project_settings_if_loaded(self) -> None:
        project = self._settings.project_path
        if project:
            try:
                save_settings_to(self._settings, project_settings_path(project))
            except OSError:
                pass

    def _on_import_settings(self, _event: wx.Event) -> None:
        project = self.project_input.GetValue().strip()
        if not project:
            wx.MessageBox("Select a project file first.", "No project")
            return
        path = project_settings_path(project)
        loaded = load_settings_from(path)
        if loaded is None:
            wx.MessageBox(f"Settings file not found or invalid:\n{path}", "Import failed")
            return
        self._settings = loaded
        self._restore_settings()

    def _on_export_settings(self, _event: wx.Event) -> None:
        project = self.project_input.GetValue().strip()
        if not project:
            wx.MessageBox("Select a project file first.", "No project")
            return
        self._collect_settings()
        path = project_settings_path(project)
        try:
            save_settings_to(self._settings, path)
            wx.MessageBox(f"Settings saved to:\n{path}", "Exported")
        except OSError as exc:
            wx.MessageBox(str(exc), "Export failed")

    # ------------------------------------------------------------------
    # Path handlers
    # ------------------------------------------------------------------

    def _browse_project(self, _event: wx.Event) -> None:
        dlg = wx.FileDialog(
            self,
            message="Select KiCad project file",
            wildcard="KiCad project files (*.kicad_pro)|*.kicad_pro",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.project_input.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _browse_output(self, _event: wx.Event) -> None:
        dlg = wx.DirDialog(self, message="Select output folder", style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            self.output_input.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_project_text_changed(self, _event: wx.Event) -> None:
        path = self.project_input.GetValue().strip()
        if not path:
            return
        project_dir = os.path.dirname(path)
        if project_dir:
            self.output_input.ChangeValue(os.path.join(project_dir, "export"))
        self._load_project_info(path)
        # Auto-load per-project settings if they exist
        per_project = project_settings_path(path)
        loaded = load_settings_from(per_project)
        if loaded is not None:
            self._settings = loaded
            self._restore_settings()

    def _load_project_info(self, project_path: str) -> None:
        """Populate layer/board2pdf info from the project file."""
        project_dir = os.path.dirname(project_path)
        ini_path = os.path.join(project_dir, "board2pdf.config.ini")
        if not self._load_board2pdf_config(ini_path):
            pcb = os.path.splitext(project_path)[0] + ".kicad_pcb"
            self._detect_kicad_layers(pcb)

    # ------------------------------------------------------------------
    # board2pdf config detection
    # ------------------------------------------------------------------

    def _load_board2pdf_config(self, ini_path: str) -> bool:
        """Read board2pdf.config.ini; populate layer display. Returns True on success."""
        if not os.path.isfile(ini_path):
            return False
        cfg = configparser.ConfigParser()
        try:
            cfg.read(ini_path, encoding="utf-8")
        except configparser.Error:
            return False

        pages: list[str] = []
        for section in cfg.sections():
            # Each section is typically a page/group with a "layers" key.
            layers_val = cfg.get(section, "layers", fallback="")
            if not layers_val:
                # Some configs use the section name itself as a layer name.
                layers_val = section
            enabled = cfg.get(section, "enabled", fallback="true").strip().lower()
            if enabled in ("true", "yes", "1", "on"):
                for layer in re.split(r"[,;]+", layers_val):
                    layer = layer.strip()
                    if layer:
                        pages.append(layer)

        if pages:
            self._layers = list(dict.fromkeys(pages))  # deduplicate, preserve order
            self._selected_layers = list(self._layers)
            self._layer_alias = {layer: layer for layer in self._layers}
            self._using_board2pdf_config = True
            n = len(self._layers)
            self.layout_tab.layers_value.SetLabel(
                f"{n} layer{'s' if n != 1 else ''} from board2pdf.config.ini"
            )
            self.layout_tab.change_layers_button.SetLabel("Open Config")
            return True

        # Config exists but has no recognisable layer sections — treat as empty.
        self._using_board2pdf_config = True
        self.layout_tab.layers_value.SetLabel("board2pdf.config.ini found (no layers parsed)")
        self.layout_tab.change_layers_button.SetLabel("Open Config")
        return True

    # ------------------------------------------------------------------
    # KiCad layer detection (fallback when board2pdf config is absent)
    # ------------------------------------------------------------------

    def _detect_kicad_layers(self, pcb_path: str) -> None:
        try:
            with open(pcb_path, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            return

        m = re.search(r'\(layers\s+(.*?)\n\s*\)', content, re.DOTALL)
        if not m:
            return

        entries = re.findall(r'\(\d+\s+"([^"]+)"\s+\w+(?:\s+"([^"]+)")?', m.group(1))
        self._layer_alias = {}
        self._layers = []
        for internal, display in entries:
            self._layer_alias[internal] = display if display else internal
            self._layers.append(internal)

        self._selected_layers = list(self._layers)
        self._using_board2pdf_config = False
        self.layout_tab.change_layers_button.SetLabel("Change…")
        self._update_layers_display()

    def _update_layers_display(self) -> None:
        if self._using_board2pdf_config:
            return  # label already set by _load_board2pdf_config
        count = len(self._selected_layers)
        total = len(self._layers)
        self.layout_tab.layers_value.SetLabel(f"{count} of {total} layers selected")

    def _open_board2pdf_config(self, _event: wx.Event) -> None:
        if self._using_board2pdf_config:
            project = self.project_input.GetValue().strip()
            if project:
                ini = os.path.join(os.path.dirname(project), "board2pdf.config.ini")
                if os.path.isfile(ini):
                    wx.LaunchDefaultApplication(ini)
                    return
            wx.MessageBox("board2pdf.config.ini not found.", "Not found")
        else:
            self._change_layers(None)

    def _change_layers(self, _event) -> None:
        if not self._layers:
            wx.MessageBox("Load a project file first.", "No layers detected")
            return
        display_names = [self._layer_alias.get(layer, layer) for layer in self._layers]
        dlg = wx.MultiChoiceDialog(self, "Select layers to export:", "Layer Selection", display_names)
        dlg.SetSelections([self._layers.index(layer) for layer in self._selected_layers if layer in self._layers])
        if dlg.ShowModal() == wx.ID_OK:
            self._selected_layers = [self._layers[i] for i in dlg.GetSelections()]
            self._update_layers_display()
        dlg.Destroy()

    # ------------------------------------------------------------------
    # Render controls
    # ------------------------------------------------------------------

    def _apply_resolution(self, _event: wx.Event) -> None:
        key = self.pcb_tab.resolution_combo.GetValue()
        if key in RESOLUTION_PRESETS:
            w, h = RESOLUTION_PRESETS[key]
            self.pcb_tab.width_input.SetValue(str(w))
            self.pcb_tab.height_input.SetValue(str(h))

    def _on_toggle_advanced(self, _event: wx.Event) -> None:
        self.pcb_tab.show_advanced(self.pcb_tab.advanced_toggle.GetValue())

    # ------------------------------------------------------------------
    # Shared export helpers
    # ------------------------------------------------------------------

    def _validate_paths(self) -> tuple[str, str] | None:
        project = self.project_input.GetValue().strip()
        output = self.output_input.GetValue().strip()
        if not project:
            wx.MessageBox("Select a project file first.", "Missing input")
            return None
        if not os.path.isfile(project):
            wx.MessageBox(f"Project file not found:\n{project}", "Missing file")
            return None
        if not output:
            wx.MessageBox("Select an output folder first.", "Missing input")
            return None
        return project, output

    def _prepare_export_ui(self, status_text: str) -> None:
        for tab in (self.pcb_tab, self.schematic_tab, self.layout_tab, self.step_tab, self.fab_tab):
            tab.log_text.SetValue("")
            tab.status_label.SetLabel(status_text)
            tab.progress.SetValue(0)
            tab.show_log(False)
        self.pcb_tab.render_button.Enable(False)
        self.schematic_tab.export_button.Enable(False)
        self.layout_tab.export_button.Enable(False)
        self.step_tab.export_button.Enable(False)
        self.fab_tab.export_button.Enable(False)
        self.bulk_tab.generate_button.Enable(False)
        self.render_in_progress = True

    def _finish_export_ui(self, success: bool) -> None:
        self.pcb_tab.render_button.Enable(True)
        self.schematic_tab.export_button.Enable(True)
        self.layout_tab.export_button.Enable(True)
        self.step_tab.export_button.Enable(True)
        self.fab_tab.export_button.Enable(True)
        self.bulk_tab.generate_button.Enable(True)
        self.render_in_progress = False
        if self._active_tab is not None:
            label = "Done." if success else "Failed — see log for details."
            self._active_tab.status_label.SetLabel(label)
            self._active_tab.show_log(True)

    # ------------------------------------------------------------------
    # Queue polling
    # ------------------------------------------------------------------

    def _poll_log_queue(self, _event: wx.Event) -> None:
        c = self._colors
        while True:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if self._bulk_active:
                self._handle_bulk_event(kind, payload, c)
            else:
                if kind == "line" and self._active_tab is not None:
                    self._active_tab.log_text.AppendText(payload + "\n")
                elif kind == "progress" and self._active_tab is not None:
                    self._active_tab.progress.SetValue(int(payload))
                elif kind == "done":
                    self._finish_export_ui(bool(payload))

    def _handle_bulk_event(self, kind: str, payload, colors: AppColors) -> None:
        if kind == "line":
            self.bulk_tab.log_text.AppendText(payload + "\n")
        elif kind == "progress":
            # Scale progress to the current step's slice
            if self._bulk_total > 0:
                step_frac = float(payload) / 100.0
                idx = self._bulk_step_idx - 1  # already incremented when step started
                overall = (idx + step_frac) / self._bulk_total * 100.0
                self.bulk_tab.progress.SetValue(int(overall))
        elif kind == "cancelled":
            self.bulk_tab.set_step_cancelled(self._bulk_current, colors)
            self._finish_bulk(False, cancelled=True)
        elif kind == "done":
            success = bool(payload)
            step_name = self._bulk_current
            self.bulk_tab.set_step_done(step_name, success, colors)
            if success and self._bulk_pending:
                self._start_next_bulk_step()
            else:
                # Done (either all finished or one failed)
                self._finish_bulk(success)

    def _start_next_bulk_step(self) -> None:
        step_name = self._bulk_pending.pop(0)
        self._bulk_current = step_name
        self._bulk_step_idx += 1
        self.bulk_tab.set_step_running(step_name, self._colors)
        self.bulk_tab.status_label.SetLabel(f"Running: {step_name}…")
        self.bulk_tab.log_text.AppendText(f"\n=== {step_name} ===\n")

        paths = self._validate_paths()
        if paths is None:
            self.log_queue.put(("done", False))
            return
        project, output_dir = paths
        os.makedirs(output_dir, exist_ok=True)

        job = self._make_job(step_name, project, output_dir)
        self._bulk_job = job
        job.start()

    def _finish_bulk(self, success: bool, cancelled: bool = False) -> None:
        self._bulk_active = False
        self._bulk_current = ""
        self._bulk_job = None
        self._bulk_cancelled = False
        self.pcb_tab.render_button.Enable(True)
        self.schematic_tab.export_button.Enable(True)
        self.layout_tab.export_button.Enable(True)
        self.step_tab.export_button.Enable(True)
        self.fab_tab.export_button.Enable(True)
        self.bulk_tab.generate_button.Enable(True)
        self.bulk_tab.cancel_button.Enable(False)
        self.render_in_progress = False
        self.bulk_tab.progress.SetValue(100 if success else self.bulk_tab.progress.GetValue())
        if cancelled:
            label = "Cancelled — see log."
        elif success:
            label = "All steps completed successfully."
        else:
            label = "One or more steps failed — see log."
        self.bulk_tab.status_label.SetLabel(label)

    # ------------------------------------------------------------------
    # Job factory
    # ------------------------------------------------------------------

    def _make_job(self, step_name: str, project: str, output_dir: str) -> ExportJob:
        """Snapshot the UI into settings and build the job for one of STEP_NAMES."""
        self._collect_settings()
        delete_renders = (
            self.bulk_tab.combined_check.GetValue() and self.bulk_tab.delete_renders_check.GetValue()
        )
        return make_step_job_by_name(
            step_name, self._settings, project, output_dir,
            on_event=lambda ev: self.log_queue.put(ev),
            delete_renders=delete_renders,
        )

    # ------------------------------------------------------------------
    # PCB render (direct, single-tab)
    # ------------------------------------------------------------------

    def _run_render(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        project, output_dir = paths

        sides = self.pcb_tab.get_selected_sides()
        if not sides:
            wx.MessageBox("Select at least one side.", "No side selected")
            return

        if not (self.pcb_tab.width_input.GetValue().strip().isdigit()
                and self.pcb_tab.height_input.GetValue().strip().isdigit()):
            wx.MessageBox("Width and height must be integers.", "Invalid input")
            return

        os.makedirs(output_dir, exist_ok=True)
        job = self._make_job("PCB Images", project, output_dir)
        self._active_tab = self.pcb_tab
        self._prepare_export_ui("Rendering…")
        job.start()

    # ------------------------------------------------------------------
    # Schematic export (direct, single-tab)
    # ------------------------------------------------------------------

    def _run_schematic(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        project, output_dir = paths

        os.makedirs(output_dir, exist_ok=True)
        self._active_tab = self.schematic_tab
        self._prepare_export_ui("Exporting schematic…")
        self._make_job("Schematic", project, output_dir).start()

    # ------------------------------------------------------------------
    # Layout export (direct, single-tab)
    # ------------------------------------------------------------------

    def _run_layout(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        project, output_dir = paths

        os.makedirs(output_dir, exist_ok=True)
        self._active_tab = self.layout_tab
        self._prepare_export_ui("Exporting layout…")
        self._make_job("Layout", project, output_dir).start()

    # ------------------------------------------------------------------
    # STEP export (direct, single-tab)
    # ------------------------------------------------------------------

    def _run_step(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        project, output_dir = paths

        os.makedirs(output_dir, exist_ok=True)
        self._active_tab = self.step_tab
        self._prepare_export_ui("Exporting STEP…")
        self._make_job("STEP", project, output_dir).start()

    # ------------------------------------------------------------------
    # Fabrication export (direct, single-tab)
    # ------------------------------------------------------------------

    def _run_fab(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        project, output_dir = paths

        os.makedirs(output_dir, exist_ok=True)
        self._active_tab = self.fab_tab
        self._prepare_export_ui("Exporting fabrication files…")
        self._make_job("Fabrication", project, output_dir).start()

    # ------------------------------------------------------------------
    # Bulk export
    # ------------------------------------------------------------------

    def _run_bulk(self, _event: wx.Event) -> None:
        if self.render_in_progress:
            return
        paths = self._validate_paths()
        if paths is None:
            return

        selected: list[str] = []
        if self.bulk_tab.pcb_check.GetValue():
            selected.append("PCB Images")
        if self.bulk_tab.sch_check.GetValue():
            selected.append("Schematic")
        if self.bulk_tab.layout_check.GetValue():
            selected.append("Layout")
        if self.bulk_tab.step_check.GetValue():
            selected.append("STEP")
        if self.bulk_tab.fab_check.GetValue():
            selected.append("Fabrication")
        if self.bulk_tab.combined_check.GetValue():
            selected.append("Combined PDF")

        if not selected:
            wx.MessageBox("Select at least one step to run.", "Nothing selected")
            return

        self.bulk_tab.log_text.SetValue("")
        self.bulk_tab.progress.SetValue(0)
        self.bulk_tab.reset_step_labels(selected, self._colors)
        self.bulk_tab.status_label.SetLabel("Starting…")

        self._bulk_active = True
        self._bulk_pending = list(selected)
        self._bulk_step_idx = 0
        self._bulk_total = len(selected)
        self._bulk_job = None
        self._bulk_cancelled = False
        self._active_tab = None

        self.pcb_tab.render_button.Enable(False)
        self.schematic_tab.export_button.Enable(False)
        self.layout_tab.export_button.Enable(False)
        self.step_tab.export_button.Enable(False)
        self.fab_tab.export_button.Enable(False)
        self.bulk_tab.generate_button.Enable(False)
        self.bulk_tab.cancel_button.Enable(True)
        self.render_in_progress = True

        self._start_next_bulk_step()

    def _cancel_bulk(self, _event: wx.Event) -> None:
        if not self._bulk_active or self._bulk_job is None or self._bulk_cancelled:
            return
        self._bulk_cancelled = True
        self._bulk_pending.clear()
        self.bulk_tab.status_label.SetLabel(f"Cancelling {self._bulk_current}…")
        self.bulk_tab.cancel_button.Enable(False)
        self._bulk_job.cancel()


class KiCadExportApp(wx.App):
    def OnInit(self) -> bool:
        frame = KiCadExportFrame()
        frame.Show()
        return True
