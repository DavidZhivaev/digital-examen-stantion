"""Scanner support for Linux using SANE (Scanner Access Now Easy)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

if sys.platform == "win32":
    raise RuntimeError("scanner_sane is for Linux/Unix only")

try:
    import sane
    SANE_AVAILABLE = True
except ImportError:
    SANE_AVAILABLE = False


class SaneNotAvailableError(RuntimeError):
    pass


class DuplexNotSupportedError(RuntimeError):
    """Scanner does not support duplex scanning."""


@dataclass
class ScannerInfo:
    device_id: str
    name: str
    vendor: str = ""
    model: str = ""
    scanner_type: str = ""

    def connect(self):
        if not SANE_AVAILABLE:
            raise SaneNotAvailableError("python-sane not installed")
        return sane.open(self.device_id)


_sane_initialized = False


def _ensure_sane() -> None:
    global _sane_initialized
    if _sane_initialized:
        return
    if not SANE_AVAILABLE:
        raise SaneNotAvailableError("python-sane not installed. Install with: pip install python-sane")
    sane.init()
    _sane_initialized = True


def find_scanners() -> List[ScannerInfo]:
    """Return list of available SANE scanners."""
    if not SANE_AVAILABLE:
        return []

    try:
        _ensure_sane()
        devices = sane.get_devices()
        scanners = []
        for dev in devices:
            device_id, vendor, model, dev_type = dev
            name = f"{vendor} {model}".strip() or device_id
            scanners.append(ScannerInfo(
                device_id=device_id,
                name=name,
                vendor=vendor,
                model=model,
                scanner_type=dev_type,
            ))
        return scanners
    except Exception:
        return []


def get_scanner_capabilities(scanner: ScannerInfo) -> dict:
    """Return scanner capabilities."""
    caps = {
        "duplex": False,
        "feeder": False,
        "flatbed": True,
        "capacity_raw": 0,
    }

    if not SANE_AVAILABLE:
        return caps

    try:
        _ensure_sane()
        device = sane.open(scanner.device_id)
        options = device.get_options()

        for opt in options:
            if opt and len(opt) > 1:
                opt_name = opt[1] if len(opt) > 1 else ""
                if "duplex" in str(opt_name).lower():
                    caps["duplex"] = True
                if "adf" in str(opt_name).lower() or "feeder" in str(opt_name).lower():
                    caps["feeder"] = True

        device.close()
    except Exception:
        pass

    return caps


def format_scanner_label(scanner: ScannerInfo) -> str:
    """Format scanner name with capabilities."""
    caps = get_scanner_capabilities(scanner)
    parts = [scanner.name]
    if caps.get("duplex"):
        parts.append("duplex")
    if caps.get("feeder"):
        parts.append("ADF")
    if caps.get("flatbed"):
        parts.append("flatbed")
    return " · ".join(parts)


def scan_image_system_dialog() -> Image.Image:
    """Scan using system dialog - not available on Linux."""
    raise NotImplementedError("System dialog scanning not available on Linux. Use scan_image() directly.")


def scan_image(
    scanner: ScannerInfo,
    dpi: int = 300,
    color_mode: str = "grayscale",
) -> Image.Image:
    """Scan a single page and return PIL Image."""
    images = scan_sheet_sides(
        scanner, dpi=dpi, color_mode=color_mode, duplex=False, max_sides=1
    )
    if not images:
        raise RuntimeError("Scan returned no image.")
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
    """Scan one or more pages."""
    if not SANE_AVAILABLE:
        raise SaneNotAvailableError("python-sane not installed")

    _ensure_sane()

    try:
        device = sane.open(scanner.device_id)
    except Exception as e:
        raise RuntimeError(f"Failed to open scanner: {e}")

    try:
        # Set resolution
        try:
            device.resolution = dpi
        except AttributeError:
            pass

        # Set color mode
        try:
            if color_mode == "grayscale":
                device.mode = "Gray"
            elif color_mode == "color":
                device.mode = "Color"
            else:
                device.mode = "Lineart"
        except AttributeError:
            pass

        # Set duplex if supported
        if duplex:
            caps = get_scanner_capabilities(scanner)
            if require_duplex and not caps.get("duplex"):
                raise DuplexNotSupportedError("Scanner does not support duplex scanning.")
            try:
                device.source = "ADF Duplex"
            except (AttributeError, sane.error):
                if require_duplex:
                    raise DuplexNotSupportedError("Failed to enable duplex mode.")

        images: List[Image.Image] = []
        sides_to_scan = max(1, max_sides) if duplex else 1

        for side in range(sides_to_scan):
            try:
                device.start()
                img = device.snap()
                if img:
                    images.append(img.convert("RGB"))
            except Exception as e:
                if side == 0:
                    raise RuntimeError(f"Scan error: {e}")
                break

        return images

    finally:
        device.close()


def is_sane_available() -> bool:
    """Check if SANE is available."""
    return SANE_AVAILABLE
