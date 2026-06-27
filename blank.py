from __future__ import annotations

import random
import struct
from typing import Any
import uuid

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import eanbc, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

CanvasType = canvas.Canvas
WIDTH, HEIGHT = A4

MARGIN = 21
SQUARE_SIZE = 14
ZHIR_LINE = 1
PAGE_WIDTH_LITERAL = 595.27

BOX_W = 14
BOX_H = 20
BOX_GAP = 2.7


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Spectral", "Spectral-Medium.ttf"))
    pdfmetrics.registerFont(TTFont("Times", r"C:\Windows\Fonts\times.ttf"))
    pdfmetrics.registerFont(TTFont("Times-Bold", r"C:\Windows\Fonts\timesbd.ttf"))
    pdfmetrics.registerFont(TTFont("Overpass", "Overpass-Regular.ttf"))


def make_qr_data(blank_id: int, work_id: uuid.UUID, type_: str) -> str:
    if not (1_000_000_000_000 <= blank_id <= 9_999_999_999_999):
        raise ValueError("blank_id должен содержать 13 цифр")

    if len(type_) != 5:
        raise ValueError("type должен содержать ровно 5 символов")

    data = bytearray(32)
    data[0] = 1
    data[1:6] = type_.encode("ascii")

    struct.pack_into(">Q", data, 6, blank_id)
    data[14:30] = work_id.bytes

    return data.hex()


def draw_qr(c: CanvasType, data: str) -> None:
    qr_code = qr.QrCodeWidget(data)
    bounds = qr_code.getBounds()
    w = bounds[2] - bounds[0]
    size = 75

    d = Drawing(size, size)
    d.add(qr_code)

    scale = size / w
    d.scale(scale, scale)

    x = MARGIN - 7.5
    y = HEIGHT - MARGIN - size + 7.8
    d.drawOn(c, x, y)


def draw_cells(c: CanvasType, x_start: float, y: float, count: int) -> None:
    x = x_start
    for _ in range(count):
        rect_y = y - BOX_H / 2 + 3.5
        c.setFillGray(1)
        c.roundRect(x, rect_y, BOX_W, BOX_H, 2, stroke=1, fill=1)
        x += BOX_W + BOX_GAP


def enable_cell_style(c: CanvasType) -> None:
    c.setLineWidth(0.25)
    c.setDash([0.3, 2.5])


def draw_line(
    c: CanvasType,
    y: float,
    width: float = ZHIR_LINE,
    dashed: bool = False,
    start: float | None = None,
) -> None:
    c.saveState()
    c.setLineWidth(width)
    if dashed:
        c.setDash(4, 2)
    
    x_start = MARGIN + start if start is not None else MARGIN
    c.line(x_start, y, WIDTH - MARGIN, y)
    c.restoreState()


def draw_line_xy(
    c: CanvasType, x1: float, y1: float, x2: float, y2: float, width: float = 1
) -> None:
    c.saveState()
    c.setLineWidth(width)
    c.setDash([])
    c.line(x1, y1, x2, y2)
    c.restoreState()


def draw_tetrad_grid(
    c: CanvasType, x: float, y: float, w: float, h: float, step: float = 10
) -> None:
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)

    c.setLineWidth(0.1)
    c.setDash(0.2, 2)

    xi = x
    while xi <= x + w:
        c.line(xi, y, xi, y + h)
        xi += step

    yi = y
    while yi <= y + h:
        c.line(x, yi, x + w, yi)
        yi += step

    c.restoreState()


def draw_page_decorations(c: CanvasType) -> None:
    draw_line_xy(c, MARGIN, MARGIN + 733.2, MARGIN, MARGIN + 20, width=0.8)
    draw_line_xy(c, MARGIN, MARGIN + 20, PAGE_WIDTH_LITERAL - MARGIN, MARGIN + 20, width=0.8)
    draw_line_xy(c, PAGE_WIDTH_LITERAL - MARGIN, MARGIN + 20, PAGE_WIDTH_LITERAL - MARGIN, MARGIN + 733.2, width=0.8)
    draw_line_xy(c, MARGIN, MARGIN + 733.2, PAGE_WIDTH_LITERAL - MARGIN, MARGIN + 733.2, width=0.8)

    draw_tetrad_grid(
        c, 
        MARGIN, 
        MARGIN + 20, 
        PAGE_WIDTH_LITERAL - 2 * MARGIN, 
        MARGIN + 694, 
        step=14.56
    )


def set_markers(c: CanvasType, type_n: int) -> None:
    corners = [
        (MARGIN + 78, HEIGHT - MARGIN - SQUARE_SIZE),
        (WIDTH - MARGIN - SQUARE_SIZE, HEIGHT - MARGIN - SQUARE_SIZE),
        (MARGIN, MARGIN),
        (WIDTH - MARGIN - SQUARE_SIZE, MARGIN)
    ]

    for x, y in corners:
        c.rect(x, y, SQUARE_SIZE, SQUARE_SIZE, fill=1)

    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Times"
    style.fontSize = 11
    style.leading = 24
    style.alignment = 1

    text = (
        'Экономьте бумагу, новый бланк выдается только после окончания обеих сторон текущего!'
        if type_n == 1 else
        'ОБОРОТНАЯ СТОРОНА БЛАНКА! Начинайте писать с предыдущей!'
    )
    p = Paragraph(text, style)

    usable_width = WIDTH - 2 * MARGIN
    _, h = p.wrap(usable_width, HEIGHT)

    x = MARGIN
    y = HEIGHT - MARGIN - SQUARE_SIZE - h - 772
    p.drawOn(c, x, y)


