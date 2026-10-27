from __future__ import annotations

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


def make_app_colors() -> AppColors:
    return AppColors(
        app_bg=wx.Colour(28, 28, 42),
        card_bg=wx.Colour(42, 42, 62),
        text_primary=wx.Colour(220, 220, 235),
        text_secondary=wx.Colour(160, 160, 185),
        text_muted=wx.Colour(100, 100, 125),
        button_bg=wx.Colour(65, 65, 95),
        progress_green=wx.Colour(78, 201, 119),
    )


def make_app_fonts() -> AppFonts:
    def _font(size: int, bold: bool = False, italic: bool = False) -> wx.Font:
        weight = wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL
        style = wx.FONTSTYLE_ITALIC if italic else wx.FONTSTYLE_NORMAL
        return wx.Font(size, wx.FONTFAMILY_DEFAULT, style, weight)

    return AppFonts(
        header=_font(10, bold=True),
        label=_font(9),
        label_bold=_font(9, bold=True),
        sub=_font(8),
        status=_font(9, italic=True),
        button=_font(9, bold=True),
        banner=_font(15, bold=True),
        banner_sub=_font(9),
    )
