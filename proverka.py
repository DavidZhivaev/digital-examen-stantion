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
    pdfmetrics.registerFont(TTFont("Spectral-Bold", "Spectral-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Overpass", "Overpass-Regular.ttf"))


def make_qr_data(work_id: uuid.UUID, type_: str) -> str:
    if len(type_) != 5:
        raise ValueError("type должен содержать ровно 5 symbols")

    data = bytearray()
    data.append(1)
    data.extend(type_.encode("ascii"))
    data.extend(work_id.bytes)

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


def draw_cells(
    c: CanvasType,
    x_start: float,
    y: float,
    count: int,
    text: str | None = None,
    mashtab: float | None = None
) -> None:
    x = x_start
    box_w = BOX_W * mashtab if mashtab is not None else BOX_W
    box_h = BOX_H * mashtab if mashtab is not None else BOX_H
    chars = list(text) if text else []

    for i in range(count):
        rect_y = y - box_h / 2 + 3.5

        if text:
            c.setFillGray(0.97)
        else:
            c.setFillGray(1)
            
        c.roundRect(x, rect_y, box_w, box_h, 2, stroke=1, fill=1)
        c.setFillGray(0)

        if i < len(chars):
            char = chars[i]
            text_x = x + box_w / 2
            text_y = rect_y + box_h / 2 - 4
            c.setFont("Spectral", 11)
            c.drawCentredString(text_x, text_y, char)

        x += box_w + BOX_GAP

    c.setFont("Spectral", 12)


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


def set_markers(c: CanvasType) -> None:
    corners = [
        (MARGIN + 78, HEIGHT - MARGIN - SQUARE_SIZE),
        (WIDTH - MARGIN - SQUARE_SIZE, HEIGHT - MARGIN - SQUARE_SIZE),
        (MARGIN, MARGIN),
        (WIDTH - MARGIN - SQUARE_SIZE, MARGIN)
    ]

    for x, y in corners:
        c.rect(x, y, SQUARE_SIZE, SQUARE_SIZE, fill=1)

    usable_width = WIDTH - 2 * MARGIN - SQUARE_SIZE
    step = usable_width / 3

    for i in range(1, 3):
        c.rect(MARGIN + i * step, MARGIN, SQUARE_SIZE, SQUARE_SIZE, fill=1)


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


def add_exam_title_lic(c: CanvasType, y_line: float) -> float:
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Spectral"
    style.fontSize = 9
    style.leading = 24
    style.alignment = 1

    p = Paragraph("Ключ проверяющего", style)
    p2 = Paragraph("от тех. специалиста:", style)

    usable_width = WIDTH - 2 * MARGIN
    p.wrap(usable_width, HEIGHT)
    p2.wrap(usable_width, HEIGHT)

    m = -5

    text_y = y_line - 22
    x = MARGIN - 150
    y = text_y - 11.5 + 3
    y2 = text_y - 11.5 - 11 + 3

    p.drawOn(c, x + m, y + 2)
    p2.drawOn(c, x + m, y2 + 2)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 185 + m, y + 10, 13)
    c.restoreState()

    return text_y - 20


def set_proverka_set(c: CanvasType, y_line: float, block_count: int = 1) -> float:
    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Spectral"
    style.fontSize = 9
    style.leading = 24
    style.alignment = 1

    p = Paragraph("Первый", style)
    p2 = Paragraph("бланк:", style)

    usable_width = WIDTH - 2 * MARGIN
    p.wrap(usable_width, HEIGHT)
    p2.wrap(usable_width, HEIGHT)

    m1 = -104
    m2 = 180
    x = MARGIN - 150
    
    cols = 5
    rows = 3
    col_width = 268 / cols
    right_offset = 285 

    current_y = y_line
    global_top = y_line - 2
    global_bottom = current_y

    c.saveState()
    c.setLineWidth(0.5)

    for i in range(block_count):
        text_y = current_y - 22
        
        y_text1 = text_y - 11.5 + 3
        y_text2 = text_y - 11.5 - 11 + 3
        start_y = text_y - 22

        p.drawOn(c, x + m1, y_text1 + 2)
        p2.drawOn(c, x + m1, y_text2 + 2)

        c.saveState()
        enable_cell_style(c)
        draw_cells(c, MARGIN + 154 + m1, y_text1 + 10, 13)
        c.restoreState()

        c.saveState()
        enable_cell_style(c)
        num = 1
        for col in range(cols):
            x_base = MARGIN + col * col_width + 4
            for row in range(rows):
                y_curr = start_y - row * 24
                c.setFont("Spectral-Bold", 10)
                c.drawString(x_base, y_curr, str(num))
                draw_cells(c, x_base + 18, y_curr, 2, mashtab=0.88)
                num += 1
        c.restoreState()

        p.drawOn(c, x + m2, y_text1 + 2)
        p2.drawOn(c, x + m2, y_text2 + 2)

        c.saveState()
        enable_cell_style(c)
        draw_cells(c, MARGIN + 154 + m2, y_text1 + 10, 13)
        c.restoreState()

        c.saveState()
        enable_cell_style(c)
        num = 1 
        for col in range(cols):
            x_base = MARGIN + right_offset + col * col_width + 4
            for row in range(rows):
                y_curr = start_y - row * 24
                c.setFont("Spectral-Bold", 10)
                c.drawString(x_base, y_curr, str(num))
                draw_cells(c, x_base + 18, y_curr, 2, mashtab=0.88)
                num += 1
        c.restoreState()

        box_bottom = text_y - 82
        global_bottom = box_bottom

        if i < block_count - 1:
            c.line(MARGIN, box_bottom, WIDTH - MARGIN, box_bottom)

        current_y = box_bottom + 2

    c.rect(MARGIN, global_bottom, WIDTH - 2 * MARGIN, global_top - global_bottom, stroke=1, fill=0)
    
    c.line(WIDTH / 2, global_bottom, WIDTH / 2, global_top)
    
    c.restoreState()

    return global_bottom - 10

def add_bottom_3blocks(c: CanvasType) -> float:
    y_top = 828
    y1 = y_top - 10
    frame_h = 35

    m = 220
    c.setLineWidth(0.25)
    c.setDash([0.3, 2.5])
    c.rect(220 + m, y1 - frame_h - 20 + 6, 120, 27)

    c.setFont("Spectral", 8)
    c.drawCentredString(220 + m + 61, y1 - frame_h - 20 + 8 - 10, "Подпись проверяющего")

    y3 = y_top - 35
    return y3 - 3 * 22 - 30

def create_pdf(filename: str) -> None:
    c = canvas.Canvas(filename, pagesize=A4)

    blanks_data = [(uuid.uuid4(), "provr")]

    for work_id, type_ in blanks_data:
        set_markers(c)
        y1 = add_header(c)
        y2 = add_exam_title_lic(c, y1) + 5
        
        set_proverka_set(c, y2, block_count=7)
        
        draw_qr(c, make_qr_data(work_id, type_))
        add_bottom_3blocks(c)
        c.showPage()

    c.save()


if __name__ == "__main__":
    register_fonts()
    create_pdf("Лист проверки.pdf")