from __future__ import annotations

import os
import random
import struct
import time
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
PersonData = dict[str, str]

WIDTH, HEIGHT = A4
MARGIN = 21
SQUARE_SIZE = 14
ZHIR_LINE = 1

BOX_W = 14
BOX_H = 20
BOX_GAP = 2.7

IMAGE_CONFIGS = {
    "path": "пример4.jpg",
    "x": WIDTH / 2 - 219,
    "y": HEIGHT - 200,
    "scale": 0.32,
}

DATA_LIST: list[PersonData] = [
    {
        "surname": "ЖИВАЕВ",
        "name": "ДАВИД",
        "patronymic": "АРТЕМОВИЧ",
        "place": "1А",
        "class": "9С1",
        "number": "000001",
        "ppe": "2-428",
    },
]


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Spectral", "Spectral-Medium.ttf"))
    pdfmetrics.registerFont(TTFont("Spectral-Bold", "Spectral-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Times", r"C:\Windows\Fonts\times.ttf"))
    pdfmetrics.registerFont(TTFont("Times-Bold", r"C:\Windows\Fonts\timesbd.ttf"))
    pdfmetrics.registerFont(TTFont("Overpass", f"Overpass-Regular.ttf"))


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


def draw_cells(
    c: CanvasType,
    x_start: float,
    y: float,
    count: int,
    text: str | None = None,
    mashtab: float | None = None,
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


def set_markers(c: CanvasType) -> None:
    corners = [
        (MARGIN + 78, HEIGHT - MARGIN - SQUARE_SIZE),
        (WIDTH - MARGIN - SQUARE_SIZE, HEIGHT - MARGIN - SQUARE_SIZE),
        (MARGIN, MARGIN),
        (WIDTH - MARGIN - SQUARE_SIZE, MARGIN),
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

    text = "ГБОУ «Бауманская инженерная школа № 1580»"
    p = Paragraph(text, style)

    usable_width = WIDTH - 2 * MARGIN
    p.wrap(usable_width, HEIGHT)

    x = MARGIN + 40
    y = HEIGHT - MARGIN - SQUARE_SIZE - 24 + 19
    p.drawOn(c, x, y)

    line_y = y - 8
    draw_line(c, line_y + 6, width=ZHIR_LINE * 0.8, start=77.5)

    return line_y


def draw_fields(c: CanvasType, data: PersonData, start_y: float) -> float:
    c.setFont("Spectral", 12)
    line_gap = 26
    left_x = MARGIN + 7

    labels_left = ["Фамилия:", "Имя:", "Отчество:"]
    values_left = [data["surname"], data["name"], data["patronymic"]]

    c.saveState()
    enable_cell_style(c)
    for i, (label, value) in enumerate(zip(labels_left, values_left)):
        y = start_y - i * line_gap
        c.drawString(left_x, y, label)
        draw_cells(c, left_x + 70, y, 19, text=value)
    c.restoreState()

    labels_right = ["Место:", "Класс:", "ППЭ:"]
    values_right = [data["place"], data["class"], data["ppe"]]
    right_x = (WIDTH / 2) + 128

    c.saveState()
    enable_cell_style(c)
    for i, (label, value) in enumerate(zip(labels_right, values_right)):
        y = start_y - i * line_gap
        c.drawString(right_x + 6, y, label)
        draw_cells(c, right_x + 60, y, 5, text=value)
    c.restoreState()

    line_y = y - 14
    draw_line(c, line_y, width=ZHIR_LINE)
    return line_y


def add_bottom_3blocks(c: CanvasType, y_top: float, data: PersonData) -> float:
    y_top = y_top + 5
    y1 = y_top - 10
    frame_h = 35

    c.setLineWidth(1)
    c.rect(190, y1 - frame_h - 20, 214.5, 30)

    c.setFont("Spectral", 8)
    c.drawCentredString(
        WIDTH / 2, 45, "Подпись ответветственного организатора строго в окошке"
    )

    y3 = y_top - 35
    return y3 - 3 * 22 - 30


def add_exam_lists_grid(c: CanvasType, y_top: float) -> float:
    c.setFont("Spectral-Bold", 12)
    text_y = y_top - 18
    c.drawCentredString(
        WIDTH / 2, text_y, "Решение тестовой части. Каждый символ СТРОГО в клеточке!"
    )

    start_y = text_y - 22
    cols = 2
    rows = 13
    col_width = (WIDTH - 2 * MARGIN) / cols

    c.saveState()
    enable_cell_style(c)
    num = 1
    for col in range(cols):
        x_base = MARGIN + col * col_width + 4
        for row in range(rows):
            y = start_y - row * 24
            c.setFont("Spectral-Bold", 10)
            c.drawString(x_base, y, str(num))
            draw_cells(c, x_base + 18, y, 17, mashtab=0.88)
            num += 1
    c.restoreState()

    line_y = start_y - rows * 24 + 10
    draw_line(c, line_y, width=ZHIR_LINE)

    c.setFont("Spectral-Bold", 12)
    text_y = line_y - 18
    c.drawCentredString(
        WIDTH / 2, text_y, "Замена ошибочных ответов. Каждый символ СТРОГО в клеточке!"
    )

    start_y = text_y - 22
    cols, rows = 2, 4

    c.saveState()
    enable_cell_style(c)
    for col in range(cols):
        for row in range(rows):
            y = start_y - row * 24
            if col == 0:
                draw_cells(c, MARGIN + 3, y, 2, mashtab=0.8)
                draw_line_xy(c, MARGIN + 30, y + 3, MARGIN + 34, y + 3, 1.6)
                draw_cells(c, MARGIN + 36, y, 17, mashtab=0.8)
            else:
                draw_cells(c, MARGIN + 284, y, 2, mashtab=0.8)
                draw_line_xy(c, MARGIN + 311, y + 3, MARGIN + 315, y + 3, 1.6)
                draw_cells(c, MARGIN + 317, y, 17, mashtab=0.8)
    c.restoreState()

    line_y = start_y - rows * 24 + 10
    draw_line(c, line_y, width=ZHIR_LINE)

    text_y = line_y - 18
    c.drawCentredString(
        WIDTH / 2, text_y, "ЗАПОЛНЯЕТСЯ ОТВЕТСТВЕННЫМ ОРГАНИЗАТОРОМ В АУДИТОРИИ:"
    )

    styles = getSampleStyleSheet()
    style = styles["Normal"]
    style.fontName = "Spectral"
    style.fontSize = 9
    style.leading = 24
    style.alignment = 1

    p_next = Paragraph("Номер последнего", style)
    p_next2 = Paragraph("бланка решений", style)

    usable_width = WIDTH - 2 * MARGIN
    p_next.wrap(usable_width, HEIGHT)
    p_next2.wrap(usable_width, HEIGHT)

    text_y = text_y - 27
    x = MARGIN - 120
    y = text_y - 11.5 + 3
    y2 = text_y - 11.5 - 11 + 3

    p_next.drawOn(c, x, y + 2)
    p_next2.drawOn(c, x, y2 + 2)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 215, y + 10, 13)
    c.restoreState()

    p_repl = Paragraph("Количество заполненных полей", style)
    p_repl2 = Paragraph("«Замена ошибочных ответов»", style)
    p_cnt = Paragraph("Количество", style)
    p_cnt2 = Paragraph("бланков решений", style)

    p_repl.wrap(usable_width, HEIGHT)
    p_repl2.wrap(usable_width, HEIGHT)
    p_cnt.wrap(usable_width, HEIGHT)
    p_cnt2.wrap(usable_width, HEIGHT)

    text_y = text_y - 34
    m1, m2 = -53, 102

    x = MARGIN - 45 + m1
    y = text_y - 11.5 + 5
    y2 = text_y - 11.5 - 11 + 5
    p_repl.drawOn(c, x, y + 5)
    p_repl2.drawOn(c, x, y2 + 5)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 315 + m1, y + 13.5, 1)
    c.restoreState()

    x = MARGIN - 45 + m2
    y = text_y - 11.5 + 5
    y2 = text_y - 11.5 - 11 + 5
    p_cnt.drawOn(c, x, y + 5)
    p_cnt2.drawOn(c, x, y2 + 5)

    c.saveState()
    enable_cell_style(c)
    draw_cells(c, MARGIN + 286 + m2, y + 13.5, 3)
    c.restoreState()

    return line_y


