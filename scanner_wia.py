"""Обнаружение и сканирование через WIA (Windows Image Acquisition)."""

from __future__ import annotations

import io
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional

if sys.platform != "win32":
    raise RuntimeError("Станция сканирования поддерживает только Windows.")

import pythoncom
import win32com.client
from PIL import Image

WIA_DEVICE_TYPE_SCANNER = 1

WIA_INTENT_IMAGE_TYPE_COLOR = 1
WIA_INTENT_IMAGE_TYPE_GRAYSCALE = 2
WIA_INTENT_IMAGE_TYPE_TEXT = 4

WIA_IPS_CUR_INTENT = 6146
WIA_IPS_XRES = 6147
WIA_IPS_YRES = 6148
WIA_IPS_PAGE_SIZE = 3097
WIA_IPS_ORIENTATION = 3098
WIA_IPS_PAGES = 3096

WIA_DPS_DOCUMENT_HANDLING_CAPACITY = 3086
WIA_DPS_DOCUMENT_HANDLING_SELECT = 3088

WIA_FEEDER = 0x001
WIA_FLATBED = 0x002
WIA_DUPLEX = 0x004

WIA_PAGE_A4 = 4
WIA_PAGE_AUTO = 100
WIA_ORIENTATION_PORTRAIT = 0

COLOR_MODE_MAP = {
    "color": WIA_INTENT_IMAGE_TYPE_COLOR,
    "grayscale": WIA_INTENT_IMAGE_TYPE_GRAYSCALE,
    "text": WIA_INTENT_IMAGE_TYPE_TEXT,
}

_thread_local = threading.local()


class DuplexNotSupportedError(RuntimeError):
    """Сканер не поддерживает двустороннее сканирование."""

def _ensure_com() -> None:
    if getattr(_thread_local, "initialized", False):
        return
    pythoncom.CoInitialize()
    _thread_local.initialized = True


@dataclass
class ScannerInfo:
    device_id: str
    name: str
    _device_info: object = None

    def connect(self):
        return self._device_info.Connect()


def _get_property(obj, prop_id: int, default=None):
    try:
        return obj.Properties(prop_id).Value
    except Exception:
        return default


def scan_image_system_dialog():
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()

    try:
        dialog = win32com.client.Dispatch(
            "WIA.CommonDialog"
        )

        result = dialog.ShowAcquireImage(
            WIA_DEVICE_TYPE_SCANNER,
            WIA_INTENT_IMAGE_TYPE_GRAYSCALE,
            0,
            "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}",
            False,
            True,
            False,
        )

        return _transfer_to_image(result)

    finally:
        pythoncom.CoUninitialize()


def _get_named_property(obj, name: str, default=None):
    try:
        return obj.Properties(name).Value
    except Exception:
        return default


def _has_property(obj, prop_id: Optional[int] = None, name: Optional[str] = None) -> bool:
    try:
        if name is not None:
            obj.Properties(name)
            return True
        if prop_id is not None:
            obj.Properties(prop_id)
            return True
    except Exception:
        return False
    return False


def _set_property(obj, prop_id: int, value) -> bool:
    try:
        obj.Properties(prop_id).Value = value
        return True
    except Exception:
        return False


def _set_named_property(obj, name: str, value) -> bool:
    try:
        obj.Properties(name).Value = value
        return True
    except Exception:
        return False


def _try_set(obj, value, prop_id: Optional[int] = None, name: Optional[str] = None) -> bool:
    if name and _has_property(obj, name=name):
        return _set_named_property(obj, name, value)
    if prop_id is not None and _has_property(obj, prop_id=prop_id):
        return _set_property(obj, prop_id, value)
    return False


def find_scanners() -> List[ScannerInfo]:
    """Возвращает список реально подключённых сканеров WIA."""
    _ensure_com()
    manager = win32com.client.Dispatch("WIA.DeviceManager")
    scanners: List[ScannerInfo] = []
    for i in range(1, manager.DeviceInfos.Count + 1):
        info = manager.DeviceInfos.Item(i)
        if info.Type != WIA_DEVICE_TYPE_SCANNER:
            continue
        name = _get_named_property(info, "Name") or _get_property(info, "Name", f"Сканер {i}")
        device_id = _get_named_property(info, "Device ID") or _get_property(info, "DeviceID", str(i))
        scanners.append(ScannerInfo(device_id=device_id, name=str(name), _device_info=info))
    return scanners


def _get_scan_item(device):
    """Выбирает элемент сканирования (планшет/АПД)."""
    if device.Items.Count < 1:
        raise RuntimeError("На сканере не найдено ни одного элемента для сканирования.")

    preferred = ("flatbed", "планшет", "feeder", "адф", "document")
    for i in range(1, device.Items.Count + 1):
        item = device.Items[i]
        label = str(_get_named_property(item, "Item Name", "") or "").lower()
        category = str(_get_named_property(item, "Item Category", "") or "").lower()
        if any(token in label or token in category for token in preferred):
            return item
    return device.Items.Item(1)


