"""
Координаты ячеек полей OCR — вычислены по формулам blank.py и titul.py.
Система координат: origin сверху-слева страницы (top-down), пункты PDF.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from blank_geometry import MARGIN, PAGE_H, PAGE_W, SQUARE, crop_rect_pdf_topdown

BOX_W = 14.0
BOX_H = 20.0
BOX_GAP = 2.7

Rect = Tuple[float, float, float, float]  # x_top, y_top, width, height (pt, top-down)


def _cell_rects(x_start: float, y: float, count: int) -> List[Rect]:
    rects: List[Rect] = []
    x = x_start
    for _ in range(count):
        rect_y = y - BOX_H / 2 + 3.5
        y_top = PAGE_H - rect_y - BOX_H
        rects.append((x, y_top, BOX_W, BOX_H))
        x += BOX_W + BOX_GAP
    return rects


def _header_line_y(paragraph_height: float = 24.0) -> float:
    square = 14.0
    y_hdr = PAGE_H - MARGIN - square - paragraph_height + 19.0
    return y_hdr - 8.0


def _blan_title_y(line_y: float) -> float:
    text_y = line_y - 22.0
    return text_y - 11.5 + 3.0


def blan1_next_cells() -> List[Rect]:
    line_y = _header_line_y()
    y = _blan_title_y(line_y)
    return _cell_rects(MARGIN + 185, y + 10, 13)


def blan2_cells() -> Dict[str, List[Rect]]:
    line_y = _header_line_y()
    y = _blan_title_y(line_y)
    return {
        "page": _cell_rects(MARGIN + 124, y + 10.5, 3),
        "reserve": _cell_rects(MARGIN + 250, y + 10.5, 9),
    }


def titul_cells() -> Dict[str, List[Rect]]:
    line_y = _header_line_y()
    y_next = _blan_title_y(line_y)
    next_cells = _cell_rects(MARGIN + 185, y_next + 10, 13)

    y_after_title = (line_y - 22.0 - 10.0) - 25.0
    start_fields = y_after_title
    line_after_fields = start_fields - 3 * 26.0 - 14.0

    text_y_grid = line_after_fields - 18.0
    start_grid = text_y_grid - 22.0
    line_after_grid1 = start_grid - 13 * 24.0 + 10.0

    text_y_grid2 = line_after_grid1 - 18.0
    start_grid2 = text_y_grid2 - 22.0
    line_after_grid2 = start_grid2 - 4 * 24.0 + 10.0

    text_y_org = line_after_grid2 - 18.0
    text_y_last = text_y_org - 27.0
    y_last = text_y_last - 11.5 + 3.0
    last_cells = _cell_rects(MARGIN + 215, y_last + 10, 13)

    text_y_cnt = text_y_last - 34.0
    m2 = 102.0
    y_cnt = text_y_cnt - 11.5 + 5.0
    count_cells = _cell_rects(MARGIN + 286 + m2, y_cnt + 13.5, 3)

    return {
        "next": next_cells,
        "last": last_cells,
        "count": count_cells,
    }


FIELD_LAYOUT: Dict[str, Dict[str, List[Rect]]] = {
    "blan1": {"next": blan1_next_cells()},
    "blan2": blan2_cells(),
    "titul": titul_cells(),
}


def crop_margin_pt(crop_margin_ratio: float = 0.35) -> float:
    return crop_margin_ratio * SQUARE


_TRIM_TOP    = 3
_TRIM_LEFT   = 2
_TRIM_RIGHT  = 0
_TRIM_BOTTOM = 0

def cell_to_pixels(
    rect: Rect,
    image_width: int,
    image_height: int,
    crop_margin_ratio: float = 0.35,
) -> Tuple[int, int, int, int]:
    margin_pt = crop_margin_pt(crop_margin_ratio)
    cx1, cy1, cx2, cy2 = crop_rect_pdf_topdown(margin_pt)
    crop_w = cx2 - cx1
    crop_h = cy2 - cy1

    scale_x = image_width / crop_w
    scale_y = image_height / crop_h

    x_pt, y_pt, w_pt, h_pt = rect
    x1 = int(round((x_pt - cx1) * scale_x)) + _TRIM_LEFT
    y1 = int(round((y_pt - cy1) * scale_y)) + _TRIM_TOP
    x2 = int(round((x_pt + w_pt - cx1) * scale_x)) - _TRIM_RIGHT
    y2 = int(round((y_pt + h_pt - cy1) * scale_y)) - _TRIM_BOTTOM

    x1 = max(0, min(x1, image_width - 1))
    y1 = max(0, min(y1, image_height - 1))
    x2 = max(x1 + 1, min(x2, image_width))
    y2 = max(y1 + 1, min(y2, image_height))
    return x1, y1, x2, y2
