from __future__ import annotations

import wx

from src.app_theme import AppColors, AppFonts
from src.ui_constants import (
    BACKGROUNDS,
    QUALITIES,
    RESOLUTION_PRESETS,
    SIDE_KEYS,
    SIDE_LABELS,
)

BULK_STEP_NAMES = ["PCB Images", "Schematic", "Layout", "STEP", "Fabrication", "Combined PDF"]

_STEP_ORIGIN_LABELS    = ["Board center", "Drill / place file origin", "Grid origin", "User defined"]
_STEP_ORIGIN_KEYS      = ["board-center", "drill",                    "grid",        "user"]
_STEP_FORMATS          = ["STEP", "GLB", "XAO"]
_TOLERANCE_LABELS      = ["Tight (0.001 mm)", "Standard (0.01 mm)", "Loose (0.1 mm)"]
_TOLERANCE_VALUES      = ["0.001",            "0.01",               "0.1"]

_STATUS_PENDING = "·  Pending"
_STATUS_RUNNING = "▶  Running…"
_STATUS_DONE    = "✓  Done"
_STATUS_FAILED  = "✗  Failed"
_STATUS_SKIP    = "—  Skipped"
_STATUS_CANCELLED = "◼  Cancelled"


def _label(parent: wx.Window, text: str, font: wx.Font, color: wx.Colour) -> wx.StaticText:
    w = wx.StaticText(parent, label=text)
    w.SetFont(font)
    w.SetForegroundColour(color)
    # On Windows, StaticText does not inherit the parent background automatically.
    bg = parent.GetBackgroundColour()
    if bg.IsOk():
        w.SetBackgroundColour(bg)
    return w


def _input(parent: wx.Window, value: str = "", width: int = -1) -> wx.TextCtrl:
    size = wx.Size(width, -1) if width > 0 else wx.DefaultSize
    return wx.TextCtrl(parent, value=value, size=size)


def _card(parent: wx.Window, colors: AppColors) -> wx.Panel:
    panel = wx.Panel(parent)
    panel.SetBackgroundColour(colors.card_bg)
    return panel


def _scroll_wrap(tab: wx.Panel, colors: AppColors) -> tuple[wx.ScrolledWindow, wx.Panel]:
    """Return (scroll_window, card_panel) — card is inside the scroll area."""
    scroll = wx.ScrolledWindow(tab, style=wx.VSCROLL)
    scroll.SetBackgroundColour(colors.app_bg)
    scroll.SetScrollRate(0, 12)
    card = wx.Panel(scroll)
    card.SetBackgroundColour(colors.card_bg)
    return scroll, card


def _attach_scroll(scroll: wx.ScrolledWindow, card: wx.Panel, outer: wx.BoxSizer) -> None:
    """Wrap card in scroll's sizer and add the scroll to the outer sizer."""
    ss = wx.BoxSizer(wx.VERTICAL)
    ss.Add(card, 0, wx.EXPAND | wx.ALL, 8)
    scroll.SetSizer(ss)
    outer.Add(scroll, 1, wx.EXPAND)


