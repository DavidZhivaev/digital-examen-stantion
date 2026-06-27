from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from main import ScannedBlank

try:
    import output_generator_cpp as _cpp
    CPP_AVAILABLE = True
except ImportError:
    CPP_AVAILABLE = False


class SheetType(IntEnum):
    UNKNOWN = 0
    TITUL = 1
    BLAN1 = 2
    BLAN2 = 3
    ADDITIONAL = 4


class ResultStatus(IntEnum):
    SUCCESS = 0
    ERROR_NO_SHEETS = 1
    ERROR_NO_BARCODE = 2
    ERROR_PDF_CREATION = 3
    ERROR_ZIP_CREATION = 4
    ERROR_FILE_WRITE = 5
    ERROR_INVALID_INPUT = 6


@dataclass
class PackageResult:
    ok: bool
    status: ResultStatus
    zip_path: str
    pdf_filename: str
    work_id: str
    title_barcode: int
    sheet_count: int
    chain_valid: bool

    @classmethod
    def from_dict(cls, d: Dict) -> "PackageResult":
        return cls(
            ok=d.get("ok", False),
            status=ResultStatus(d.get("status", 0)),
            zip_path=d.get("zip_path", ""),
            pdf_filename=d.get("pdf_filename", ""),
            work_id=d.get("work_id", ""),
            title_barcode=d.get("title_barcode", 0),
            sheet_count=d.get("sheet_count", 0),
            chain_valid=d.get("chain_valid", True),
        )


def _type_code_to_enum(type_code: str) -> int:
    mapping = {
        "titul": SheetType.TITUL,
        "blan1": SheetType.BLAN1,
        "blan2": SheetType.BLAN2,
    }
    return mapping.get(type_code, SheetType.UNKNOWN)


def _resolve_blank_id(blank: "ScannedBlank") -> Optional[int]:
    if hasattr(blank, "operator_blank_id") and blank.operator_blank_id:
        return int(blank.operator_blank_id)
    if blank.qr_info and blank.qr_info.valid and blank.qr_info.blank_id:
        return int(blank.qr_info.blank_id)
    if hasattr(blank, "barcode_id") and blank.barcode_id:
        return int(blank.barcode_id)
    return None


def _get_work_id(blanks: Sequence["ScannedBlank"]) -> Optional[str]:
    for blank in blanks:
        if blank.qr_info and blank.qr_info.valid and blank.qr_info.work_id:
            return blank.qr_info.work_id
    return None


def _get_title_barcode(blanks: Sequence["ScannedBlank"]) -> Optional[int]:
    for blank in blanks:
        if blank.qr_info and blank.qr_info.type_code == "titul":
            bc = _resolve_blank_id(blank)
            if bc:
                return bc
    if blanks:
        return _resolve_blank_id(blanks[0])
    return None


def _save_temp_image(blank: "ScannedBlank", temp_dir: Path, index: int) -> Optional[str]:
    if blank.image is None:
        return None
    path = temp_dir / f"sheet_{index:04d}.jpg"
    blank.image.convert("RGB").save(str(path), "JPEG", quality=92)
    return str(path)


class OutputGenerator:
    def __init__(self, output_dir: str):
        self._output_dir = output_dir
        if CPP_AVAILABLE:
            self._cpp_generator = _cpp.OutputGenerator(output_dir)
        else:
            self._cpp_generator = None

    def create_package(
        self,
        blanks: Sequence["ScannedBlank"],
        work_id: Optional[str] = None,
        title_barcode: Optional[int] = None,
        chain_valid: bool = True,
        temp_dir: Optional[Path] = None,
    ) -> PackageResult:
        if not CPP_AVAILABLE:
            return PackageResult(
                ok=False,
                status=ResultStatus.ERROR_INVALID_INPUT,
                zip_path="",
                pdf_filename="",
                work_id="",
                title_barcode=0,
                sheet_count=0,
                chain_valid=False,
            )

        if work_id is None:
            work_id = _get_work_id(blanks)
        if work_id is None:
            from uuid import uuid4
            work_id = str(uuid4())

        if title_barcode is None:
            title_barcode = _get_title_barcode(blanks)
        if title_barcode is None:
            title_barcode = 0

        if temp_dir is None:
            import tempfile
            temp_dir = Path(tempfile.mkdtemp())

        sheets: List[Tuple[str, int, int]] = []
        for i, blank in enumerate(blanks):
            path = _save_temp_image(blank, temp_dir, i)
            if path is None:
                continue
            barcode = _resolve_blank_id(blank) or 0
            type_code = ""
            if blank.qr_info and blank.qr_info.type_code:
                type_code = blank.qr_info.type_code
            type_int = _type_code_to_enum(type_code)
            sheets.append((path, barcode, type_int))

        result_dict = self._cpp_generator.create_package(
            work_id,
            title_barcode,
            sheets,
            chain_valid,
        )

        return PackageResult.from_dict(result_dict)


def create_work_package(
    blanks: Sequence["ScannedBlank"],
    output_dir: str,
    work_id: Optional[str] = None,
    title_barcode: Optional[int] = None,
    chain_valid: bool = True,
) -> PackageResult:
    generator = OutputGenerator(output_dir)
    return generator.create_package(
        blanks,
        work_id=work_id,
        title_barcode=title_barcode,
        chain_valid=chain_valid,
    )
