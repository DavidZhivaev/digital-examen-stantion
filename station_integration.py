"""
Связка станции сканирования с utils.process_auditorium_blanks.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TYPE_CHECKING

from PIL import Image

from utils import (
    AUDITORIUM_STATUS_AUTO_FIXED,
    AUDITORIUM_STATUS_CLEAN,
    AUDITORIUM_STATUS_FINALIZED,
    AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED,
    AUDITORIUM_STATUS_PARTIALLY_FIXED,
    FINAL_STATUS_WAITING_OPERATOR,
    assess_automation_risks,
    process_auditorium_blanks,
    resolve_operator_decision,
    update_manual_decision,
)

if TYPE_CHECKING:
    from main import ScannedBlank

CHAIN_TYPES = frozenset({"titul", "blan1", "blan2"})

STATUS_LABELS: Dict[str, str] = {
    AUDITORIUM_STATUS_CLEAN: "Готово",
    AUDITORIUM_STATUS_AUTO_FIXED: "Автоисправлено",
    AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED: "Нужна проверка",
    AUDITORIUM_STATUS_PARTIALLY_FIXED: "Частично",
    AUDITORIUM_STATUS_FINALIZED: "Завершено",
    "NEEDS_OPERATOR": "Ожидание",
    "PARTIAL": "Замечания",
}

STATUS_COLORS: Dict[str, str] = {
    AUDITORIUM_STATUS_CLEAN: "#16a34a",
    AUDITORIUM_STATUS_AUTO_FIXED: "#2563eb",
    AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED: "#dc2626",
    AUDITORIUM_STATUS_PARTIALLY_FIXED: "#d97706",
    AUDITORIUM_STATUS_FINALIZED: "#16a34a",
    "NEEDS_OPERATOR": "#dc2626",
    "PARTIAL": "#d97706",
}


def format_blank_number(blank_id: Optional[int]) -> str:
    if blank_id is None:
        return ""
    return f"{int(blank_id):013d}"


def resolve_blank_id(blank: "ScannedBlank") -> Optional[int]:
    operator_id = getattr(blank, "operator_blank_id", None)
    if operator_id is not None:
        return int(operator_id)
    qr = blank.qr_info
    if qr and qr.valid and qr.blank_id is not None:
        return int(qr.blank_id)
    barcode_id = getattr(blank, "barcode_id", None)
    if barcode_id is not None:
        return int(barcode_id)
    if qr and qr.blank_id is not None:
        return int(qr.blank_id)
    return None


def blank_needs_chain_id(blank: "ScannedBlank") -> bool:
    qr = blank.qr_info
    type_code = qr.type_code if qr else ""
    if type_code in CHAIN_TYPES:
        return True
    return bool(getattr(blank, "is_corrupted", False))


def corrupted_blanks(blanks: Sequence["ScannedBlank"]) -> List["ScannedBlank"]:
    return [b for b in blanks if getattr(b, "is_corrupted", False)]


def can_link_blanks(blanks: Sequence["ScannedBlank"]) -> bool:
    if not blanks:
        return False
    if corrupted_blanks(blanks):
        return False
    for blank in blanks:
        if not blank_needs_chain_id(blank):
            continue
        if resolve_blank_id(blank) is None:
            return False
        if getattr(blank, "is_corrupted", False):
            return False
    return True


def extract_veroytn(blank: "ScannedBlank") -> Optional[Any]:
    rec = getattr(blank, "recognition", None)
    if rec is None:
        return None
    veroytn = getattr(rec, "veroytn", None)
    if veroytn is not None:
        return veroytn
    raw = getattr(rec, "raw_data", None) or {}
    if isinstance(raw, dict):
        return raw.get("veroytn")
    return None


def blank_to_scan_entry(blank: "ScannedBlank") -> Optional[Dict[str, Any]]:
    if getattr(blank, "is_corrupted", False):
        return None
    qr = blank.qr_info
    type_code = qr.type_code if qr else ""
    if type_code not in CHAIN_TYPES:
        return None
    number = format_blank_number(resolve_blank_id(blank))
    if len(number) != 13:
        return None
    veroytn = extract_veroytn(blank)
    if veroytn is None:
        return None
    return {"type": type_code, "number": number, "veroytn": veroytn}


def build_scan_data(blanks: Sequence["ScannedBlank"]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for blank in blanks:
        item = blank_to_scan_entry(blank)
        if item is not None:
            entries.append(item)
    return entries


def count_chain_ready(blanks: Sequence["ScannedBlank"]) -> Dict[str, int]:
    with_veroytn = 0
    with_id = 0
    for blank in blanks:
        if getattr(blank, "is_corrupted", False):
            continue
        qr = blank.qr_info
        if qr and qr.type_code in CHAIN_TYPES and resolve_blank_id(blank) is not None:
            with_id += 1
            if extract_veroytn(blank) is not None:
                with_veroytn += 1
    return {"chain_blanks": with_id, "with_ocr": with_veroytn}


def auditorium_paths(config: Mapping[str, Any], base_dir: Path) -> Dict[str, Path]:
    aud_cfg = config.get("auditorium", {})
    paths_cfg = aud_cfg.get("data_paths", {})
    return {
        "operator_links_path": base_dir / paths_cfg.get("operator_links", "operator_links.json"),
        "manual_review_queue_path": base_dir / paths_cfg.get("manual_review_queue", "manual_review_queue.json"),
        "manual_history_path": base_dir / paths_cfg.get("manual_history", "manual_history.json"),
        "audit_log_path": base_dir / paths_cfg.get("audit_log", "audit_log.json"),
        "issued_store_path": base_dir / paths_cfg.get("issued_blanks", "issued_blanks.json"),
    }


def reset_operator_session(config: Mapping[str, Any], base_dir: Path) -> None:
    """Сброс всех решений оператора для текущей аудитории."""
    aud_cfg = config.get("auditorium", {})
    auditorium_id = str(aud_cfg.get("id", "default"))
    paths = auditorium_paths(config, base_dir)

    for path in (
        paths["operator_links_path"],
        paths["manual_review_queue_path"],
        paths["manual_history_path"],
        paths["audit_log_path"],
    ):
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                store = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        auditoriums = store.get("auditoriums", {})
        if auditorium_id in auditoriums:
            del auditoriums[auditorium_id]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)


def run_auditorium_processing(
    blanks: Sequence["ScannedBlank"],
    config: Mapping[str, Any],
    base_dir: Path,
) -> Dict[str, Any]:
    aud_cfg = config.get("auditorium", {})
    auditorium_id = aud_cfg.get("id", "default")
    scan_data = build_scan_data(blanks)
    paths = auditorium_paths(config, base_dir)

    if not scan_data:
        return {
            "ok": False,
            "reason": "no_scan_data",
            "message": "Нет бланков с OCR-вероятностями для построения цепочек",
            "scan_data_count": 0,
            "auditorium_status": "",
            "manual_review_queue": [],
            "links": {},
            "renames": {},
            "risk_assessment": {},
        }

    result = process_auditorium_blanks(
        scan_data,
        auditorium_id=auditorium_id,
        return_details=True,
        persist_review_queue=True,
        operator_links_path=paths["operator_links_path"],
        manual_review_queue_path=paths["manual_review_queue_path"],
        manual_history_path=paths["manual_history_path"],
        audit_log_path=paths["audit_log_path"],
        issued_store_path=paths["issued_store_path"],
    )

    blanks_count = sum(
        1
        for b in blanks
        if b.qr_info and b.qr_info.valid and b.qr_info.type_code in ("blan1", "blan2")
    )
    result["risk_assessment"] = assess_automation_risks(result, blanks_count)
    result["ok"] = True
    result["scan_data_count"] = len(scan_data)
    return result


def pending_operator_reviews(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    queue = list(result.get("manual_review_queue", []))
    return [
        item
        for item in queue
        if str(item.get("status", "pending")) == "pending"
        and item.get("show_to_operator", True)
    ]


def status_display(result: Optional[Mapping[str, Any]]) -> tuple[str, str, str]:
    if not result or not result.get("ok"):
        return "—", "#64748b", ""
    status = str(result.get("auditorium_status", result.get("status", "")))
    label = STATUS_LABELS.get(status, status or "—")
    color = STATUS_COLORS.get(status, "#64748b")
    risk = result.get("risk_assessment", {})
    pct = risk.get("estimated_no_human_probability_percent")
    extra = f"{pct:.0f}% авто" if isinstance(pct, (int, float)) else ""
    return label, color, extra


def apply_links_to_blanks(blanks: Sequence["ScannedBlank"], links: Mapping[str, str]) -> None:
    for blank in blanks:
        number = format_blank_number(resolve_blank_id(blank))
        if number and number in links:
            blank.link_next = links[number]
        else:
            blank.link_next = None


def resolve_review(
    review_id: str,
    chosen_candidate: str,
    blanks: Sequence["ScannedBlank"],
    config: Mapping[str, Any],
    base_dir: Path,
    previous_result: Mapping[str, Any],
) -> Dict[str, Any]:
    aud_cfg = config.get("auditorium", {})
    auditorium_id = aud_cfg.get("id", "default")
    scan_data = build_scan_data(blanks)
    paths = auditorium_paths(config, base_dir)
    return update_manual_decision(
        review_id,
        chosen_candidate,
        auditorium_id,
        scan_data,
        previous_result=previous_result,
        operator_links_path=paths["operator_links_path"],
        manual_review_queue_path=paths["manual_review_queue_path"],
        manual_history_path=paths["manual_history_path"],
        audit_log_path=paths["audit_log_path"],
        issued_store_path=paths["issued_store_path"],
    )


def resolve_operator_input(
    src_number: str,
    dst_number: str,
    blanks: Sequence["ScannedBlank"],
    config: Mapping[str, Any],
    base_dir: Path,
    previous_result: Mapping[str, Any],
    review_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Оператор ввёл номер вручную — фиксируем как 100% trusted forced link."""
    aud_cfg = config.get("auditorium", {})
    auditorium_id = aud_cfg.get("id", "default")
    scan_data = build_scan_data(blanks)
    paths = auditorium_paths(config, base_dir)
    result = resolve_operator_decision(
        auditorium_id,
        scan_data,
        str(src_number),
        str(dst_number),
        operator_id="station_operator",
        operator_links_path=paths["operator_links_path"],
        manual_review_queue_path=paths["manual_review_queue_path"],
        manual_history_path=paths["manual_history_path"],
        audit_log_path=paths["audit_log_path"],
        review_id=review_id,
        reason="operator_manual_input",
        previous_result=previous_result,
        recalc_scope="full",
        issued_store_path=paths["issued_store_path"],
    )
    result["ok"] = True
    return result


