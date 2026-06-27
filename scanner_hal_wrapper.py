from __future__ import annotations

from typing import Callable, List, Optional

import numpy as np
from PIL import Image

try:
    import scanner_hal as _hal
    HAL_AVAILABLE = True
except ImportError:
    HAL_AVAILABLE = False


class HardwareScanner:
    def __init__(self):
        if not HAL_AVAILABLE:
            raise RuntimeError("scanner_hal module not available")
        self._scanner = _hal.Scanner()
        self._connected = False

    def list_devices(self) -> List[str]:
        return self._scanner.list_scanners()

    def connect(self, device_id: str) -> bool:
        self._connected = self._scanner.connect(device_id)
        return self._connected

    def disconnect(self) -> None:
        self._scanner.disconnect()
        self._connected = False

    def scan_page(self) -> Optional[Image.Image]:
        arr = self._scanner.scan_page()
        if arr.size == 0:
            return None
        return Image.fromarray(arr)

    def scan_batch(
        self,
        on_page: Optional[Callable[[Image.Image, int], None]] = None,
    ) -> List[Image.Image]:
        arrays = self._scanner.scan_batch()
        images = []
        for i, arr in enumerate(arrays):
            img = Image.fromarray(arr)
            images.append(img)
            if on_page:
                on_page(img, i)
        return images
