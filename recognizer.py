from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
from PIL import Image

from digit_inference import (
    IDX_TO_CLASS,
    Candidate,
    build_candidates,
    load_model,
    probs_to_output,
    set_seed,
    to_gray,
    _foreground_background_split,
)
from field_regions import FIELD_LAYOUT, cell_to_pixels


def _get_resource_path(relative_path: str) -> Path:
    """Get path to resource, works for dev and PyInstaller bundle."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent / relative_path


BASE_DIR = _get_resource_path(".")
WEIGHTS_PATH = _get_resource_path("digit_model.pth")

BLANK_ALPHABET = "0234567"
# Модель обучена только на TARGET_CLASSES = [0, 2, 3, 4, 5, 6, 7].
# Цифры 1, 8, 9 модели недоступны — они будут получать prob=0.0 при любом входе.
# Поэтому PAGE_ALPHABET ограничен теми же классами, что и BLANK_ALPHABET.
PAGE_ALPHABET = "0234567"
EMPTY_CELL_MIN_FOREGROUND = 25

_MODEL: Optional[torch.nn.Module] = None
_DEVICE: Optional[torch.device] = None
_RECOGNIZER: Optional["Recognizer"] = None


def _get_recognizer() -> "Recognizer":
    global _RECOGNIZER
    if _RECOGNIZER is None:
        _RECOGNIZER = Recognizer()
    return _RECOGNIZER


@dataclass
class CellRecognition:
    digit: str
    confidence: float
    is_empty: bool
    field_probs: Dict[str, float]
    image28: Optional[np.ndarray] = None
    preprocessing: str = ""


@dataclass
class RecognitionResult:
    success: bool = True
    confidence: Optional[float] = 1.0
    is_unreadable: bool = False
    is_damaged: bool = False
    is_empty: bool = False
    has_multiple_marks: bool = False
    special_reasons: List[str] = field(default_factory=list)
    veroytn: Optional[Union[Dict[str, Any], List[Dict[str, float]]]] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_special_case(self) -> bool:
        return bool(self.special_reasons) or any(
            (self.is_unreadable, self.is_damaged, self.is_empty, self.has_multiple_marks)
        )


def _ensure_model() -> tuple[torch.nn.Module, torch.device]:
    global _MODEL, _DEVICE
    if _MODEL is None:
        set_seed(42)
        _DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _MODEL = load_model(str(WEIGHTS_PATH), _DEVICE)
    return _MODEL, _DEVICE


def _uniform_probs(alphabet: str) -> Dict[str, float]:
    p = 1.0 / len(alphabet)
    return {ch: p for ch in alphabet}


def _is_empty_cell(rgb: np.ndarray) -> bool:
    if rgb.size == 0:
        return True
    gray = to_gray(rgb)
    _, _, mask = _foreground_background_split(gray)
    fg = int(np.count_nonzero(mask))
    h, w = gray.shape[:2]
    threshold = max(EMPTY_CELL_MIN_FOREGROUND, int(0.008 * h * w))
    return fg < threshold


def _digit_probs_to_field_dict(probs: torch.Tensor, alphabet: str) -> Dict[str, float]:
    _, _, all_probs = probs_to_output(probs)
    out = _uniform_probs(alphabet)
    for digit_str, prob in all_probs.items():
        if digit_str in out:
            out[digit_str] = float(prob)
    for ch in alphabet:
        if ch not in {str(d) for d in IDX_TO_CLASS.values()}:
            out[ch] = 0.0
    total = sum(out.values())
    if total > 0:
        out = {k: v / total for k, v in out.items()}
    return out


def _cells_to_field_probs(cells: List[CellRecognition]) -> List[Dict[str, float]]:
    return [c.field_probs for c in cells]


def _recognize_layout(
    rgb: np.ndarray,
    layout: Dict[str, List[tuple[float, float, float, float]]],
    model: torch.nn.Module,
    device: torch.device,
    crop_margin_ratio: float,
) -> tuple[Any, float, List[CellRecognition]]:
    field_keys: List[str] = []
    field_sizes: List[int] = []
    cell_meta: List[tuple[tuple[float, float, float, float], str]] = []

    for key, cells in layout.items():
        alphabet = PAGE_ALPHABET if key in ("page", "count") else BLANK_ALPHABET
        field_keys.append(key)
        field_sizes.append(len(cells))
        for cell in cells:
            cell_meta.append((cell, alphabet))

    if not cell_meta:
        return None, 0.0, []

    h, w = rgb.shape[:2]
    results_meta: List[Optional[CellRecognition]] = [None] * len(cell_meta)
    pending: List[Tuple[int, List[Candidate], str]] = []

    for idx, (cell, alphabet) in enumerate(cell_meta):
        x1, y1, x2, y2 = cell_to_pixels(cell, w, h, crop_margin_ratio=crop_margin_ratio)
        crop = rgb[y1:y2, x1:x2]
        if crop.size == 0 or _is_empty_cell(crop):
            results_meta[idx] = CellRecognition("", 0.0, True, _uniform_probs(alphabet))
            continue
        candidates, _, _, _ = build_candidates(crop)
        pending.append((idx, candidates, alphabet))

    if pending:
        flat: List[Candidate] = []
        spans: List[Tuple[int, int, int, str]] = []
        for cell_idx, candidates, alphabet in pending:
            start = len(flat)
            flat.extend(candidates)
            spans.append((cell_idx, start, len(flat), alphabet))

        batch = torch.cat([c.tensor for c in flat], dim=0).to(device)
        with torch.inference_mode():
            logits = model(batch)
            probs = torch.softmax(logits, dim=1)

        for i, cand in enumerate(flat):
            cand.probs = probs[i].detach().cpu()
            cand.confidence = float(cand.probs.max().item())

        for cell_idx, start, end, alphabet in spans:
            group = flat[start:end]
            best = max(group, key=lambda c: c.confidence)
            assert best.probs is not None
            predicted_digit, confidence, _ = probs_to_output(best.probs)
            results_meta[cell_idx] = CellRecognition(
                digit=str(predicted_digit),
                confidence=confidence,
                is_empty=False,
                field_probs=_digit_probs_to_field_dict(best.probs, alphabet),
                image28=best.image28.copy(),
                preprocessing=best.name,
            )

    final_cells = [
        r if r is not None else CellRecognition("", 0.0, True, _uniform_probs(BLANK_ALPHABET))
        for r in results_meta
    ]

    confidences = [c.confidence for c in final_cells if not c.is_empty]
    min_conf = min(confidences) if confidences else 0.0

    offset = 0
    veroytn: Dict[str, Any] = {}
    all_details: List[CellRecognition] = []
    for _key, size in zip(field_keys, field_sizes):
        chunk = final_cells[offset : offset + size]
        veroytn[_key] = _cells_to_field_probs(chunk)
        all_details.extend(chunk)
        offset += size

    return veroytn, min_conf, all_details


class Recognizer:
    def __init__(self, crop_margin_ratio: float = 0.35) -> None:
        self._crop_margin_ratio = crop_margin_ratio
        self._model, self._device = _ensure_model()

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        return np.asarray(image.convert("RGB"))

    def _recognize_fields(self, rgb: np.ndarray, blank_type: str) -> RecognitionResult:
        layout = FIELD_LAYOUT.get(blank_type)
        if layout is None:
            return RecognitionResult(success=False, confidence=0.0, veroytn=None)

        veroytn, confidence, cell_details = _recognize_layout(
            rgb, layout, self._model, self._device, self._crop_margin_ratio,
        )

        is_empty = confidence < 0.15 and all(c.is_empty for c in cell_details)

        return RecognitionResult(
            success=True,
            confidence=confidence,
            is_empty=is_empty,
            veroytn=veroytn,
            raw_data={
                "blank_type": blank_type,
                "cells": [
                    {
                        "digit": c.digit,
                        "confidence": round(c.confidence, 4),
                        "is_empty": c.is_empty,
                        "preprocessing": c.preprocessing,
                    }
                    for c in cell_details
                ],
            },
        )

    def recognize(self, image: Image.Image, blank_type: str = "") -> RecognitionResult:
        rgb = self._preprocess(image)
        if blank_type in FIELD_LAYOUT:
            return self._recognize_fields(rgb, blank_type)
        if blank_type == "provr":
            return RecognitionResult(success=True, confidence=None, veroytn=None)
        return RecognitionResult(success=False, confidence=0.0, veroytn=None)


def evaluate_special_case(
    result: RecognitionResult,
    config: Dict[str, Any],
) -> tuple[bool, List[str]]:
    rules = config.get("special_cases", {})
    labels = rules.get("custom_labels", {})
    reasons: List[str] = []

    threshold = float(rules.get("low_confidence_threshold", 0.65))
    if (
        rules.get("count_on_low_confidence", True)
        and result.confidence is not None
        and result.confidence < threshold
    ):
        reasons.append(labels.get("low_confidence", "Низкая уверенность"))

    if rules.get("count_on_unreadable", True) and result.is_unreadable:
        reasons.append(labels.get("unreadable", "Не читается"))

    if rules.get("count_on_damaged", True) and result.is_damaged:
        reasons.append(labels.get("damaged", "Повреждён"))

    if rules.get("count_on_empty", True) and result.is_empty:
        reasons.append(labels.get("empty", "Пустой бланк"))

    if rules.get("count_on_multiple_marks", False) and result.has_multiple_marks:
        reasons.append(labels.get("multiple_marks", "Несколько отметок"))

    if result.special_reasons:
        reasons.extend(result.special_reasons)

    seen: set[str] = set()
    unique: List[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return bool(unique), unique


def process_scanned_blank(img_numpy: Any, blank_type: str = "") -> str:
    arr = np.asarray(img_numpy)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return json.dumps({"success": False, "error": "Ожидается тензор H×W×3"})

    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)

    rgb = arr[:, :, ::-1].copy()
    image = Image.fromarray(rgb)

    recognizer = _get_recognizer()
    result = recognizer.recognize(image, blank_type=blank_type)

    payload: Dict[str, Any] = {
        "success": result.success,
        "confidence": round(result.confidence, 4) if result.confidence is not None else None,
        "is_empty": result.is_empty,
        "veroytn": result.veroytn,
        "blank_type": blank_type,
        "cells": result.raw_data.get("cells"),
    }
    return json.dumps(payload, ensure_ascii=False)
