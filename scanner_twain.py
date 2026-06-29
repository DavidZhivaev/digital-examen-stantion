from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PIL import Image

from scan_logger import get_logger, log_exception

log = get_logger("twain")

from scanner_shm import (
    CMD_LIST,
    CMD_SCAN,
    CMD_STOP,
    CMD_NONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_IMAGE_READY,
    STATE_SCANNING,
    ERROR_NO_DEVICE,
    ERROR_PAPER_JAM,
    ERROR_COVER_OPEN,
    ERROR_TIMEOUT,
    ERROR_CANCELLED,
    SharedMemoryScanner,
    SHM_NAME,
)


class TwainError(Exception):
    pass


class TwainDeviceNotFoundError(TwainError):
    pass


class TwainPaperJamError(TwainError):
    pass


class TwainCoverOpenError(TwainError):
    pass


class TwainTimeoutError(TwainError):
    pass


class TwainCancelledError(TwainError):
    pass


class TwainNotAvailableError(TwainError):
    pass


ERROR_EXCEPTIONS = {
    ERROR_NO_DEVICE: TwainDeviceNotFoundError,
    ERROR_PAPER_JAM: TwainPaperJamError,
    ERROR_COVER_OPEN: TwainCoverOpenError,
    ERROR_TIMEOUT: TwainTimeoutError,
    ERROR_CANCELLED: TwainCancelledError,
}


@dataclass
class TwainScannerInfo:
    device_id: str
    name: str
    supports_duplex: bool = False
    supports_adf: bool = False


