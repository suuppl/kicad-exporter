from __future__ import annotations

import io
import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from fpdf import FPDF
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    FloatObject,
    NameObject,
    PdfObject,
    RectangleObject,
    StreamObject,
    TextStringObject,
)

_PT_PER_MM = 72 / 25.4
# A4 landscape (pt); used when no input PDF sets a larger page size
_DEFAULT_PAGE_PT = (297 * _PT_PER_MM, 210 * _PT_PER_MM)
_MARGIN = 15.0      # mm
_GAP = 6.0          # mm between grid cells
_CAPTION_H = 7.0    # mm below each grid image
_JS_FUNCTION_RE = re.compile(r"\bfunction\s+(\w+)")
# Page-jump target in KiCad's popup menu entries: ["label", "#<page index>"]
_JS_PAGE_TARGET_RE = re.compile(r'(,\s*["\'])#(\d+)(["\'])')

# PdfWriter.append() adds each page with /Annots stripped, compares it to the
# original and warns "Annotation sizes differ: N vs. 0" for every page that has
# links, then re-inserts the annotations itself. The warning is spurious (links
# and property popups survive the merge), so keep it off the console.
logging.getLogger("pypdf.generic._link").setLevel(logging.ERROR)


@dataclass
class CombinedPdfContent:
    title: str
    subtitle_lines: list[str] = field(default_factory=list)
    cover_image: str | None = None
    # (page heading, [(caption, png path), ...]); each group is laid out as a
    # grid on a single page
    image_groups: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    # (bookmark label, pdf path), appended with every page scaled to the common size
    pdfs: list[tuple[str, str]] = field(default_factory=list)


def _latin1(text: str) -> str:
    # fpdf2's built-in core fonts only cover latin-1.
    return text.encode("latin-1", "replace").decode("latin-1")


def _load_cropped(path: str) -> Image.Image:
    """Load a render with its empty (transparent) border trimmed off."""
    img = Image.open(path)
    img.load()
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
        bbox = img.convert("RGBA").getchannel("A").getbbox()
        if bbox:
            pad = 8
            img = img.crop((
                max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height),
            ))
    return img


