"""
Разбор QR-кодов бланков по форматам генераторов titul.py, proverka.py, blank.py.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

# Типы из QR (5 символов ASCII) и параметры маркеров из генераторов
BLANK_TYPE_INFO: Dict[str, dict] = {
    "blan1": {
        "label": "Бланк решений (лицо)",
        "short_label": "Бланк решений · лицо",
        "min_markers": 4,
        "max_markers": 4,
        "corner_only": True,
        "duplex_side": 1,
    },
    "blan2": {
        "label": "Бланк решений (оборот)",
        "short_label": "Бланк решений · оборот",
        "min_markers": 4,
        "max_markers": 4,
        "corner_only": True,
        "duplex_side": 2,
    },
    "titul": {
        "label": "Титульный лист",
        "short_label": "Титульный лист",
        "min_markers": 4,
        "max_markers": 6,
        "corner_only": False,
        "duplex_side": 1,
    },
    "provr": {
        "label": "Лист проверки",
        "short_label": "Лист проверки",
        "min_markers": 4,
        "max_markers": 6,
        "corner_only": False,
        "duplex_side": 1,
    },
}

KNOWN_TYPE_CODES = frozenset(BLANK_TYPE_INFO.keys())


@dataclass
class QrPayload:
    valid: bool
    type_code: str = ""
    type_label: str = ""
    short_label: str = ""
    blank_id: Optional[int] = None
    work_id: Optional[str] = None
    side: Optional[str] = None  # front | back | single
    min_markers: int = 4
    max_markers: int = 6
    corner_only: bool = False


def get_type_info(type_code: str) -> Optional[dict]:
    return BLANK_TYPE_INFO.get(type_code)


def parse_qr_data(data: str) -> QrPayload:
    """Декодирует hex-строку из QR (как make_qr_data в генераторах)."""
    text = data.strip()
    if not text:
        return QrPayload(valid=False)

    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return QrPayload(valid=False)

    if len(raw) < 6 or raw[0] != 1:
        return QrPayload(valid=False)

    type_code = raw[1:6].decode("ascii", errors="replace")
    info = BLANK_TYPE_INFO.get(type_code, {})
    label = info.get("label", f"Неизвестный тип ({type_code})")
    short_label = info.get("short_label", label)

    # titul.py / blank.py — 32 байта с blank_id
    if type_code in ("titul", "blan1", "blan2") and len(raw) >= 30:
        blank_id = struct.unpack(">Q", raw[6:14])[0]
        work_id = str(uuid.UUID(bytes=bytes(raw[14:30])))
        side = None
        if type_code == "blan1":
            side = "front"
        elif type_code == "blan2":
            side = "back"
        elif type_code == "titul":
            side = "single"
        return QrPayload(
            valid=type_code in KNOWN_TYPE_CODES,
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

    # proverka.py — без blank_id
    if type_code == "provr" and len(raw) >= 22:
        work_id = str(uuid.UUID(bytes=bytes(raw[6:22])))
        return QrPayload(
            valid=True,
            type_code=type_code,
            type_label=label,
            short_label=short_label,
            work_id=work_id,
            side="single",
            min_markers=int(info.get("min_markers", 4)),
            max_markers=int(info.get("max_markers", 6)),
            corner_only=bool(info.get("corner_only", False)),
        )

    return QrPayload(
        valid=False,
        type_code=type_code,
        type_label=label,
        short_label=short_label,
    )
