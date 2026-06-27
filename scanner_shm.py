from __future__ import annotations

import mmap
import struct
import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from PIL import Image

SHM_NAME = "twain_scanner_shm"
SHM_SIZE = 50 * 1024 * 1024
CONTROL_BLOCK_SIZE = 4096
IMAGE_BUFFER_OFFSET = 4096

MAGIC = 0x5457414E
STATE_IDLE = 0
STATE_SCANNING = 1
STATE_IMAGE_READY = 2
STATE_ERROR = 3
CMD_NONE = 0
CMD_LIST = 1
CMD_SCAN = 2
CMD_STOP = 3

ERROR_NONE = 0
ERROR_NO_DEVICE = 1
ERROR_PAPER_JAM = 2
ERROR_COVER_OPEN = 3
ERROR_TIMEOUT = 4
ERROR_CANCELLED = 5


@dataclass
class ControlBlock:
    magic: int = MAGIC
    version: int = 1
    state: int = STATE_IDLE
    command: int = CMD_NONE
    image_offset: int = IMAGE_BUFFER_OFFSET
    image_size: int = 0
    image_width: int = 0
    image_height: int = 0
    image_channels: int = 1
    image_index: int = 0
    total_pages: int = 0
    error_code: int = 0
    dpi: int = 300
    duplex: int = 1
    device_id: bytes = b""
    error_message: bytes = b""

    STRUCT_FORMAT = "<IIIIIIIIIIIIII256s256s"
    STRUCT_SIZE = struct.calcsize(STRUCT_FORMAT)

    def pack(self) -> bytes:
        device_id = self.device_id[:255].ljust(256, b"\x00")
        error_msg = self.error_message[:255].ljust(256, b"\x00")
        return struct.pack(
            self.STRUCT_FORMAT,
            self.magic,
            self.version,
            self.state,
            self.command,
            self.image_offset,
            self.image_size,
            self.image_width,
            self.image_height,
            self.image_channels,
            self.image_index,
            self.total_pages,
            self.error_code,
            self.dpi,
            self.duplex,
            device_id,
            error_msg,
        )

    @classmethod
    def unpack(cls, data: bytes) -> ControlBlock:
        fields = struct.unpack(cls.STRUCT_FORMAT, data[: cls.STRUCT_SIZE])
        return cls(
            magic=fields[0],
            version=fields[1],
            state=fields[2],
            command=fields[3],
            image_offset=fields[4],
            image_size=fields[5],
            image_width=fields[6],
            image_height=fields[7],
            image_channels=fields[8],
            image_index=fields[9],
            total_pages=fields[10],
            error_code=fields[11],
            dpi=fields[12],
            duplex=fields[13],
            device_id=fields[14].rstrip(b"\x00"),
            error_message=fields[15].rstrip(b"\x00"),
        )


class SharedMemoryScanner:
    def __init__(self, shm_name: str = SHM_NAME, shm_size: int = SHM_SIZE):
        self._shm_name = shm_name
        self._shm_size = shm_size
        self._shm: Optional[mmap.mmap] = None
        self._owns_shm = False

    def create(self) -> None:
        self._shm = mmap.mmap(-1, self._shm_size, tagname=self._shm_name)
        self._owns_shm = True
        ctrl = ControlBlock()
        self._write_control(ctrl)

    def attach(self) -> bool:
        try:
            self._shm = mmap.mmap(-1, self._shm_size, tagname=self._shm_name)
            ctrl = self._read_control()
            return ctrl.magic == MAGIC
        except Exception:
            return False

    def close(self) -> None:
        if self._shm:
            self._shm.close()
            self._shm = None

    def _read_control(self) -> ControlBlock:
        self._shm.seek(0)
        data = self._shm.read(ControlBlock.STRUCT_SIZE)
        return ControlBlock.unpack(data)

    def _write_control(self, ctrl: ControlBlock) -> None:
        self._shm.seek(0)
        self._shm.write(ctrl.pack())

    def _read_image(self, ctrl: ControlBlock) -> Image.Image:
        self._shm.seek(ctrl.image_offset)
        raw = self._shm.read(ctrl.image_size)
        if ctrl.image_channels == 1:
            mode = "L"
            shape = (ctrl.image_height, ctrl.image_width)
        else:
            mode = "RGB"
            shape = (ctrl.image_height, ctrl.image_width, ctrl.image_channels)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(shape)
        return Image.fromarray(arr, mode=mode)

    def get_state(self) -> int:
        ctrl = self._read_control()
        return ctrl.state

    def get_control(self) -> ControlBlock:
        return self._read_control()

    def send_command(self, cmd: int, **kwargs) -> None:
        ctrl = self._read_control()
        ctrl.command = cmd
        for key, value in kwargs.items():
            if hasattr(ctrl, key):
                if isinstance(value, str):
                    value = value.encode("utf-8")
                setattr(ctrl, key, value)
        self._write_control(ctrl)

    def wait_state(
        self, target_states: List[int], timeout: float = 30.0, poll_interval: float = 0.01
    ) -> ControlBlock:
        start = time.monotonic()
        while True:
            ctrl = self._read_control()
            if ctrl.state in target_states:
                return ctrl
            if time.monotonic() - start > timeout:
                raise TimeoutError("Scanner state timeout")
            time.sleep(poll_interval)

    def acknowledge(self) -> None:
        ctrl = self._read_control()
        ctrl.command = CMD_NONE
        self._write_control(ctrl)

    def read_current_image(self) -> Optional[Image.Image]:
        ctrl = self._read_control()
        if ctrl.state != STATE_IMAGE_READY:
            return None
        if ctrl.image_size == 0:
            return None
        return self._read_image(ctrl)