def _fit(img: Image.Image, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Largest box with img's aspect ratio centred in (x, y, w, h)."""
    scale = min(w / img.width, h / img.height)
    iw, ih = img.width * scale, img.height * scale
    return x + (w - iw) / 2, y + (h - ih) / 2, iw, ih


def _best_grid(images: list[Image.Image], w: float, h: float) -> tuple[int, int]:
    """Pick the column count that makes the grid images largest."""
    aspect = max(img.width / img.height for img in images)
    best = (0.0, 1, len(images))
    for cols in range(1, len(images) + 1):
        rows = math.ceil(len(images) / cols)
        cell_w = (w - (cols - 1) * _GAP) / cols
        cell_h = (h - (rows - 1) * _GAP) / rows - _CAPTION_H
        if cell_w <= 0 or cell_h <= 0:
            continue
        img_w = min(cell_w, cell_h * aspect)
        if img_w > best[0]:
            best = (img_w, cols, rows)
    return best[1], best[2]


def _render_cover_and_images(content: CombinedPdfContent, page_w: float, page_h: float) -> bytes:
    pdf = FPDF(unit="mm", format=(page_w, page_h))
    pdf.set_auto_page_break(False)
    pdf.set_title(_latin1(content.title))
    usable_w = page_w - 2 * _MARGIN

    # Title page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_xy(_MARGIN, _MARGIN + 5)
    pdf.multi_cell(usable_w, 12, _latin1(content.title), align="C")
    if content.subtitle_lines:
        pdf.set_font("Helvetica", "", 13)
        pdf.set_text_color(90, 90, 90)
        pdf.ln(2)
        pdf.set_x(_MARGIN)
        pdf.multi_cell(usable_w, 7, _latin1("\n".join(content.subtitle_lines)), align="C")
        pdf.set_text_color(0, 0, 0)
    if content.cover_image:
        img = _load_cropped(content.cover_image)
        top = pdf.get_y() + 10
        x, y, w, h = _fit(img, _MARGIN, top, usable_w, page_h - _MARGIN - top)
        pdf.image(img, x=x, y=y, w=w, h=h)

    # One page per group, renders in a grid with captions
    for heading, items in content.image_groups:
        if not items:
            continue
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_xy(_MARGIN, _MARGIN)
        pdf.cell(usable_w, 8, _latin1(heading))
        top = _MARGIN + 12
        images = [_load_cropped(path) for _caption, path in items]
        cols, rows = _best_grid(images, usable_w, page_h - _MARGIN - top)
        cell_w = (usable_w - (cols - 1) * _GAP) / cols
        cell_h = (page_h - _MARGIN - top - (rows - 1) * _GAP) / rows
        pdf.set_font("Helvetica", "", 10)
        for i, ((caption, _path), img) in enumerate(zip(items, images)):
            cx = _MARGIN + (i % cols) * (cell_w + _GAP)
            cy = top + (i // cols) * (cell_h + _GAP)
            x, y, w, h = _fit(img, cx, cy, cell_w, cell_h - _CAPTION_H)
            pdf.image(img, x=x, y=y, w=w, h=h)
            pdf.set_xy(cx, y + h + 1)
            pdf.cell(cell_w, _CAPTION_H - 1, _latin1(caption), align="C")

    return bytes(pdf.output())


def _target_page_size(readers: list[PdfReader]) -> tuple[float, float]:
    """Common page size (pt, landscape): the largest page among the inputs."""
    best = _DEFAULT_PAGE_PT
    for reader in readers:
        for page in reader.pages:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            if w * h > best[0] * best[1]:
                best = (max(w, h), min(w, h))
    return best


def _normalize_page(page, long_side: float, short_side: float) -> float:
    """Scale a page uniformly to fit the common size, keeping its orientation.

    Only scale() is applied to the content (it also rescales annotation rects,
    so schematic links/popups stay in place); centring is done by moving the
    media box around the scaled content instead of translating the content.
    Returns the scale factor, which destinations into the page must also get
    (see _scale_destinations).
    """
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    tw, th = (long_side, short_side) if w >= h else (short_side, long_side)
    factor = min(tw / w, th / h)
    if abs(factor - 1) > 1e-3:
        page.scale_by(factor)
    mb = page.mediabox
    cx = float(mb.left) + float(mb.width) / 2
    cy = float(mb.bottom) + float(mb.height) / 2
    box = RectangleObject((cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2))
    page.mediabox = box
    page.cropbox = box
    for name in ("/TrimBox", "/BleedBox", "/ArtBox"):
        if name in page:
            del page[name]
    return factor


# Positions of the user-space coordinates in a destination array
# [page, /type, ...], per destination type.
_DEST_COORD_INDICES = {
    "/XYZ": (2, 3),
    "/FitH": (2,), "/FitBH": (2,),
    "/FitV": (2,), "/FitBV": (2,),
    "/FitR": (2, 3, 4, 5),
}


def _scale_destinations(writer: PdfWriter, factors: dict[int, float]) -> None:
    """Scale the coordinates of destinations that point into scaled pages.

    page.scale() transforms the content and annotation rects, but explicit
    destinations (e.g. the /FitR zoom-to-symbol bookmarks in KiCad schematic
    PDFs) still hold the old coordinates and would land on the wrong spot.
    factors maps page object id -> scale factor.
    """
    done: set[int] = set()

    def scale_dest(dest) -> None:
        if dest is None:
            return
        dest = dest.get_object()
        if not isinstance(dest, ArrayObject) or len(dest) < 2 or id(dest) in done:
            return
        page_ref = dest[0]
        factor = factors.get(getattr(page_ref, "idnum", -1))
        if factor is None:
            return
        done.add(id(dest))
        for i in _DEST_COORD_INDICES.get(str(dest[1]), ()):
            if i < len(dest) and isinstance(dest[i], (int, float)):
                dest[i] = FloatObject(float(dest[i]) * factor)
        if str(dest[1]) == "/XYZ" and len(dest) > 4 and isinstance(dest[4], (int, float)) and dest[4]:
            # Same region at the same on-screen size
            dest[4] = FloatObject(float(dest[4]) / factor)

    def scale_action_or_dest(obj) -> None:
        if "/Dest" in obj:
            scale_dest(obj["/Dest"])
        action = obj.get("/A")
        if action is not None:
            action = action.get_object()
            if action.get("/S") == "/GoTo":
                scale_dest(action.get("/D"))

    for page in writer.pages:
        for annot in page.get("/Annots") or []:
            scale_action_or_dest(annot.get_object())

    outlines = writer.root_object.get("/Outlines")
    stack = [outlines.get_object().get("/First")] if outlines is not None else []
    while stack:
        item = stack.pop()
        if item is None:
            continue
        item = item.get_object()
        scale_action_or_dest(item)
        stack.append(item.get("/First"))
        stack.append(item.get("/Next"))


def _js_text(obj: PdfObject) -> str:
    obj = obj.get_object()
    if isinstance(obj, StreamObject):
        return obj.get_data().decode("latin-1")
    return str(obj)


def _document_scripts(reader: PdfReader) -> list[str]:
    """Document-level JavaScript (/Names /JavaScript name tree) of a PDF.

    KiCad's schematic PDF defines the ShM() function its property popups call
    here; PdfWriter.append() does not carry it over.
    """
    names = reader.root_object.get("/Names")
    tree = names.get_object().get("/JavaScript") if names is not None else None
    scripts: list[str] = []

    def walk(node: PdfObject | None) -> None:
        if node is None:
            return
        node = node.get_object()
        entries = node.get("/Names")
        if entries is not None:
            entries = entries.get_object()
            for i in range(1, len(entries), 2):
                action = entries[i].get_object()
                if "/JS" in action:
                    scripts.append(_js_text(action["/JS"]))
        for kid in node.get("/Kids") or []:
            walk(kid)

    walk(tree)
    return scripts


def _shift_js_page_targets(page, offset: int) -> None:
    """Shift '#N' page-jump targets in a page's JavaScript link actions.

    ShM() jumps with this.pageNum = N, an absolute page index that was valid in
    the source PDF; after merging, the PDF's pages start at `offset`.
    """
    if offset == 0:
        return
    for annot in page.get("/Annots") or []:
        action = annot.get_object().get("/A")
        if action is None:
            continue
        action = action.get_object()
        if action.get("/S") != "/JavaScript" or "/JS" not in action:
            continue
        code = _js_text(action["/JS"])
        shifted = _JS_PAGE_TARGET_RE.sub(
            lambda m: f"{m.group(1)}#{int(m.group(2)) + offset}{m.group(3)}", code
        )
        if shifted != code:
            action[NameObject("/JS")] = TextStringObject(shifted)


def build_combined_pdf(
    content: CombinedPdfContent,
    output_path: str,
    log: Callable[[str], None],
) -> None:
    """Write title page + render pages + appended PDFs into output_path, with
    every page at the same size (orientation preserved)."""
    readers = [(label, path, PdfReader(path)) for label, path in content.pdfs]
    long_side, short_side = _target_page_size([r for _l, _p, r in readers])
    log(f"Page size: {long_side / _PT_PER_MM:.0f} x {short_side / _PT_PER_MM:.0f} mm")

    writer = PdfWriter()
    cover = _render_cover_and_images(content, long_side / _PT_PER_MM, short_side / _PT_PER_MM)
    writer.append(io.BytesIO(cover), outline_item="Board renders")
    scripts: list[str] = []
    defined: set[str] = set()
    factors: dict[int, float] = {}
    for label, path, reader in readers:
        first = len(writer.pages)
        writer.append(reader, outline_item=label)
        for page in writer.pages[first:]:
            factors[page.indirect_reference.idnum] = _normalize_page(page, long_side, short_side)
            _shift_js_page_targets(page, first)
        for script in _document_scripts(reader):
            # Schematic and layout PDFs (KiCad, board2pdf) each define their own
            # ShM(); the one loaded last would win, so keep the first definition.
            functions = set(_JS_FUNCTION_RE.findall(script))
            if script in scripts or (functions and functions <= defined):
                continue
            scripts.append(script)
            defined |= functions
        log(f"Appended {os.path.basename(path)}")
    _scale_destinations(writer, factors)
    for script in scripts:
        writer.add_js(script)
    with open(output_path, "wb") as fh:
        writer.write(fh)
    log(f"Wrote {output_path}")