class TwainDriver:
    def __init__(self, exe_path: Path, shm_name: str = SHM_NAME):
        self._exe = exe_path
        self._shm_name = shm_name
        self._shm = SharedMemoryScanner(shm_name)
        self._process: Optional[subprocess.Popen] = None
        self._started = False

    @property
    def available(self) -> bool:
        return self._exe.exists()

    @property
    def running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def start(self, timeout: float = 5.0) -> bool:
        log.info(f"TwainDriver.start(timeout={timeout})")
        log.debug(f"  exe path: {self._exe}")
        log.debug(f"  available: {self.available}")

        if not self.available:
            log.warning("TWAIN driver exe not available")
            return False

        if self.running:
            log.info("Already running")
            return True

        log.debug("Creating shared memory...")
        self._shm.create()

        try:
            log.info(f"Starting TWAIN process: {self._exe}")
            self._process = subprocess.Popen(
                [str(self._exe), "--shm", self._shm_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            log.debug(f"Process started with PID: {self._process.pid}")
        except OSError as e:
            log.error(f"Failed to start process: {e}")
            self._shm.close()
            return False

        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if self._process.poll() is not None:
                log.error(f"Process exited early with code: {self._process.returncode}")
                self._shm.close()
                return False
            try:
                ctrl = self._shm.get_control()
                if ctrl.state == STATE_IDLE:
                    log.info("TWAIN driver started successfully (IDLE state)")
                    self._started = True
                    return True
            except Exception as e:
                log.debug(f"Waiting for IDLE state... ({e})")
            time.sleep(0.1)

        log.error(f"Timeout waiting for TWAIN driver to start ({timeout}s)")
        self.stop()
        return False

    def stop(self) -> None:
        if self._process is not None:
            try:
                self._shm.send_command(CMD_STOP)
                self._process.wait(timeout=3)
            except Exception:
                self._process.kill()
                self._process.wait()
            self._process = None

        self._shm.close()
        self._started = False

    def list_scanners(self, timeout: float = 10.0) -> List[TwainScannerInfo]:
        if not self.running:
            if not self.start():
                return []

        self._shm.send_command(CMD_LIST)

        try:
            self._shm.wait_state([STATE_IDLE], timeout=timeout)
        except TimeoutError:
            return []

        self._shm.acknowledge()
        return []

    def scan(
        self,
        device_id: str = "",
        dpi: int = 300,
        duplex: bool = True,
        color_mode: str = "grayscale",
        timeout_per_page: float = 60.0,
        on_page: Optional[Callable[[Image.Image, int], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> List[Image.Image]:
        log.info("=" * 50)
        log.info("TwainDriver.scan() START")
        log.info(f"  device_id: {device_id}")
        log.info(f"  dpi: {dpi}, duplex: {duplex}, color_mode: {color_mode}")

        if not self.running:
            log.info("Driver not running, attempting to start...")
            if not self.start():
                log.error("Failed to start TWAIN driver!")
                raise TwainNotAvailableError("TWAIN driver not available")

        channels = 1 if color_mode == "grayscale" else 3
        log.debug(f"Using {channels} channel(s)")

        log.debug("Sending CMD_SCAN command...")
        self._shm.send_command(
            CMD_SCAN,
            device_id=device_id,
            dpi=dpi,
            duplex=1 if duplex else 0,
            image_channels=channels,
        )

        images: List[Image.Image] = []

        while True:
            if on_progress:
                on_progress(f"Waiting for page {len(images) + 1}...")

            log.debug(f"Waiting for state (page {len(images) + 1})...")
            try:
                ctrl = self._shm.wait_state(
                    [STATE_IMAGE_READY, STATE_IDLE, STATE_ERROR],
                    timeout=timeout_per_page,
                )
                log.debug(f"Got state: {ctrl.state}")
            except TimeoutError:
                log.error("Scan timeout!")
                raise TwainTimeoutError("Scan timeout")

            if ctrl.state == STATE_ERROR:
                exc_class = ERROR_EXCEPTIONS.get(ctrl.error_code, TwainError)
                msg = ctrl.error_message.decode("utf-8", errors="replace")
                log.error(f"TWAIN error: code={ctrl.error_code}, msg={msg}")
                raise exc_class(msg or f"Error code {ctrl.error_code}")

            if ctrl.state == STATE_IDLE:
                log.info("Got IDLE state, scan loop complete")
                break

            if ctrl.state == STATE_IMAGE_READY:
                log.info(f"Image ready: index={ctrl.image_index}")
                img = self._shm.read_current_image()
                if img is not None:
                    log.info(f"Read image: size={img.size}, mode={img.mode}")
                    images.append(img)
                    if on_page:
                        on_page(img, ctrl.image_index)
                    if on_progress:
                        on_progress(f"Received page {ctrl.image_index + 1}")
                else:
                    log.warning("read_current_image returned None!")
                self._shm.acknowledge()

        log.info(f"TwainDriver.scan() COMPLETE: {len(images)} images")
        log.info("=" * 50)
        return images

    def cancel(self) -> None:
        if self.running:
            self._shm.send_command(CMD_STOP)


def find_twain_exe() -> Optional[Path]:
    log.debug("find_twain_exe() searching for TWAIN driver...")
    candidates = [
        Path(__file__).parent / "bin" / "twain_driver.exe",
        Path(__file__).parent / "twain_driver.exe",
        Path("C:/Program Files/TwainDriver/twain_driver.exe"),
    ]
    for path in candidates:
        log.debug(f"  Checking: {path}")
        if path.exists():
            log.info(f"Found TWAIN exe: {path}")
            return path
    log.warning("TWAIN exe not found in any candidate location")
    return None


_driver_instance: Optional[TwainDriver] = None


def get_twain_driver() -> Optional[TwainDriver]:
    global _driver_instance
    log.debug("get_twain_driver() called")
    if _driver_instance is not None:
        log.debug("Returning existing driver instance")
        return _driver_instance

    exe = find_twain_exe()
    if exe is None:
        log.warning("Cannot create TWAIN driver - exe not found")
        return None

    log.info(f"Creating new TwainDriver with exe: {exe}")
    _driver_instance = TwainDriver(exe)
    return _driver_instance


def is_twain_available() -> bool:
    driver = get_twain_driver()
    available = driver is not None and driver.available
    log.debug(f"is_twain_available(): {available}")
    return available