def session_work_id(blanks: Sequence["ScannedBlank"]) -> Optional[str]:
    """work_id берётся с любого бланка с корректно распознанным QR."""
    for blank in blanks:
        qr = blank.qr_info
        if qr and qr.valid and qr.work_id:
            return qr.work_id
    return None


def _decode_page_number(blank: "ScannedBlank") -> str:
    """Извлекает номер страницы с blan2 (3 цифры)."""
    veroytn = extract_veroytn(blank)
    if veroytn is None:
        return ""
    field: Optional[List] = None
    if isinstance(veroytn, list):
        field = veroytn
    elif isinstance(veroytn, dict):
        for key in ("page", "list", "sheet", "number"):
            if isinstance(veroytn.get(key), list):
                field = veroytn[key]
                break
    if not field or len(field) != 3:
        return ""
    digits = "0123456789"
    chars: List[str] = []
    for pos in field:
        if not isinstance(pos, dict):
            return ""
        best = max(digits, key=lambda c: float(pos.get(c, 0)))
        chars.append(best)
    return "".join(chars)


def export_filename_for_blank(
    blank: "ScannedBlank",
    links: Mapping[str, str],
    renames: Mapping[str, str],
    used_names: set[str],
) -> Optional[str]:
    """
    Имя файла: НОМЕР_QR-РАСПОЗНАННЫЙ.расширение
    blan1/titul → следующий бланк или титул (из links)
    blan2 → номер страницы (3 цифры)
    """
    qr_num = format_blank_number(resolve_blank_id(blank))
    if len(qr_num) != 13:
        return None

    type_code = blank.type_code
    if type_code == "blan2":
        suffix = _decode_page_number(blank) or links.get(qr_num, "")
        if not suffix:
            return None
        base = f"{qr_num}-{suffix}"
    elif type_code in ("titul", "blan1"):
        suffix = links.get(qr_num, "")
        if not suffix and qr_num in renames:
            parts = str(renames[qr_num]).split("-", 1)
            suffix = parts[1] if len(parts) == 2 else ""
        if not suffix:
            return None
        base = f"{qr_num}-{suffix}"
    else:
        return None

    if base in used_names and type_code == "blan2":
        base = f"{base}_oborot"
    elif base in used_names:
        base = f"{base}_{type_code}"

    used_names.add(base)
    return base


