"""
Геометрия маркеров из генераторов blank.py, titul.py, proverka.py.

Координаты в пунктах PDF (origin — нижний левый угол, как в ReportLab).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# blank.py / titul.py / proverka.py
PAGE_W = 595.27
PAGE_H = 841.89
MARGIN = 21.0
SQUARE = 14.0

# 4 угловых маркера (левый-нижний x,y + размер) — одинаково во всех генераторах
CORNER_MARKERS_PDF: Tuple[Tuple[float, float, float, float], ...] = (
    (MARGIN + 78, PAGE_H - MARGIN - SQUARE, SQUARE, SQUARE),          # верх-лево
    (PAGE_W - MARGIN - SQUARE, PAGE_H - MARGIN - SQUARE, SQUARE, SQUARE),  # верх-право
    (MARGIN, MARGIN, SQUARE, SQUARE),                                  # низ-лево
    (PAGE_W - MARGIN - SQUARE, MARGIN, SQUARE, SQUARE),                # низ-право
)

# titul / provr: 2 дополнительных маркера по центру нижнего края
def bottom_center_markers_pdf() -> Tuple[Tuple[float, float, float, float], ...]:
    usable = PAGE_W - 2 * MARGIN - SQUARE
    step = usable / 3
    return tuple(
        (MARGIN + i * step, MARGIN, SQUARE, SQUARE)
        for i in (1, 2)
    )


def marker_center_pdf(x: float, y: float, w: float, h: float) -> Tuple[float, float]:
    return x + w / 2, y + h / 2


def corner_centers_pdf_topdown() -> Dict[str, Tuple[float, float]]:
    """
    Центры угловых маркеров в системе «y вниз от верха листа» (как в OpenCV).
    Порядок: tl, tr, bl, br.
    """
    raw = {
        "tl": marker_center_pdf(*CORNER_MARKERS_PDF[0]),
        "tr": marker_center_pdf(*CORNER_MARKERS_PDF[1]),
        "bl": marker_center_pdf(*CORNER_MARKERS_PDF[2]),
        "br": marker_center_pdf(*CORNER_MARKERS_PDF[3]),
    }
    out: Dict[str, Tuple[float, float]] = {}
    for key, (x, y_bottom) in raw.items():
        y_top = PAGE_H - y_bottom
        out[key] = (x, y_top)
    return out


def crop_rect_pdf_topdown(margin_pt: float) -> Tuple[float, float, float, float]:
    """Прямоугольник обрезки (x1, y1, x2, y2) в координатах y-вниз."""
    m = margin_pt
    return (
        MARGIN - m,
        MARGIN - m,
        PAGE_W - MARGIN + m,
        PAGE_H - MARGIN + m,
    )


def expected_horizontal_span_pt() -> float:
    tl, tr, _, _ = (
        marker_center_pdf(*CORNER_MARKERS_PDF[0]),
        marker_center_pdf(*CORNER_MARKERS_PDF[1]),
        marker_center_pdf(*CORNER_MARKERS_PDF[2]),
        marker_center_pdf(*CORNER_MARKERS_PDF[3]),
    )
    return tr[0] - tl[0]


def expected_vertical_span_pt() -> float:
    tl = marker_center_pdf(*CORNER_MARKERS_PDF[0])
    bl = marker_center_pdf(*CORNER_MARKERS_PDF[2])
    return tl[1] - bl[1]
