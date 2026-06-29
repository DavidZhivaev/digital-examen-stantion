from __future__ import annotations

from typing import Callable, List, Optional

import numpy as np
from PIL import Image

from scan_logger import get_logger, log_exception

log = get_logger("hal")

try:
    import scanner_hal as _hal
    HAL_AVAILABLE = True
    log.info("scanner_hal module loaded successfully - HAL_AVAILABLE=True")
except ImportError as e:
    HAL_AVAILABLE = False
    log.warning(f"scanner_hal module NOT available: {e}")
    log.warning("Falling back to WIA/SANE. To use HAL, compile scanner_module/")


class HardwareScanner:
    def __init__(self):
        log.info("HardwareScanner.__init__() called")
        if not HAL_AVAILABLE:
            log.error("scanner_hal module not available!")
            raise RuntimeError("scanner_hal module not available")
        self._scanner = _hal.Scanner()
        self._connected = False
        log.info("HardwareScanner initialized successfully")

    def list_devices(self) -> List[str]:
        log.info("list_devices() called")
        devices = self._scanner.list_scanners()
        log.info(f"Found {len(devices)} devices: {devices}")
        return devices

    def connect(self, device_id: str) -> bool:
        log.info(f"connect(device_id={device_id}) called")
        self._connected = self._scanner.connect(device_id)
        log.info(f"Connection result: {self._connected}")
        return self._connected

    def disconnect(self) -> None:
        log.info("disconnect() called")
        self._scanner.disconnect()
        self._connected = False
        log.info("Disconnected")

    def scan_page(self) -> Optional[Image.Image]:
        log.info("scan_page() called")
        arr = self._scanner.scan_page()
        log.debug(f"scan_page returned array: shape={arr.shape if arr.size > 0 else 'empty'}, size={arr.size}")
        if arr.size == 0:
            log.warning("scan_page returned empty array")
            return None
        img = Image.fromarray(arr)
        log.info(f"scan_page success: {img.size}")
        return img

    def scan_batch(
        self,
        on_page: Optional[Callable[[Image.Image, int], None]] = None,
    ) -> List[Image.Image]:
        log.info("=" * 50)
        log.info("scan_batch() START")
        try:
            arrays = self._scanner.scan_batch()
            log.info(f"scan_batch returned {len(arrays)} arrays")
            images = []
            for i, arr in enumerate(arrays):
                log.debug(f"Processing array {i}: shape={arr.shape}, dtype={arr.dtype}")
                img = Image.fromarray(arr)
                images.append(img)
                log.info(f"Page {i+1}: size={img.size}, mode={img.mode}")
                if on_page:
                    on_page(img, i)
            log.info(f"scan_batch() COMPLETE: {len(images)} images")
            log.info("=" * 50)
            return images
        except Exception as e:
            log_exception(log, e, "scan_batch")
            raise