def add_header(c: CanvasType) -> float:
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Times-Bold"
    style.fontSize = 18
    style.leading = 24
    style.alignment = 1

    text = 'ГБОУ «Бауманская инженерная школа № 1580»'
    p = Paragraph(text, style)

    usable_width = WIDTH - 2 * MARGIN
    _, h = p.wrap(usable_width, HEIGHT)

    x = MARGIN + 40
    y = HEIGHT - MARGIN - SQUARE_SIZE - h + 19
    p.drawOn(c, x, y)

    line_y = y - 8
    draw_line(c, line_y + 6, width=ZHIR_LINE * 0.8, start=77.5)

    return line_y


def add_exam_title_lic(c: CanvasType, y_line: float, number: int | str) -> float:
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Spectral"
    style.fontSize = 9
    style.leading = 24
    style.alignment = 1

    p = Paragraph("Номер следующего", style)
    p2 = Paragraph("бланка решений:", style)

    usable_width = WIDTH - 2 * MARGIN
    p.wrap(usable_width, HEIGHT)
    p2.wrap(usable_width, HEIGHT)

    text_y = y_line - 22
    x = MARGIN - 150
    y = text_y - 11.5 + 3
    y2 = text_y - 11.5 - 11 + 3

    p.drawOn(c, x, y + 2)
    p2.drawOn(c, x, y2 + 2)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 185, y + 10, 13)
    c.restoreState()

    barcode = eanbc.Ean13BarcodeWidget(str(number))
    barcode.barHeight = 25
    barcode.barWidth = 1.25
    barcode.fontName = "Overpass"
    barcode.fontSize = 13

    bounds = barcode.getBounds()
    bw = bounds[2] - bounds[0]
    bh = bounds[3] - bounds[1]

    d = Drawing(bw, bh)
    d.add(barcode)

    barcode_x = x + 563
    barcode_y = y + 1
    renderPDF.draw(d, c, barcode_x, barcode_y)

    padding = 3
    c.saveState()
    c.setDash(0.3, 2)
    c.setLineWidth(0.5)
    c.rect(barcode_x - padding, barcode_y - padding, bw + padding * 2 - 9, bh + padding * 2)
    c.restoreState()

    return text_y - 10


def add_exam_title_back(c: CanvasType, y_line: float, number: int | str) -> float:
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Spectral"
    style.fontSize = 9
    style.leading = 24
    style.alignment = 1

    p = Paragraph("Номер", style)
    p2 = Paragraph("бланка:", style)
    p3 = Paragraph("Для резерва:", style)
    p4 = Paragraph("(не трогать)", style)

    usable_width = WIDTH - 2 * MARGIN
    p.wrap(usable_width, HEIGHT)
    p2.wrap(usable_width, HEIGHT)
    p3.wrap(usable_width, HEIGHT)
    p4.wrap(usable_width, HEIGHT)

    text_y = y_line - 22
    x = MARGIN - 180
    x2 = MARGIN - 65
    y = text_y - 11.5 + 3
    y2 = text_y - 11.5 - 11 + 3

    p.drawOn(c, x, y + 2)
    p2.drawOn(c, x, y2 + 2)
    p3.drawOn(c, x2, y + 2)
    p4.drawOn(c, x2, y2 + 2)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 124, y + 10.5, 3)
    draw_cells(c, MARGIN + 250, y + 10.5, 9)
    c.restoreState()

    barcode = eanbc.Ean13BarcodeWidget(str(number))
    barcode.barHeight = 25
    barcode.barWidth = 1.25
    barcode.fontName = "Overpass"
    barcode.fontSize = 13

    bounds = barcode.getBounds()
    bw = bounds[2] - bounds[0]
    bh = bounds[3] - bounds[1]

    d = Drawing(bw, bh)
    d.add(barcode)

    barcode_x = MARGIN - 150 + 563
    barcode_y = y + 1
    renderPDF.draw(d, c, barcode_x, barcode_y)

    padding = 3
    c.saveState()
    c.setDash(0.3, 2)
    c.setLineWidth(0.5)
    c.rect(barcode_x - padding, barcode_y - padding, bw + padding * 2 - 9, bh + padding * 2)
    c.restoreState()

    return text_y - 10


def create_pdf(filename: str) -> None:
    c = canvas.Canvas(filename, pagesize=A4)

    blanks_data = [(random.randint(1_000_000_000_000, 9_999_999_999_999), uuid.uuid4(), "blan")]

    for blank_id, work_id, type_ in blanks_data:
        set_markers(c, type_n=1)
        y1 = add_header(c)
        add_exam_title_lic(c, y1, blank_id)
        draw_qr(c, make_qr_data(blank_id, work_id, type_ + "1"))
        draw_page_decorations(c)
        c.showPage()

        set_markers(c, type_n=2)
        y1 = add_header(c)
        add_exam_title_back(c, y1, blank_id)
        draw_qr(c, make_qr_data(blank_id, work_id, type_ + "2"))
        draw_page_decorations(c)
        c.showPage()

    c.save()


if __name__ == "__main__":
    register_fonts()
    create_pdf("Бланк решений.pdf")