def build_export_plan(
    blanks: Sequence["ScannedBlank"],
    auditorium_result: Mapping[str, Any],
    image_format: str = "jpg",
) -> List[Dict[str, Any]]:
    links = auditorium_result.get("links", {})
    renames = auditorium_result.get("renames", {})
    used: set[str] = set()
    plan: List[Dict[str, Any]] = []

    for blank in blanks:
        if blank.type_code not in CHAIN_TYPES:
            continue
        name = export_filename_for_blank(blank, links, renames, used)
        if not name:
            continue
        plan.append({
            "blank_uid": blank.uid,
            "filename": f"{name}.{image_format.lower()}",
            "qr_number": format_blank_number(resolve_blank_id(blank)),
        })
    return plan


def export_work_zip(
    blanks: Sequence["ScannedBlank"],
    auditorium_result: Mapping[str, Any],
    output_path: Path,
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    export_cfg = config.get("export", {})
    image_format = str(export_cfg.get("image_format", "jpg")).lower().lstrip(".")
    jpeg_quality = int(export_cfg.get("jpeg_quality", 92))

    work_id = session_work_id(blanks)
    if not work_id:
        return {"ok": False, "message": "work_id не найден в QR бланков"}

    if not auditorium_result.get("ok"):
        return {"ok": False, "message": "Сначала постройте цепочки бланков"}

    plan = build_export_plan(blanks, auditorium_result, image_format)
    if not plan:
        return {"ok": False, "message": "Нет бланков с готовыми именами для экспорта"}

    blank_by_uid = {b.uid: b for b in blanks}
    saved = 0

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in plan:
            blank = blank_by_uid.get(item["blank_uid"])
            if blank is None or blank.image is None:
                continue
            img = blank.image.convert("RGB")
            buf = io.BytesIO()
            if image_format in ("jpg", "jpeg"):
                img.save(buf, format="JPEG", quality=jpeg_quality)
            elif image_format == "png":
                img.save(buf, format="PNG")
            else:
                img.save(buf, format=image_format.upper())
            zf.writestr(item["filename"], buf.getvalue())
            saved += 1

        meta = {
            "work_id": work_id,
            "files": [p["filename"] for p in plan],
            "links": auditorium_result.get("links", {}),
            "renames": auditorium_result.get("renames", {}),
        }
        zf.writestr("manifest.json", json.dumps(meta, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "work_id": work_id,
        "saved": saved,
        "path": str(output_path),
        "plan": plan,
    }


def normalize_operator_number(text: str, expected_len: int = 13) -> Optional[str]:
    digits = re.sub(r"\D", "", text.strip())
    if len(digits) != expected_len:
        return None
    return digits


def needs_operator_attention(result: Optional[Mapping[str, Any]]) -> bool:
    if not result or not result.get("ok"):
        return False
    status = str(result.get("auditorium_status", ""))
    if status == AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED:
        return True
    if result.get("review_required"):
        return True
    if str(result.get("final_status", "")) == FINAL_STATUS_WAITING_OPERATOR:
        return True
    return bool(pending_operator_reviews(result))


_FOREIGN_REASON_MARKERS = (
    "foreign",
    "not_issued_to_auditorium",
    "foreign_blank_reference",
    "foreign_or_hijacked",
    "hijacked",
)


def detect_diversion(result: Optional[Mapping[str, Any]]) -> tuple[bool, List[str]]:
    """Обнаружена «диверсия» — чужой бланк / подмена номера."""
    if not result or not result.get("ok"):
        return False, []

    details: List[str] = []
    seen: set[str] = set()

    for item in list(result.get("suspicious", [])) + list(result.get("warnings", [])):
        reason = str(item.get("reason", ""))
        is_foreign = bool(item.get("foreign")) or any(m in reason for m in _FOREIGN_REASON_MARKERS)
        if not is_foreign:
            continue
        number = str(item.get("number", item.get("qr", "")))
        line = f"Бланк {number}: {reason}" if number else reason
        if line not in seen:
            seen.add(line)
            details.append(line)

    return bool(details), details


def is_export_ready(
    result: Optional[Mapping[str, Any]],
    blanks: Sequence["ScannedBlank"],
    config: Mapping[str, Any],
) -> bool:
    """Все связи готовы — можно экспортировать ZIP."""
    if not result or not result.get("ok"):
        return False
    if detect_diversion(result)[0]:
        return False
    if needs_operator_attention(result):
        return False
    if corrupted_blanks(blanks):
        return False

    status = str(result.get("auditorium_status", ""))
    if status not in {
        AUDITORIUM_STATUS_CLEAN,
        AUDITORIUM_STATUS_AUTO_FIXED,
        AUDITORIUM_STATUS_FINALIZED,
    }:
        return False

    if not result.get("links"):
        return False

    export_cfg = config.get("export", {})
    image_format = str(export_cfg.get("image_format", "jpg"))
    if not build_export_plan(blanks, result, image_format):
        return False

    return session_work_id(blanks) is not None