class PcbTab(wx.Panel):
    render_button: wx.Button
    advanced_toggle: wx.CheckBox
    resolution_combo: wx.ComboBox
    width_input: wx.TextCtrl
    height_input: wx.TextCtrl
    background_combo: wx.ComboBox
    quality_combo: wx.ComboBox
    floor_check: wx.CheckBox
    perspective_check: wx.CheckBox
    bare_check: wx.CheckBox
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

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._side_checks: dict[str, wx.CheckBox] = {}
        self._build(colors, fonts)

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        scroll, card = _scroll_wrap(self, c)
        cs = wx.BoxSizer(wx.VERTICAL)

        # Resolution row
        res = wx.BoxSizer(wx.HORIZONTAL)
        res.Add(_label(card, "Resolution:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.resolution_combo = wx.ComboBox(card, choices=list(RESOLUTION_PRESETS.keys()), style=wx.CB_READONLY)
        self.resolution_combo.SetSelection(1)
        res.Add(self.resolution_combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.width_input = _input(card, "1920", width=60)
        self.height_input = _input(card, "1080", width=60)
        res.Add(self.width_input, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        res.Add(_label(card, "×", f.label, c.text_muted), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        res.Add(self.height_input, 0, wx.ALIGN_CENTER_VERTICAL)
        cs.Add(res, 0, wx.ALL, 8)

        # Side checkboxes
        sides = wx.BoxSizer(wx.HORIZONTAL)
        sides.Add(_label(card, "Sides:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        for key in SIDE_KEYS:
            chk = wx.CheckBox(card, label=SIDE_LABELS[key])
            chk.SetFont(f.label)
            chk.SetForegroundColour(c.text_secondary)
            chk.SetBackgroundColour(c.card_bg)
            self._side_checks[key] = chk
            sides.Add(chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self._side_checks["top"].SetValue(True)
        cs.Add(sides, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.bare_check = wx.CheckBox(card, label="Also render without components")
        self.bare_check.SetFont(f.label)
        self.bare_check.SetForegroundColour(c.text_secondary)
        self.bare_check.SetBackgroundColour(c.card_bg)
        self.bare_check.SetToolTip(
            "Render each selected side a second time with all component 3D models removed "
            "(saved as <name>_<side>_bare.png)."
        )
        cs.Add(self.bare_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Background + Quality row
        opts = wx.BoxSizer(wx.HORIZONTAL)
        for lbl, attr, choices in [
            ("Background:", "background_combo", BACKGROUNDS),
            ("Quality:",    "quality_combo",    QUALITIES),
        ]:
            opts.Add(_label(card, lbl, f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            combo = wx.ComboBox(card, choices=choices, style=wx.CB_READONLY)
            combo.SetSelection(0)
            setattr(self, attr, combo)
            opts.Add(combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        cs.Add(opts, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Advanced toggle
        self.advanced_toggle = wx.CheckBox(card, label="Show advanced options")
        self.advanced_toggle.SetForegroundColour(c.text_secondary)
        self.advanced_toggle.SetBackgroundColour(c.card_bg)
        self.advanced_toggle.SetFont(f.label)
        cs.Add(self.advanced_toggle, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Advanced panel (hidden by default)
        self._advanced_panel = wx.Panel(card)
        self._advanced_panel.SetBackgroundColour(c.card_bg)
        adv = wx.BoxSizer(wx.VERTICAL)

        # Flags row
        flags = wx.BoxSizer(wx.HORIZONTAL)
        self.floor_check = wx.CheckBox(self._advanced_panel, label="Floor (shadow)")
        self.perspective_check = wx.CheckBox(self._advanced_panel, label="Perspective")
        for chk in (self.floor_check, self.perspective_check):
            chk.SetForegroundColour(c.text_secondary)
            chk.SetBackgroundColour(c.card_bg)
            chk.SetFont(f.label)
        flags.Add(self.floor_check, 0, wx.RIGHT, 16)
        flags.Add(self.perspective_check)
        adv.Add(flags, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # Transform grid (2 rows × 4 cols: label, input, label, input)
        tg = wx.FlexGridSizer(cols=4, hgap=8, vgap=4)
        tg.AddGrowableCol(1)
        tg.AddGrowableCol(3)
        _tips = {
            "zoom_input":   "Zoom factor. Positive = zoom in, negative = zoom out (e.g. -1.5).",
            "pan_input":    "Camera pan offset as x,y,z in board units (e.g. 10,-5,0). Negative values are valid.",
            "pivot_input":  "Rotation pivot point as x,y,z. Defaults to the board centre. Negative values are valid.",
            "rotate_input": "Additional rotation as x,y,z in degrees, applied on top of the side preset (e.g. -30,0,45). Negative values are valid.",
        }
        for lbl, attr in [
            ("Zoom:",          "zoom_input"),
            ("Pan (x,y,z):",   "pan_input"),
            ("Pivot (x,y,z):", "pivot_input"),
            ("Rotate (x,y,z):","rotate_input"),
        ]:
            tg.Add(_label(self._advanced_panel, lbl, f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL)
            inp = _input(self._advanced_panel)
            inp.SetToolTip(_tips[attr])
            setattr(self, attr, inp)
            tg.Add(inp, 1, wx.EXPAND)
        adv.Add(tg, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 4)

        # Lights grid (5 label-input pairs in one row)
        lg = wx.BoxSizer(wx.HORIZONTAL)
        for lbl, attr in [
            ("Light top:",  "light_top_input"),
            ("Bottom:",     "light_bottom_input"),
            ("Side:",       "light_side_input"),
            ("Camera:",     "light_camera_input"),
            ("Side elev.:", "light_side_elevation_input"),
        ]:
            lg.Add(_label(self._advanced_panel, lbl, f.sub, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
            inp = _input(self._advanced_panel, width=52)
            setattr(self, attr, inp)
            lg.Add(inp, 0, wx.RIGHT, 10)
        adv.Add(lg, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        self._advanced_panel.SetSizer(adv)
        cs.Add(self._advanced_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self._advanced_panel.Hide()

        card.SetSizer(cs)
        _attach_scroll(scroll, card, outer)

        self.render_button = wx.Button(self, label="Render PCB Images")
        self.render_button.SetFont(f.button)
        outer.Add(self.render_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.progress = wx.Gauge(self, range=100)
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(self, "", f.status, c.text_muted)
        outer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)

        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.log_text.Hide()

        self.SetSizer(outer)

    def get_selected_sides(self) -> list[str]:
        return [k for k in SIDE_KEYS if self._side_checks[k].GetValue()]

    def set_selected_sides(self, sides: list[str]) -> None:
        for k, chk in self._side_checks.items():
            chk.SetValue(k in sides)

    def show_log(self, visible: bool) -> None:
        self.log_text.Show(visible)
        self.Layout()

    def show_advanced(self, visible: bool) -> None:
        self._advanced_panel.Show(visible)
        self.Layout()


class SchematicTab(wx.Panel):
    export_button: wx.Button
    plot_drawing_sheet_check: wx.CheckBox
    output_mode_combo: wx.ComboBox
    color_theme_input: wx.TextCtrl
    plot_background_check: wx.CheckBox
    pdf_property_popups_check: wx.CheckBox
    pdf_hierarchical_links_check: wx.CheckBox
    pdf_metadata_check: wx.CheckBox
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._build(colors, fonts)

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        scroll, card = _scroll_wrap(self, c)
        two_col = wx.BoxSizer(wx.HORIZONTAL)

        # ── Left: Options ────────────────────────────────────────────
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(_label(card, "Options", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)

        # Plot drawing sheet
        self.plot_drawing_sheet_check = wx.CheckBox(card, label="Plot drawing sheet")
        self.plot_drawing_sheet_check.SetValue(True)
        self.plot_drawing_sheet_check.SetFont(f.label)
        self.plot_drawing_sheet_check.SetForegroundColour(c.text_secondary)
        self.plot_drawing_sheet_check.SetBackgroundColour(c.card_bg)
        left.Add(self.plot_drawing_sheet_check, 0, wx.LEFT | wx.TOP, 8)

        # Output mode
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_row.Add(_label(card, "Output mode:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.output_mode_combo = wx.ComboBox(card, choices=["Color", "Black and white"], style=wx.CB_READONLY)
        self.output_mode_combo.SetSelection(0)
        mode_row.Add(self.output_mode_combo, 1, wx.ALIGN_CENTER_VERTICAL)
        left.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # Color theme
        theme_row = wx.BoxSizer(wx.HORIZONTAL)
        theme_row.Add(_label(card, "Color theme:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.color_theme_input = _input(card, "", width=130)
        self.color_theme_input.SetToolTip("Leave blank for KiCad Default (--theme)")
        theme_row.Add(self.color_theme_input, 1, wx.ALIGN_CENTER_VERTICAL)
        left.Add(theme_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # Plot background color
        self.plot_background_check = wx.CheckBox(card, label="Plot background color")
        self.plot_background_check.SetValue(False)
        self.plot_background_check.SetFont(f.label)
        self.plot_background_check.SetForegroundColour(c.text_secondary)
        self.plot_background_check.SetBackgroundColour(c.card_bg)
        self.plot_background_check.SetToolTip("Include the schematic background color in the PDF.")
        left.Add(self.plot_background_check, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        two_col.Add(left, 1, wx.EXPAND)

        # ── Right: PDF Options ────────────────────────────────────────
        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(_label(card, "PDF Options", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)

        for attr, lbl, default, tip in [
            ("pdf_property_popups_check",    "Generate property popups",                       True, "Embed clickable component property popups in the PDF (--pdf-property-popups)."),
            ("pdf_hierarchical_links_check", "Generate clickable links for hierarchical elements", True, "Embed navigation links between hierarchical sheets (--pdf-hierarchical-links)."),
            ("pdf_metadata_check",           "Generate metadata from AUTHOR & SUBJECT variables",  True, "Write AUTHOR and SUBJECT metadata into the PDF (--pdf-metadata)."),
        ]:
            chk = wx.CheckBox(card, label=lbl)
            chk.SetValue(default)
            chk.SetFont(f.label)
            chk.SetForegroundColour(c.text_secondary)
            chk.SetBackgroundColour(c.card_bg)
            chk.SetToolTip(tip)
            setattr(self, attr, chk)
            right.Add(chk, 0, wx.LEFT | wx.TOP, 8)

        right.Add((0, 8))
        two_col.Add(right, 1, wx.EXPAND)

        card.SetSizer(two_col)
        _attach_scroll(scroll, card, outer)

        self.export_button = wx.Button(self, label="Export Schematic PDF")
        self.export_button.SetFont(f.button)
        outer.Add(self.export_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.progress = wx.Gauge(self, range=100)
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(self, "", f.status, c.text_muted)
        outer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)
        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.log_text.Hide()
        self.SetSizer(outer)

    def show_log(self, visible: bool) -> None:
        self.log_text.Show(visible)
        self.Layout()


class LayoutTab(wx.Panel):
    export_button: wx.Button
    change_layers_button: wx.Button
    layers_value: wx.StaticText
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._build(colors, fonts)

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        scroll, card = _scroll_wrap(self, c)
        cs = wx.BoxSizer(wx.VERTICAL)

        # Layer info row
        lr = wx.BoxSizer(wx.HORIZONTAL)
        lr.Add(_label(card, "Layers:", f.label_bold, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.layers_value = _label(card, "No project loaded", f.label, c.text_muted)
        lr.Add(self.layers_value, 1, wx.ALIGN_CENTER_VERTICAL)
        self.change_layers_button = wx.Button(card, label="Change…")
        self.change_layers_button.SetFont(f.label)
        lr.Add(self.change_layers_button, 0, wx.ALIGN_CENTER_VERTICAL)
        cs.Add(lr, 0, wx.ALL, 12)
        card.SetSizer(cs)
        _attach_scroll(scroll, card, outer)

        self.export_button = wx.Button(self, label="Export Layout PDF")
        self.export_button.SetFont(f.button)
        outer.Add(self.export_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.progress = wx.Gauge(self, range=100)
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(self, "", f.status, c.text_muted)
        outer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)
        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.log_text.Hide()
        self.SetSizer(outer)

    def show_log(self, visible: bool) -> None:
        self.log_text.Show(visible)
        self.Layout()


class StepTab(wx.Panel):
    export_button: wx.Button
    _origin_buttons: list[wx.RadioButton]
    user_origin_input: wx.TextCtrl
    format_combo: wx.ComboBox
    tolerance_combo: wx.ComboBox
    # Board options
    export_board_body_check: wx.CheckBox
    export_components_check: wx.CheckBox
    cut_vias_check: wx.CheckBox
    include_silkscreen_check: wx.CheckBox
    include_soldermask_check: wx.CheckBox
    include_inner_copper_check: wx.CheckBox
    # Conductor options
    include_tracks_check: wx.CheckBox
    include_pads_check: wx.CheckBox
    include_zones_check: wx.CheckBox
    fuse_shapes_check: wx.CheckBox
    fill_all_vias_check: wx.CheckBox
    net_filter_input: wx.TextCtrl
    component_filter_input: wx.TextCtrl
    # Other options
    no_dnp_check: wx.CheckBox
    no_unspecified_check: wx.CheckBox
    subst_models_check: wx.CheckBox
    force_check: wx.CheckBox
    no_prcurves_check: wx.CheckBox
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._build(colors, fonts)

    def _chk(self, parent: wx.Window, attr: str, label: str, default: bool,
              tip: str, c: AppColors, f: AppFonts) -> wx.CheckBox:
        chk = wx.CheckBox(parent, label=label)
        chk.SetValue(default)
        chk.SetFont(f.label)
        chk.SetForegroundColour(c.text_secondary)
        chk.SetBackgroundColour(c.card_bg)
        chk.SetToolTip(tip)
        setattr(self, attr, chk)
        return chk

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        # Scrollable area for all options
        scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
        scroll.SetBackgroundColour(c.app_bg)
        scroll.SetScrollRate(0, 12)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        card = wx.Panel(scroll)
        card.SetBackgroundColour(c.card_bg)
        two_col = wx.BoxSizer(wx.HORIZONTAL)

        # ── Left column ──────────────────────────────────────────────
        left = wx.BoxSizer(wx.VERTICAL)

        # Board Options
        left.Add(_label(card, "Board Options", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)
        for attr, lbl, default, tip in [
            ("export_board_body_check",   "Export board body",             True,  "Include the PCB substrate in the export (uncheck → --no-board-body)."),
            ("export_components_check",   "Export components",             True,  "Include component 3D models in the export (uncheck → --no-components)."),
            ("cut_vias_check",            "Cut vias in board body",        False, "Cut through-hole vias from the PCB body solid (--cut-vias-in-body)."),
            ("include_silkscreen_check",  "Export silkscreen",             False, "Export silkscreen graphics as flat faces (--include-silkscreen)."),
            ("include_soldermask_check",  "Export solder mask",            False, "Export soldermask layers as flat faces (--include-soldermask)."),
            ("include_inner_copper_check","Export inner conductor layers", False, "Export inner copper traces and via annular rings (--include-inner-copper)."),
        ]:
            left.Add(self._chk(card, attr, lbl, default, tip, c, f), 0, wx.LEFT | wx.TOP, 8)

        # Conductor Options
        left.Add(_label(card, "Conductor Options", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 12)
        for attr, lbl, default, tip in [
            ("include_tracks_check", "Export tracks and vias", False, "Export PCB tracks and vias as cylindrical objects."),
            ("include_pads_check",   "Export pads",            False, "Export PCB pads as cylindrical objects."),
            ("include_zones_check",  "Export zones",           False, "Export copper zones as solid objects."),
            ("fuse_shapes_check",    "Fuse shapes (time consuming)", False, "Fuse overlapping geometry together."),
            ("fill_all_vias_check",  "Fill all vias",          False, "Fill all via holes."),
        ]:
            left.Add(self._chk(card, attr, lbl, default, tip, c, f), 0, wx.LEFT | wx.TOP, 8)

        nf_row = wx.BoxSizer(wx.HORIZONTAL)
        nf_row.Add(_label(card, "Net filter:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.net_filter_input = _input(card, "", width=130)
        self.net_filter_input.SetToolTip("Only include conductors for nets matching this pattern (supports wildcards).")
        nf_row.Add(self.net_filter_input, 1, wx.ALIGN_CENTER_VERTICAL)
        left.Add(nf_row, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)

        cf_row = wx.BoxSizer(wx.HORIZONTAL)
        cf_row.Add(_label(card, "Component filter:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.component_filter_input = _input(card, "", width=130)
        self.component_filter_input.SetToolTip("Only include components whose reference matches this pattern (supports wildcards).")
        cf_row.Add(self.component_filter_input, 1, wx.ALIGN_CENTER_VERTICAL)
        left.Add(cf_row, 0, wx.LEFT | wx.TOP | wx.RIGHT | wx.BOTTOM, 8)

        two_col.Add(left, 1, wx.EXPAND)

        # ── Right column ─────────────────────────────────────────────
        right = wx.BoxSizer(wx.VERTICAL)

        # Coordinates / Origin
        right.Add(_label(card, "Coordinates", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)
        self._origin_buttons = []
        for i, lbl in enumerate(_STEP_ORIGIN_LABELS):
            style = wx.RB_GROUP if i == 0 else 0
            rb = wx.RadioButton(card, label=lbl, style=style)
            rb.SetFont(f.label)
            rb.SetForegroundColour(c.text_secondary)
            rb.SetBackgroundColour(c.card_bg)
            rb.Bind(wx.EVT_RADIOBUTTON, self._on_origin_changed)
            self._origin_buttons.append(rb)
            right.Add(rb, 0, wx.LEFT | wx.TOP, 8)
        self._origin_buttons[0].SetValue(True)

        right.Add(_label(card, "User Defined Origin", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 10)
        urow = wx.BoxSizer(wx.HORIZONTAL)
        urow.Add(_label(card, "X, Y (mm):", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.user_origin_input = _input(card, "", width=120)
        self.user_origin_input.SetToolTip("Format: <x>x<y><unit> — e.g. 100x50mm or 1x1in")
        self.user_origin_input.Enable(False)
        urow.Add(self.user_origin_input, 0, wx.ALIGN_CENTER_VERTICAL)
        right.Add(urow, 0, wx.LEFT | wx.TOP, 8)

        # Other Options
        right.Add(_label(card, "Other Options", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 12)
        for attr, lbl, default, tip in [
            ("no_dnp_check",        "Ignore 'Do not populate' components", True,  "Do not include 3D models for DNP components (--no-dnp)."),
            ("no_unspecified_check","Ignore 'Unspecified' components",      False, "Do not include 3D models for components with no specified model (--no-unspecified)."),
            ("subst_models_check",  "Substitute similarly named models",    True,  "Replace VRML models with STEP/IGS equivalents where available (--subst-models)."),
            ("force_check",         "Overwrite old file",                   True,  "Overwrite the output file if it already exists (--force)."),
            ("no_prcurves_check",   "Don't write P-curves to STEP file",   True,  "Default behaviour; uncheck to pass --no-optimize-step (writes parametric curves, disables optimisation)."),
        ]:
            right.Add(self._chk(card, attr, lbl, default, tip, c, f), 0, wx.LEFT | wx.TOP, 8)

        tol_row = wx.BoxSizer(wx.HORIZONTAL)
        tol_row.Add(_label(card, "Board outline chaining tolerance:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.tolerance_combo = wx.ComboBox(card, choices=_TOLERANCE_LABELS, style=wx.CB_READONLY)
        self.tolerance_combo.SetSelection(1)
        tol_row.Add(self.tolerance_combo, 0, wx.ALIGN_CENTER_VERTICAL)
        right.Add(tol_row, 0, wx.LEFT | wx.TOP, 8)

        fmt_row = wx.BoxSizer(wx.HORIZONTAL)
        fmt_row.Add(_label(card, "Output format:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.format_combo = wx.ComboBox(card, choices=_STEP_FORMATS, style=wx.CB_READONLY)
        self.format_combo.SetSelection(0)
        self.format_combo.SetToolTip("GLB and XAO require KiCad 8+")
        fmt_row.Add(self.format_combo, 0, wx.ALIGN_CENTER_VERTICAL)
        right.Add(fmt_row, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        two_col.Add(right, 1, wx.EXPAND)

        card.SetSizer(two_col)
        scroll_sizer.Add(card, 0, wx.EXPAND | wx.ALL, 8)
        scroll.SetSizer(scroll_sizer)
        outer.Add(scroll, 1, wx.EXPAND)

        self.export_button = wx.Button(self, label="Export STEP")
        self.export_button.SetFont(f.button)
        outer.Add(self.export_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.progress = wx.Gauge(self, range=100)
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(self, "", f.status, c.text_muted)
        outer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)

        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.log_text.Hide()

        self.SetSizer(outer)

    def _on_origin_changed(self, _event: wx.Event) -> None:
        self.user_origin_input.Enable(self._origin_buttons[3].GetValue())

    def get_origin_key(self) -> str:
        for i, rb in enumerate(self._origin_buttons):
            if rb.GetValue():
                return _STEP_ORIGIN_KEYS[i]
        return _STEP_ORIGIN_KEYS[0]

    def set_origin_key(self, key: str) -> None:
        idx = _STEP_ORIGIN_KEYS.index(key) if key in _STEP_ORIGIN_KEYS else 0
        for i, rb in enumerate(self._origin_buttons):
            rb.SetValue(i == idx)
        self.user_origin_input.Enable(idx == 3)

    def get_tolerance(self) -> str:
        sel = self.tolerance_combo.GetSelection()
        return _TOLERANCE_VALUES[sel] if 0 <= sel < len(_TOLERANCE_VALUES) else "0.01"

    def set_tolerance(self, value: str) -> None:
        idx = _TOLERANCE_VALUES.index(value) if value in _TOLERANCE_VALUES else 1
        self.tolerance_combo.SetSelection(idx)

    def show_log(self, visible: bool) -> None:
        self.log_text.Show(visible)
        self.Layout()


class FabricationTab(wx.Panel):
    export_button: wx.Button
    plugin_dir_input: wx.TextCtrl
    exclude_dnp_check: wx.CheckBox
    auto_translate_check: wx.CheckBox
    auto_fill_check: wx.CheckBox
    all_active_layers_check: wx.CheckBox
    user1_vcut_check: wx.CheckBox
    user2_alt_edge_cut_check: wx.CheckBox
    generate_backup_check: wx.CheckBox
    archive_name_input: wx.TextCtrl
    extra_layers_input: wx.TextCtrl
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._build(colors, fonts)

    def _chk(self, parent: wx.Window, attr: str, label: str, default: bool,
              tip: str, c: AppColors, f: AppFonts) -> wx.CheckBox:
        chk = wx.CheckBox(parent, label=label)
        chk.SetValue(default)
        chk.SetFont(f.label)
        chk.SetForegroundColour(c.text_secondary)
        chk.SetBackgroundColour(c.card_bg)
        chk.SetToolTip(tip)
        setattr(self, attr, chk)
        return chk

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        scroll, card = _scroll_wrap(self, c)
        cs = wx.BoxSizer(wx.VERTICAL)

        two_col = wx.BoxSizer(wx.HORIZONTAL)

        # ── Left: Assembly ────────────────────────────────────────────
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(_label(card, "Assembly", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)
        for attr, lbl, default, tip in [
            ("exclude_dnp_check",    "Exclude DNP components",                 True,  "Omit 'Do Not Populate' components from BOM and pick & place (--excludeDNP)."),
            ("auto_translate_check", "Apply AUTO TRANSLATE",                   True,  "Apply JLCPCB rotation/position corrections for known component packages (--autoTranslate)."),
            ("auto_fill_check",      "Apply zone fill before export",          False, "Flood-fill all copper zones before generating outputs (--autoFill)."),
        ]:
            left.Add(self._chk(card, attr, lbl, default, tip, c, f), 0, wx.LEFT | wx.TOP, 8)
        left.Add((0, 8))
        two_col.Add(left, 1, wx.EXPAND)

        # ── Right: Gerbers & Archive ──────────────────────────────────
        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(_label(card, "Gerbers & Archive", f.label_bold, c.text_secondary), 0, wx.LEFT | wx.TOP, 8)
        for attr, lbl, default, tip in [
            ("all_active_layers_check",  "Export all active layers",           False, "Export every active layer instead of the standard JLCPCB set (--allActiveLayers)."),
            ("user1_vcut_check",         "User.1 as V-Cut layer",              False, "Include User.1 as a V-Cut/score line layer (--user1VCut)."),
            ("user2_alt_edge_cut_check", "User.2 as alternative Edge-Cut",     False, "Use User.2 as an additional board outline layer (--user2AltVCut)."),
            ("generate_backup_check",    "Generate backup before overwriting", True,  "Copy previous production files to a backups/ folder (uncheck → --noBackup)."),
        ]:
            right.Add(self._chk(card, attr, lbl, default, tip, c, f), 0, wx.LEFT | wx.TOP, 8)

        extra_row = wx.BoxSizer(wx.HORIZONTAL)
        extra_row.Add(_label(card, "Extra layers:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.extra_layers_input = _input(card, "", width=140)
        self.extra_layers_input.SetToolTip("Comma-separated additional layer names to include in the Gerber export.")
        extra_row.Add(self.extra_layers_input, 1, wx.ALIGN_CENTER_VERTICAL)
        right.Add(extra_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        arch_row = wx.BoxSizer(wx.HORIZONTAL)
        arch_row.Add(_label(card, "Archive name:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.archive_name_input = _input(card, "", width=140)
        self.archive_name_input.SetToolTip(
            "Custom base name for the zip archive and the designators/positions/bom CSVs. "
            "Spaces become underscores. Leave blank to use the plugin's default (project) name."
        )
        arch_row.Add(self.archive_name_input, 1, wx.ALIGN_CENTER_VERTICAL)
        right.Add(arch_row, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 8)

        two_col.Add(right, 1, wx.EXPAND)
        cs.Add(two_col, 0, wx.EXPAND)

        # ── Plugin path row ───────────────────────────────────────────
        cs.Add(wx.StaticLine(card), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        plugin_row = wx.BoxSizer(wx.HORIZONTAL)
        plugin_row.Add(_label(card, "Plugin dir:", f.label, c.text_secondary), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.plugin_dir_input = _input(card, "")
        self.plugin_dir_input.SetToolTip(
            "Path to the KiCad 3rdparty/plugins directory containing com_github_bennymeg_JLC-Plugin-for-KiCad. "
            "Leave blank to auto-detect."
        )
        plugin_row.Add(self.plugin_dir_input, 1, wx.ALIGN_CENTER_VERTICAL)
        cs.Add(plugin_row, 0, wx.EXPAND | wx.ALL, 8)

        card.SetSizer(cs)
        _attach_scroll(scroll, card, outer)

        self.export_button = wx.Button(self, label="Export Fabrication Files")
        self.export_button.SetFont(f.button)
        outer.Add(self.export_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.progress = wx.Gauge(self, range=100)
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(self, "", f.status, c.text_muted)
        outer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)
        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.log_text.Hide()
        self.SetSizer(outer)

    def show_log(self, visible: bool) -> None:
        self.log_text.Show(visible)
        self.Layout()


class BulkExportTab(wx.Panel):
    pcb_check: wx.CheckBox
    sch_check: wx.CheckBox
    layout_check: wx.CheckBox
    step_check: wx.CheckBox
    fab_check: wx.CheckBox
    combined_check: wx.CheckBox
    delete_renders_check: wx.CheckBox
    generate_button: wx.Button
    cancel_button: wx.Button
    progress: wx.Gauge
    status_label: wx.StaticText
    log_text: wx.TextCtrl
    _step_labels: dict[str, wx.StaticText]

    def __init__(self, parent: wx.Window, colors: AppColors, fonts: AppFonts) -> None:
        super().__init__(parent)
        self.SetBackgroundColour(colors.app_bg)
        self._step_labels = {}
        self._build(colors, fonts)

    def _build(self, c: AppColors, f: AppFonts) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        # Selection card
        sel_card = _card(self, c)
        sel_sizer = wx.BoxSizer(wx.VERTICAL)
        sel_sizer.Add(_label(sel_card, "Select exports to run:", f.label_bold, c.text_primary), 0, wx.ALL, 8)

        # Fixed grids rather than WrapSizer: a WrapSizer's min height is computed
        # before it wraps, which squashes the button row until the window resizes.
        check_sizer = wx.FlexGridSizer(cols=3, hgap=24, vgap=6)
        for attr, label in [
            ("pcb_check",    "PCB Images Export"),
            ("sch_check",    "Schematic Export"),
            ("layout_check", "Layout Export"),
            ("step_check",   "STEP Export"),
            ("fab_check",    "Fabrication Export"),
            ("combined_check", "Combined PDF"),
        ]:
            chk = wx.CheckBox(sel_card, label=label)
            chk.SetValue(True)
            chk.SetFont(f.label)
            chk.SetForegroundColour(c.text_secondary)
            chk.SetBackgroundColour(c.card_bg)
            setattr(self, attr, chk)
            check_sizer.Add(chk, 0)
        self.combined_check.SetToolTip(
            "Merge title page (board title + corner render), PCB images, schematic PDF and "
            "layout PDF from the output folder into <name>_combined.pdf. Runs last."
        )
        sel_sizer.Add(check_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.delete_renders_check = wx.CheckBox(sel_card, label="Delete renders after combining")
        self.delete_renders_check.SetFont(f.label)
        self.delete_renders_check.SetForegroundColour(c.text_secondary)
        self.delete_renders_check.SetBackgroundColour(c.card_bg)
        self.delete_renders_check.SetToolTip(
            "Remove the PCB render PNGs from the output folder once <name>_combined.pdf "
            "has been written. Only available with Combined PDF selected."
        )
        sel_sizer.Add(self.delete_renders_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.combined_check.Bind(wx.EVT_CHECKBOX, lambda _e: self.update_delete_renders_enabled())

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.generate_button = wx.Button(sel_card, label="Generate Selected")
        self.generate_button.SetFont(f.button)
        self.cancel_button = wx.Button(sel_card, label="Cancel")
        self.cancel_button.SetFont(f.button)
        self.cancel_button.Enable(False)
        button_row.Add(self.generate_button, 0, wx.RIGHT, 8)
        button_row.Add(self.cancel_button, 0)
        sel_sizer.Add(button_row, 0, wx.LEFT | wx.BOTTOM, 8)
        sel_card.SetSizer(sel_sizer)
        outer.Add(sel_card, 0, wx.EXPAND | wx.ALL, 8)

        # Status card
        st_card = _card(self, c)
        st_sizer = wx.BoxSizer(wx.VERTICAL)
        st_sizer.Add(_label(st_card, "Status:", f.label_bold, c.text_primary), 0, wx.ALL, 8)

        step_row = wx.FlexGridSizer(cols=6, hgap=4, vgap=6)
        for name in BULK_STEP_NAMES:
            name_lbl = _label(st_card, f"{name}:", f.label_bold, c.text_secondary)
            step_lbl = _label(st_card, _STATUS_PENDING, f.label, c.text_muted)
            self._step_labels[name] = step_lbl
            step_row.Add(name_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            step_row.Add(step_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        st_sizer.Add(step_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.progress = wx.Gauge(st_card, range=100)
        st_sizer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_label = _label(st_card, "Ready.", f.status, c.text_muted)
        st_sizer.Add(self.status_label, 0, wx.LEFT | wx.BOTTOM, 8)
        st_card.SetSizer(st_sizer)
        outer.Add(st_card, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Log (always visible)
        self.log_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.log_text.SetBackgroundColour(c.card_bg)
        self.log_text.SetForegroundColour(c.text_secondary)
        self.log_text.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(outer)

    def update_delete_renders_enabled(self) -> None:
        self.delete_renders_check.Enable(self.combined_check.GetValue())

    def reset_step_labels(self, selected_names: list[str], colors: AppColors) -> None:
        for name, lbl in self._step_labels.items():
            if name in selected_names:
                lbl.SetLabel(_STATUS_PENDING)
                lbl.SetForegroundColour(colors.text_muted)
            else:
                lbl.SetLabel(_STATUS_SKIP)
                lbl.SetForegroundColour(colors.text_muted)

    def set_step_running(self, name: str, colors: AppColors) -> None:
        lbl = self._step_labels.get(name)
        if lbl:
            lbl.SetLabel(_STATUS_RUNNING)
            lbl.SetForegroundColour(colors.text_secondary)

    def set_step_done(self, name: str, success: bool, colors: AppColors) -> None:
        lbl = self._step_labels.get(name)
        if lbl:
            if success:
                lbl.SetLabel(_STATUS_DONE)
                lbl.SetForegroundColour(colors.progress_green)
            else:
                lbl.SetLabel(_STATUS_FAILED)
                lbl.SetForegroundColour(wx.Colour(220, 60, 60))

    def set_step_cancelled(self, name: str, colors: AppColors) -> None:
        lbl = self._step_labels.get(name)
        if lbl:
            lbl.SetLabel(_STATUS_CANCELLED)
            lbl.SetForegroundColour(colors.text_muted)

    def show_log(self, visible: bool) -> None:
        pass  # log is always visible in the bulk tab