def add_exam_title(c: CanvasType, y_line: float, number: int | str) -> float:
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
    c.rect(
        barcode_x - padding, barcode_y - padding, bw + padding * 2 - 9, bh + padding * 2
    )
    c.restoreState()

    return text_y - 10


def draw_custom_images(c: CanvasType) -> None:
    path = IMAGE_CONFIGS["path"]
    if os.path.exists(path):
        try:
            c.saveState()
            c.translate(IMAGE_CONFIGS["x"], IMAGE_CONFIGS["y"])
            c.scale(IMAGE_CONFIGS["scale"], IMAGE_CONFIGS["scale"])
            c.drawImage(path, 0, 0, mask="auto")
            c.restoreState()
        except Exception as e:
            print(f"Ошибка отрисовки изображения {path}: {e}")
    else:
        print(f"Предупреждение: Файл {path} не найден в текущей папке!")


def create_pdfs(filename: str, data_list: list[PersonData]) -> None:
    start_time = time.perf_counter()
    c = canvas.Canvas(filename, pagesize=A4)

    for data in data_list:
        set_markers(c)
        draw_custom_images(c)
        number = random.randint(1_000_000_000_000, 9_999_999_999_999)

        y = add_header(c)
        y = add_exam_title(c, y, number) - 25
        y = draw_fields(c, data, y) - 26
        add_exam_lists_grid(c, y)
        add_bottom_3blocks(c, MARGIN + 96, data)

        qr_data = make_qr_data(number, uuid.uuid4(), "titul")
        draw_qr(c, qr_data)

        c.showPage()

    c.save()
    total_time = time.perf_counter() - start_time

    print("\nГотово!")
    print(f"Время генерации: {total_time:.3f} сек")
    print(f"Страниц: {len(data_list)}")


if __name__ == "__main__":
    register_fonts()
    create_pdfs("Регистрационный лист.pdf", DATA_LIST)
