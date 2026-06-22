from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from PIL import Image


@dataclass
class RecognitionResult:
    success: bool = True
    confidence: float = 1.0
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


class Recognizer:

    def __init__(self) -> None:
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        pass

    def _preprocess(self, image: Image.Image) -> Any:
        return image

    def _create_digit_probabilities(self, length: int) -> List[Dict[str, float]]:
        return [
            {"0": 0.1, "1": 0.1, "2": 0.1, "3": 0.1, "4": 0.1, "5": 0.1, "6": 0.1, "7": 0.1, "8": 0.1, "9": 0.1}
            for _ in range(length)
        ]

    def _recognize_titul(self, image: Image.Image) -> RecognitionResult:
        return RecognitionResult(
            success=True,
            confidence=0.5,
            veroytn={
                "next": self._create_digit_probabilities(13),
                "last": self._create_digit_probabilities(13),
            },
        )

    def _recognize_blan1(self, image: Image.Image) -> RecognitionResult:
        return RecognitionResult(
            success=True,
            confidence=0.5,
            veroytn=self._create_digit_probabilities(13),
        )

    def _recognize_blan2(self, image: Image.Image) -> RecognitionResult:
        return RecognitionResult(
            success=True,
            confidence=0.5,
            veroytn=self._create_digit_probabilities(3),
        )

    def _recognize_provr(self, image: Image.Image) -> RecognitionResult:
        return RecognitionResult(
            success=True,
            confidence=1.0,
            veroytn=None,
        )

    def recognize(self, image: Image.Image, blank_type: str = "") -> RecognitionResult:
        _ = self._preprocess(image)

        if blank_type == "titul":
            return self._recognize_titul(image)
        elif blank_type == "blan1":
            return self._recognize_blan1(image)
        elif blank_type == "blan2":
            return self._recognize_blan2(image)
        elif blank_type == "provr":
            return self._recognize_provr(image)

        return RecognitionResult(
            success=True,
            confidence=0.5,
            veroytn=self._create_digit_probabilities(13),
        )


def evaluate_special_case(
    result: RecognitionResult,
    config: Dict[str, Any],
) -> tuple[bool, List[str]]:
    rules = config.get("special_cases", {})
    labels = rules.get("custom_labels", {})
    reasons: List[str] = []

    threshold = float(rules.get("low_confidence_threshold", 0.65))
    if rules.get("count_on_low_confidence", True) and result.confidence < threshold:
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
