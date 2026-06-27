"""
Обработка отсканированных бланков: поиск маркеров, QR, штрихкод, выравнивание и обрезка.

Геометрия маркеров взята из blank.py (4 угла) и titul.py / proverka.py (+2 снизу).
Штрихкод EAN-13 — как в blank.py / titul.py (верхняя часть, номер текущего бланка).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from blank_geometry import (
    MARGIN,
    PAGE_H,
    PAGE_W,
    SQUARE,
    bottom_center_markers_pdf,
    corner_centers_pdf_topdown,
    crop_rect_pdf_topdown,
    expected_horizontal_span_pt,
    expected_vertical_span_pt,
    marker_center_pdf,
)
from qr_parser import BLANK_TYPE_INFO, QrPayload, get_type_info, parse_qr_data

CHAIN_TYPE_CODES = frozenset({"titul", "blan1", "blan2"})
_BLANK_ID_MIN = 1_000_000_000_000
_BLANK_ID_MAX = 9_999_999_999_999


@dataclass
class ProcessResult:
    visible: bool
    image: Optional[Image.Image] = None
    has_markers: bool = False
    has_qr: bool = False
    qr_data: Optional[str] = None
    qr_info: Optional[QrPayload] = None
    barcode_id: Optional[int] = None
    id_source: str = ""
    is_corrupted: bool = False
    marker_count: int = 0
    reason: str = ""


@dataclass
class _Marker:
    cx: float
    cy: float
    x: int
    y: int
    w: int
    h: int
    area: float


def _pil_to_cv(image: Image.Image) -> np.ndarray:
    rgb = image.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def _cv_to_pil(bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _valid_blank_id(value: int) -> bool:
    return _BLANK_ID_MIN <= int(value) <= _BLANK_ID_MAX


def _parse_blank_id_digits(text: str) -> Optional[int]:
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 13 and _valid_blank_id(int(digits)):
        return int(digits)
    # Примечание: 12-значные числа не могут пройти _valid_blank_id,
    # т.к. _BLANK_ID_MIN = 1_000_000_000_000 — это 13 цифр.
    # Если диапазон изменится, эту ветку нужно раскомментировать
    # и скорректировать _BLANK_ID_MIN / _BLANK_ID_MAX.
    return None


def _detect_qr(bgr: np.ndarray, cfg: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    h, w = bgr.shape[:2]
    roi_ratio = float(cfg.get("qr_roi_width_ratio", 0.22))
    roi_h_ratio = float(cfg.get("qr_roi_height_ratio", 0.18))
    roi_w = max(80, int(w * roi_ratio))
    roi_h = max(80, int(h * roi_h_ratio))
    roi = bgr[0:roi_h, 0:roi_w]

    detector = cv2.QRCodeDetector()
    for img in (roi, bgr):
        data, _, _ = detector.detectAndDecode(img)
        if data:
            text = data.strip()
            if text:
                return True, text

    if cfg.get("try_pyzbar", False):
        try:
            from pyzbar.pyzbar import decode as zbar_decode

            for img in (roi, bgr):
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                for obj in zbar_decode(gray):
                    text = obj.data.decode("utf-8", errors="ignore").strip()
                    if text:
                        return True, text
        except Exception:
            pass

    return False, None


def _detect_barcode(bgr: np.ndarray, cfg: Dict[str, Any]) -> Tuple[bool, Optional[int]]:
    """EAN-13 в верхней части бланка (blank.py / titul.py)."""
    try:
        from pyzbar.pyzbar import decode as zbar_decode
    except ImportError:
        return False, None

    h, w = bgr.shape[:2]
    top_ratio = float(cfg.get("barcode_roi_height_ratio", 0.28))
    left_ratio = float(cfg.get("barcode_roi_left_ratio", 0.42))
    roi_y2 = max(80, int(h * top_ratio))
    roi_x1 = max(0, int(w * left_ratio))

    rois = (
        bgr[0:roi_y2, roi_x1:w],
        bgr[0:roi_y2, :],
        bgr,
    )

    for roi in rois:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        variants = (
            gray,
            cv2.equalizeHist(gray),
            cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11),
        )
        for img in variants:
            for obj in zbar_decode(img):
                if obj.type not in ("EAN13", "EAN8", "I25", "CODE128"):
                    continue
                text = obj.data.decode("utf-8", errors="ignore").strip()
                blank_id = _parse_blank_id_digits(text)
                if blank_id is not None:
                    return True, blank_id

    return False, None


def _find_square_markers(gray: np.ndarray, cfg: Dict[str, Any]) -> List[_Marker]:
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area_ratio = float(cfg.get("marker_min_area_ratio", 0.00008))
    max_area_ratio = float(cfg.get("marker_max_area_ratio", 0.003))
    min_area = (w * h) * min_area_ratio
    max_area = (w * h) * max_area_ratio
    min_aspect = float(cfg.get("marker_min_aspect", 0.65))
    max_aspect = float(cfg.get("marker_max_aspect", 1.35))
    min_solidity = float(cfg.get("marker_min_solidity", 0.75))

    markers: List[_Marker] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 4 or bh < 4:
            continue

        aspect = bw / bh
        if aspect < min_aspect or aspect > max_aspect:
            continue

        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0:
            continue
        solidity = area / hull_area
        if solidity < min_solidity:
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.08 * peri, True)
        if len(approx) < 4 or len(approx) > 8:
            continue

        markers.append(
            _Marker(cx=x + bw / 2, cy=y + bh / 2, x=x, y=y, w=bw, h=bh, area=area)
        )

    markers.sort(key=lambda m: m.area, reverse=True)
    return _dedupe_markers(markers, cfg)


def _dedupe_markers(markers: List[_Marker], cfg: Dict[str, Any]) -> List[_Marker]:
    if not markers:
        return []

    avg_size = sum(m.w + m.h for m in markers[:4]) / min(4, len(markers)) / 2
    min_dist = avg_size * float(cfg.get("marker_dedupe_factor", 0.6))

    kept: List[_Marker] = []
    for m in markers:
        if any(abs(m.cx - k.cx) < min_dist and abs(m.cy - k.cy) < min_dist for k in kept):
            continue
        kept.append(m)
    return kept


def _filter_peripheral_markers(
    markers: List[_Marker],
    width: int,
    height: int,
    margin_ratio: float = 0.25,
) -> List[_Marker]:
    """Оставляет кандидатов в угловых зонах листа (не клеточки сетки посередине)."""
    if len(markers) <= 6:
        return markers

    mx = width * margin_ratio
    my = height * margin_ratio
    kept = [
        m
        for m in markers
        if (m.cx <= mx or m.cx >= width - mx) and (m.cy <= my or m.cy >= height - my)
    ]
    return kept if len(kept) >= 4 else markers


def _filter_registration_markers(
    markers: List[_Marker],
    width: int,
    height: int,
    cfg: Dict[str, Any],
) -> List[_Marker]:
    pool = _filter_peripheral_markers(
        markers,
        width,
        height,
        float(cfg.get("marker_corner_margin_ratio", 0.25)),
    )
    if len(markers) <= 8:
        return pool

    areas = sorted((m.area for m in pool), reverse=True)
    if len(areas) < 4:
        return pool

    ref = float(np.median(areas[:4]))
    lo = ref * float(cfg.get("marker_size_min_ratio", 0.55))
    hi = ref * float(cfg.get("marker_size_max_ratio", 1.8))
    sized = [m for m in pool if lo <= m.area <= hi]
    return sized if len(sized) >= 4 else pool


def _assign_corner_roles(
    markers: List[_Marker],
    width: int,
    height: int,
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, _Marker]]:
    """
    Назначает tl/tr/bl/br по экстремальным точкам четырёхугольника.

    Старый алгоритм «2 верхних + 2 нижних по y» ломался на титульнике:
    снизу 4 маркера в одном ряду (bl, bc1, bc2, br), и br принимали за bc1.
    """
    if len(markers) < 4:
        return None

    pool = _filter_registration_markers(markers, width, height, cfg or {})

    tl = min(pool, key=lambda m: m.cx + m.cy)
    tr = max(pool, key=lambda m: m.cx - m.cy)
    bl = min(pool, key=lambda m: m.cx - m.cy)
    br = max(pool, key=lambda m: m.cx + m.cy)

    roles = {"tl": tl, "tr": tr, "bl": bl, "br": br}
    if len({id(v) for v in roles.values()}) < 4:
        pts = sorted(pool, key=lambda m: m.cy)
        top = sorted(pts[:2], key=lambda m: m.cx)
        bottom = sorted(pts[-2:], key=lambda m: m.cx)
        roles = {"tl": top[0], "tr": top[1], "bl": bottom[0], "br": bottom[1]}
    return roles


def _pick_corner_markers(
    markers: List[_Marker],
    width: int,
    height: int,
    cfg: Optional[Dict[str, Any]] = None,
    min_count: int = 4,
) -> List[_Marker]:
    roles = _assign_corner_roles(markers, width, height, cfg)
    if roles is None:
        return markers[:max(min_count, len(markers))]
    return [roles["tl"], roles["tr"], roles["bl"], roles["br"]]


def _markers_for_crop(
    markers: List[_Marker],
    width: int,
    height: int,
    cfg: Dict[str, Any],
    qr_info: Optional[QrPayload],
) -> List[_Marker]:
    if not markers:
        return []
    corner_only = qr_info.corner_only if qr_info and qr_info.valid else False
    if corner_only or len(markers) > 4:
        return _pick_corner_markers(markers, width, height, cfg, min_count=4)
    return markers


def _estimate_scale(corners: Dict[str, _Marker]) -> float:
    src = np.float32([
        [corners["tl"].cx, corners["tl"].cy],
        [corners["tr"].cx, corners["tr"].cy],
        [corners["bl"].cx, corners["bl"].cy],
        [corners["br"].cx, corners["br"].cy],
    ])
    det_w = float(np.linalg.norm(src[1] - src[0]))
    det_h = float(np.linalg.norm(src[0] - src[2]))
    if det_w < 10 or det_h < 10:
        return 1.0
    exp_w = expected_horizontal_span_pt()
    exp_h = expected_vertical_span_pt()
    return (det_w / exp_w + det_h / exp_h) / 2.0


def _rectify_and_crop(
    bgr: np.ndarray,
    corners: Dict[str, _Marker],
    cfg: Dict[str, Any],
) -> np.ndarray:
    """
    Перспективное выравнивание по 4 угловым маркерам и обрезка
    по прямоугольнику маркерной рамки из генераторов.
    """
    scale = _estimate_scale(corners)
    dst_centers = corner_centers_pdf_topdown()

    src = np.float32([
        [corners["tl"].cx, corners["tl"].cy],
        [corners["tr"].cx, corners["tr"].cy],
        [corners["bl"].cx, corners["bl"].cy],
        [corners["br"].cx, corners["br"].cy],
    ])
    dst = np.float32([
        [dst_centers["tl"][0] * scale, dst_centers["tl"][1] * scale],
        [dst_centers["tr"][0] * scale, dst_centers["tr"][1] * scale],
        [dst_centers["bl"][0] * scale, dst_centers["bl"][1] * scale],
        [dst_centers["br"][0] * scale, dst_centers["br"][1] * scale],
    ])

    matrix = cv2.getPerspectiveTransform(src, dst)
    out_w = max(1, int(PAGE_W * scale))
    out_h = max(1, int(PAGE_H * scale))
    warped = cv2.warpPerspective(bgr, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR)

    margin_pt = float(cfg.get("crop_margin_ratio", 0.35)) * SQUARE
    if int(cfg.get("crop_margin_px", 0)) > 0:
        margin_pt = float(cfg["crop_margin_px"]) / scale

    x1, y1, x2, y2 = crop_rect_pdf_topdown(margin_pt)
    cx1, cy1 = int(x1 * scale), int(y1 * scale)
    cx2, cy2 = int(x2 * scale), int(y2 * scale)

    cx1 = max(0, cx1)
    cy1 = max(0, cy1)
    cx2 = min(out_w, cx2)
    cy2 = min(out_h, cy2)

    if cx2 - cx1 < 50 or cy2 - cy1 < 50:
        return warped
    return warped[cy1:cy2, cx1:cx2].copy()


def _count_bottom_markers(markers: List[_Marker], scale_guess: float) -> int:
    """Считает маркеры у нижнего края (titul/provr)."""
    if len(markers) < 5:
        return 0
    centers = bottom_center_markers_pdf()
    tol = 40 * max(scale_guess, 1.0)
    found = 0
    for mx, my in (marker_center_pdf(x, y, w, h) for x, y, w, h in centers):
        target_y = PAGE_H - my
        for m in markers:
            if abs(m.cy - target_y * scale_guess) < tol and abs(m.cx - mx * scale_guess) < tol * 2:
                found += 1
                break
    return found


def crop_by_markers(
    bgr: np.ndarray,
    cfg: Dict[str, Any],
    qr_info: Optional[QrPayload] = None,
) -> Tuple[Optional[np.ndarray], List[_Marker]]:
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    all_markers = _find_square_markers(gray, cfg)

    min_required = 4
    if qr_info and qr_info.valid:
        min_required = qr_info.min_markers

    if len(all_markers) < 4:
        return None, all_markers

    corners = _assign_corner_roles(all_markers, w, h, cfg)
    if corners is None:
        return None, all_markers

    scale_guess = _estimate_scale(corners)
    if qr_info and qr_info.valid and not qr_info.corner_only:
        extra = _count_bottom_markers(all_markers, scale_guess)
        if extra < 2 and len(all_markers) < min_required:
            return None, all_markers

    try:
        cropped = _rectify_and_crop(bgr, corners, cfg)
    except cv2.error:
        return None, all_markers

    return cropped, all_markers


def _infer_type_code(
    qr_info: Optional[QrPayload],
    markers: List[_Marker],
    sheet_part: int,
    width: int,
    height: int,
    cfg: Dict[str, Any],
) -> str:
    if qr_info and qr_info.type_code in CHAIN_TYPE_CODES:
        return qr_info.type_code
    if qr_info and qr_info.type_code:
        return qr_info.type_code

    corners = _assign_corner_roles(markers, width, height, cfg) if markers else None
    scale_guess = _estimate_scale(corners) if corners else 1.0
    bottom_extra = _count_bottom_markers(markers, scale_guess) if markers else 0
    if bottom_extra >= 2 or len(markers) >= 6:
        return "titul"
    if sheet_part >= 2:
        return "blan2"
    return "blan1"


def _needs_blank_id(type_code: str) -> bool:
    return type_code in CHAIN_TYPE_CODES


def _build_qr_payload(
    type_code: str,
    blank_id: Optional[int],
    work_id: Optional[str] = None,
    *,
    valid: bool = True,
) -> QrPayload:
    info = get_type_info(type_code) or {}
    label = info.get("label", f"Неизвестный тип ({type_code})")
    short_label = info.get("short_label", label)
    side = None
    if type_code == "blan1":
        side = "front"
    elif type_code == "blan2":
        side = "back"
    elif type_code in ("titul", "provr"):
        side = "single"
    return QrPayload(
        valid=valid and type_code in BLANK_TYPE_INFO,
        type_code=type_code,
        type_label=label,
        short_label=short_label,
        blank_id=blank_id,
        work_id=work_id,
        side=side,
        min_markers=int(info.get("min_markers", 4)),
        max_markers=int(info.get("max_markers", 6)),
        corner_only=bool(info.get("corner_only", False)),
    )


def _resolve_identity(
    qr_info: Optional[QrPayload],
    barcode_id: Optional[int],
    markers: List[_Marker],
    sheet_part: int,
    width: int,
    height: int,
    cfg: Dict[str, Any],
) -> Tuple[Optional[QrPayload], Optional[int], str, bool]:
    type_code = _infer_type_code(qr_info, markers, sheet_part, width, height, cfg)
    qr_valid = bool(qr_info and qr_info.valid)
    qr_blank_id = qr_info.blank_id if qr_info and qr_valid and qr_info.blank_id is not None else None

    if qr_blank_id is not None and _valid_blank_id(qr_blank_id):
        merged = _build_qr_payload(
            type_code=qr_info.type_code if qr_info and qr_info.type_code else type_code,
            blank_id=qr_blank_id,
            work_id=qr_info.work_id if qr_info else None,
            valid=True,
        )
        return merged, None, "qr", False

    if barcode_id is not None and _valid_blank_id(barcode_id):
        merged = _build_qr_payload(
            type_code=type_code,
            blank_id=barcode_id,
            work_id=qr_info.work_id if qr_info else None,
            valid=type_code in BLANK_TYPE_INFO,
        )
        return merged, barcode_id, "barcode", False

    if _needs_blank_id(type_code):
        partial = _build_qr_payload(
            type_code=type_code,
            blank_id=None,
            work_id=qr_info.work_id if qr_info else None,
            valid=False,
        )
        return partial, None, "", True

    partial = qr_info or _build_qr_payload(type_code=type_code, blank_id=None, valid=qr_valid)
    return partial, None, "", False


def process_scanned_blank(
    image: Image.Image,
    config: Optional[Dict[str, Any]] = None,
    *,
    sheet_part: int = 1,
) -> ProcessResult:
    """
    Обрабатывает скан: QR → тип → маркеры → выравнивание → штрихкод → обрезка.
    Лист невидим, если нет ни маркеров, ни QR.
    """
    cfg = (config or {}).get("blank_processing", {})
    bgr = _pil_to_cv(image)
    img_h, img_w = bgr.shape[:2]

    has_qr, qr_data = _detect_qr(bgr, cfg)
    qr_info = parse_qr_data(qr_data) if has_qr and qr_data else None

    cropped, markers = crop_by_markers(bgr, cfg, qr_info=qr_info)

    # Пустой лист — нет угловых маркеров (blan: 4, titul: 6; минимум 4 угла).
    if len(markers) < 4 or cropped is None:
        return ProcessResult(
            visible=False,
            has_markers=False,
            has_qr=has_qr,
            qr_data=qr_data,
            qr_info=qr_info,
            marker_count=len(markers),
            reason="Пустой лист — маркеры не найдены",
        )

    has_markers = True

    search_bgr = cropped if cropped is not None else bgr
    has_barcode, barcode_id = _detect_barcode(search_bgr, cfg)
    if not has_barcode:
        has_barcode, barcode_id = _detect_barcode(bgr, cfg)

    qr_info, stored_barcode, id_source, is_corrupted = _resolve_identity(
        qr_info,
        barcode_id if has_barcode else None,
        markers,
        sheet_part,
        img_w,
        img_h,
        cfg,
    )

    if has_markers and cropped is not None:
        out_image = _cv_to_pil(cropped)
        if qr_info and qr_info.valid and qr_info.corner_only:
            marker_note = "4 угловых маркера, выравнивание"
        elif qr_info and qr_info.type_code:
            marker_note = f"{len(markers)} маркеров, выравнивание ({qr_info.type_code})"
        else:
            marker_note = f"{len(markers)} маркеров, выравнивание"
        reason = f"Обрезано по {marker_note}"
    else:
        out_image = _cv_to_pil(cropped)
        reason = f"{len(markers)} маркеров, выравнивание"

    if id_source == "qr" and qr_info and qr_info.valid:
        reason += f"; {qr_info.type_label}"
    elif id_source == "barcode" and qr_info:
        reason += f"; штрихкод → {qr_info.type_label}"
    elif is_corrupted:
        reason += "; испорченный QR — нужен ввод оператора"

    return ProcessResult(
        visible=True,
        image=out_image,
        has_markers=has_markers,
        has_qr=has_qr,
        qr_data=qr_data,
        qr_info=qr_info,
        barcode_id=stored_barcode,
        id_source=id_source,
        is_corrupted=is_corrupted,
        marker_count=len(markers),
        reason=reason,
    )