def get_scanner_capabilities(scanner: ScannerInfo) -> dict:
    """Возвращает возможности сканера: duplex, ADF, планшет."""
    _ensure_com()
    device = scanner.connect()
    item = _get_scan_item(device)

    capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
    if not capacity:
        capacity = _get_property(device, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
    if not capacity:
        capacity = int(_get_named_property(item, "Document Handling Capabilities", 0) or 0)

    return {
        "duplex": bool(capacity & WIA_DUPLEX),
        "feeder": bool(capacity & WIA_FEEDER),
        "flatbed": bool(capacity & WIA_FLATBED),
        "capacity_raw": int(capacity),
    }


def format_scanner_label(scanner: ScannerInfo) -> str:
    caps = get_scanner_capabilities(scanner)
    parts = [scanner.name]
    if caps.get("duplex"):
        parts.append("дуплекс")
    if caps.get("feeder"):
        parts.append("АПД")
    if caps.get("flatbed"):
        parts.append("планшет")
    return " · ".join(parts)


def _transfer_to_image(result) -> Image.Image:
    if result is None:
        raise RuntimeError("Сканирование не вернуло изображение.")

    if not getattr(result, "FileData", None):
        raise RuntimeError("Сканирование вернуло пустые данные.")

    raw = bytes(result.FileData)
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image.convert("RGB")


def _configure_document_handling(item, duplex: bool) -> bool:
    if not duplex:
        capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
        if capacity & WIA_FLATBED:
            select = WIA_FLATBED
        elif capacity & WIA_FEEDER:
            select = WIA_FEEDER
        else:
            return True
        return _try_set(item, select, prop_id=WIA_DPS_DOCUMENT_HANDLING_SELECT, name="Document Handling Select")

    capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
    if not capacity:
        capacity = int(_get_named_property(item, "Document Handling Capabilities", 0) or 0)
    if not (capacity & WIA_DUPLEX):
        return False

    if capacity & WIA_FEEDER:
        select = WIA_FEEDER | WIA_DUPLEX
    elif capacity & WIA_FLATBED:
        select = WIA_FLATBED | WIA_DUPLEX
    else:
        select = WIA_DUPLEX

    if not _try_set(item, select, prop_id=WIA_DPS_DOCUMENT_HANDLING_SELECT, name="Document Handling Select"):
        return False

    _try_set(item, 2, prop_id=WIA_IPS_PAGES, name="Pages")
    return True


def _configure_scan_item(
    item,
    dpi: int,
    color_mode: str,
    duplex: bool,
    *,
    page_size: str = "a4",
    auto_border: bool = True,
) -> bool:
    intent = COLOR_MODE_MAP.get(color_mode.lower(), WIA_INTENT_IMAGE_TYPE_GRAYSCALE)

    _try_set(item, intent, prop_id=WIA_IPS_CUR_INTENT, name="Current Intent")
    _try_set(item, dpi, prop_id=WIA_IPS_XRES, name="Horizontal Resolution")
    _try_set(item, dpi, prop_id=WIA_IPS_YRES, name="Vertical Resolution")
    _try_set(item, WIA_ORIENTATION_PORTRAIT, prop_id=WIA_IPS_ORIENTATION, name="Orientation")

    if page_size.lower() == "a4":
        _try_set(item, WIA_PAGE_A4, prop_id=WIA_IPS_PAGE_SIZE, name="Page Size")

    if auto_border:
        _try_set(item, 1, name="Auto-Crop")
        _try_set(item, 1, name="Auto Deskew")

    return _configure_document_handling(item, duplex=duplex)


def scan_image(
    scanner: ScannerInfo,
    dpi: int = 300,
    color_mode: str = "grayscale",
) -> Image.Image:
    """Сканирует одну сторону и возвращает PIL Image."""
    images = scan_sheet_sides(
        scanner, dpi=dpi, color_mode=color_mode, duplex=False, max_sides=1
    )
    if not images:
        raise RuntimeError("Сканирование не вернуло изображение.")
    return images[0]


def scan_sheet_sides(
    scanner: ScannerInfo,
    dpi: int = 300,
    color_mode: str = "grayscale",
    duplex: bool = True,
    max_sides: int = 2,
    *,
    page_size: str = "a4",
    auto_border: bool = True,
    require_duplex: bool = True,
) -> List[Image.Image]:
    """
    Сканирует лист А4 в ч/б. При duplex=True получает лицо и оборот.
    """
    _ensure_com()
    device = scanner.connect()
    item = _get_scan_item(device)

    caps = get_scanner_capabilities(scanner)
    if duplex and require_duplex and not caps.get("duplex"):
        raise DuplexNotSupportedError(
            "Двустороннее сканирование доступно только на сканерах с поддержкой дуплекса."
        )

    duplex_enabled = _configure_scan_item(
        item,
        dpi=dpi,
        color_mode=color_mode,
        duplex=duplex,
        page_size=page_size,
        auto_border=auto_border,
    )

    if duplex and not duplex_enabled:
        raise DuplexNotSupportedError(
            "Не удалось включить двусторонний режим на выбранном сканере."
        )

    images: List[Image.Image] = []
    errors: List[str] = []
    sides_to_scan = max(1, max_sides) if duplex else 1

    for side in range(sides_to_scan):
        try:
            result = item.Transfer()
            images.append(_transfer_to_image(result))
        except Exception as exc:
            err = str(exc)
            errors.append(err)
            if side == 0:
                raise RuntimeError(f"Ошибка сканирования: {err}") from exc
            break

    if not images and errors:
        raise RuntimeError(errors[0])

    return images
