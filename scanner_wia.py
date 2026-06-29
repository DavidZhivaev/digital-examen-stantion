"""Обнаружение и сканирование через WIA (Windows Image Acquisition)."""

from __future__ import annotations

import io
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

from scan_logger import get_logger, log_exception

log = get_logger("wia")

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import pythoncom
    import win32com.client
else:
    pythoncom = None
    win32com = None

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
    if not IS_WINDOWS:
        return
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
    if not IS_WINDOWS:
        raise RuntimeError("WIA system dialog is only available on Windows.")

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
    log.info("find_scanners() called")
    if not IS_WINDOWS:
        log.warning("Not Windows, returning empty list")
        return []
    _ensure_com()
    log.debug("COM initialized, creating DeviceManager")
    manager = win32com.client.Dispatch("WIA.DeviceManager")
    scanners: List[ScannerInfo] = []
    device_count = manager.DeviceInfos.Count
    log.debug(f"Found {device_count} WIA devices")
    for i in range(1, device_count + 1):
        info = manager.DeviceInfos.Item(i)
        log.debug(f"Device {i}: Type={info.Type}")
        if info.Type != WIA_DEVICE_TYPE_SCANNER:
            continue
        name = _get_named_property(info, "Name") or _get_property(info, "Name", f"Сканер {i}")
        device_id = _get_named_property(info, "Device ID") or _get_property(info, "DeviceID", str(i))
        log.info(f"Found scanner: {name} (ID: {device_id})")
        scanners.append(ScannerInfo(device_id=device_id, name=str(name), _device_info=info))
    log.info(f"Total scanners found: {len(scanners)}")
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
    log.info(f"get_scanner_capabilities() for {scanner.name}")
    if not IS_WINDOWS:
        log.warning("Not Windows, returning empty capabilities")
        return {"duplex": False, "feeder": False, "flatbed": False, "capacity_raw": 0}
    _ensure_com()
    log.debug("Connecting to device...")
    device = scanner.connect()
    log.debug("Getting scan item...")
    item = _get_scan_item(device)

    capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
    log.debug(f"Capacity from item: {capacity}")
    if not capacity:
        capacity = _get_property(device, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
        log.debug(f"Capacity from device: {capacity}")
    if not capacity:
        capacity = int(_get_named_property(item, "Document Handling Capabilities", 0) or 0)
        log.debug(f"Capacity from named property: {capacity}")

    caps = {
        "duplex": bool(capacity & WIA_DUPLEX),
        "feeder": bool(capacity & WIA_FEEDER),
        "flatbed": bool(capacity & WIA_FLATBED),
        "capacity_raw": int(capacity),
    }
    log.info(f"Scanner capabilities: duplex={caps['duplex']}, feeder={caps['feeder']}, flatbed={caps['flatbed']}, raw={capacity}")
    return caps


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
    log.debug(f"_transfer_to_image(result={type(result)})")

    if result is None:
        log.error("Transfer result is None!")
        raise RuntimeError("Сканирование не вернуло изображение.")

    file_data = getattr(result, "FileData", None)
    log.debug(f"FileData present: {file_data is not None}")

    if not file_data:
        log.error("Transfer result has no FileData!")
        raise RuntimeError("Сканирование вернуло пустые данные.")

    raw = bytes(file_data)
    log.debug(f"Raw data size: {len(raw)} bytes")

    image = Image.open(io.BytesIO(raw))
    image.load()
    log.debug(f"Image loaded: size={image.size}, mode={image.mode}")

    rgb_image = image.convert("RGB")
    log.debug(f"Converted to RGB: size={rgb_image.size}")
    return rgb_image


def _configure_document_handling(item, duplex: bool) -> bool:
    log.debug(f"_configure_document_handling(duplex={duplex})")

    if not duplex:
        capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
        log.debug(f"Non-duplex mode, capacity={capacity}")
        if capacity & WIA_FLATBED:
            select = WIA_FLATBED
            log.debug("Using FLATBED")
        elif capacity & WIA_FEEDER:
            select = WIA_FEEDER
            log.debug("Using FEEDER")
        else:
            log.debug("No specific handling, returning True")
            return True
        result = _try_set(item, select, prop_id=WIA_DPS_DOCUMENT_HANDLING_SELECT, name="Document Handling Select")
        log.debug(f"Set document handling select: {result}")
        return result

    capacity = _get_property(item, WIA_DPS_DOCUMENT_HANDLING_CAPACITY, 0) or 0
    log.debug(f"Duplex mode, initial capacity={capacity}")
    if not capacity:
        capacity = int(_get_named_property(item, "Document Handling Capabilities", 0) or 0)
        log.debug(f"Capacity from named property={capacity}")
    if not (capacity & WIA_DUPLEX):
        log.warning("Duplex not supported in capacity flags")
        return False

    if capacity & WIA_FEEDER:
        select = WIA_FEEDER | WIA_DUPLEX
        log.debug(f"Using FEEDER + DUPLEX (select={select})")
    elif capacity & WIA_FLATBED:
        select = WIA_FLATBED | WIA_DUPLEX
        log.debug(f"Using FLATBED + DUPLEX (select={select})")
    else:
        select = WIA_DUPLEX
        log.debug(f"Using DUPLEX only (select={select})")

    if not _try_set(item, select, prop_id=WIA_DPS_DOCUMENT_HANDLING_SELECT, name="Document Handling Select"):
        log.warning("Failed to set document handling select")
        return False

    pages_result = _try_set(item, 2, prop_id=WIA_IPS_PAGES, name="Pages")
    log.debug(f"Set Pages to 2: {pages_result}")
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
    log.debug(f"_configure_scan_item(dpi={dpi}, color_mode={color_mode}, duplex={duplex})")
    intent = COLOR_MODE_MAP.get(color_mode.lower(), WIA_INTENT_IMAGE_TYPE_GRAYSCALE)
    log.debug(f"Color intent: {intent}")

    r1 = _try_set(item, intent, prop_id=WIA_IPS_CUR_INTENT, name="Current Intent")
    log.debug(f"Set Current Intent: {r1}")
    r2 = _try_set(item, dpi, prop_id=WIA_IPS_XRES, name="Horizontal Resolution")
    log.debug(f"Set Horizontal Resolution ({dpi}): {r2}")
    r3 = _try_set(item, dpi, prop_id=WIA_IPS_YRES, name="Vertical Resolution")
    log.debug(f"Set Vertical Resolution ({dpi}): {r3}")
    r4 = _try_set(item, WIA_ORIENTATION_PORTRAIT, prop_id=WIA_IPS_ORIENTATION, name="Orientation")
    log.debug(f"Set Orientation: {r4}")

    if page_size.lower() == "a4":
        r5 = _try_set(item, WIA_PAGE_A4, prop_id=WIA_IPS_PAGE_SIZE, name="Page Size")
        log.debug(f"Set Page Size (A4): {r5}")

    if auto_border:
        r6 = _try_set(item, 1, name="Auto-Crop")
        log.debug(f"Set Auto-Crop: {r6}")
        r7 = _try_set(item, 1, name="Auto Deskew")
        log.debug(f"Set Auto Deskew: {r7}")

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
    log.info("=" * 50)
    log.info("scan_sheet_sides() START")
    log.info(f"  scanner: {scanner.name}")
    log.info(f"  dpi: {dpi}, color_mode: {color_mode}")
    log.info(f"  duplex: {duplex}, max_sides: {max_sides}")
    log.info(f"  page_size: {page_size}, auto_border: {auto_border}")
    log.info(f"  require_duplex: {require_duplex}")

    if not IS_WINDOWS:
        log.error("Not Windows platform!")
        raise RuntimeError("WIA scanning is only available on Windows. Use SANE on Linux.")

    log.debug("Ensuring COM...")
    _ensure_com()

    log.debug("Connecting to scanner device...")
    device = scanner.connect()
    log.debug(f"Device connected: {device}")

    log.debug("Getting scan item...")
    item = _get_scan_item(device)
    log.debug(f"Scan item obtained: {item}")

    log.debug("Getting scanner capabilities...")
    caps = get_scanner_capabilities(scanner)
    if duplex and require_duplex and not caps.get("duplex"):
        log.error("Duplex required but not supported!")
        raise DuplexNotSupportedError(
            "Двустороннее сканирование доступно только на сканерах с поддержкой дуплекса."
        )

    log.debug("Configuring scan item...")
    duplex_enabled = _configure_scan_item(
        item,
        dpi=dpi,
        color_mode=color_mode,
        duplex=duplex,
        page_size=page_size,
        auto_border=auto_border,
    )
    log.debug(f"Duplex enabled result: {duplex_enabled}")

    if duplex and not duplex_enabled:
        log.error("Failed to enable duplex mode!")
        raise DuplexNotSupportedError(
            "Не удалось включить двусторонний режим на выбранном сканере."
        )

    images: List[Image.Image] = []
    errors: List[str] = []
    sides_to_scan = max(1, max_sides) if duplex else 1
    log.info(f"Will scan {sides_to_scan} side(s)")

    for side in range(sides_to_scan):
        log.info(f"--- Scanning side {side + 1}/{sides_to_scan} ---")
        try:
            log.debug("Calling item.Transfer()...")
            result = item.Transfer()
            log.debug(f"Transfer result type: {type(result)}")
            log.debug(f"Transfer result: {result}")

            log.debug("Converting to image...")
            img = _transfer_to_image(result)
            log.info(f"Side {side + 1} scanned successfully: {img.size}, mode={img.mode}")
            images.append(img)

        except Exception as exc:
            err = str(exc)
            log.error(f"Side {side + 1} scan error: {err}")
            log_exception(log, exc, f"Side {side + 1} scan")
            errors.append(err)
            if side == 0:
                log.error("First side failed, raising exception")
                raise RuntimeError(f"Ошибка сканирования: {err}") from exc
            log.warning("Non-first side failed, breaking loop")
            break

    if not images and errors:
        log.error(f"No images and errors: {errors}")
        raise RuntimeError(errors[0])

    log.info(f"scan_sheet_sides() COMPLETE: {len(images)} images, {len(errors)} errors")
    log.info("=" * 50)
    return images
