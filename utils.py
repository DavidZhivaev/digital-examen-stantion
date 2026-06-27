from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from uuid import uuid4

import numpy as np

# Пороги уверенности для автоматического решения (ниже — в очередь оператору).
DEFAULT_MIN_BAYES_FACTOR = 0.95
DEFAULT_MIN_LOG_MARGIN = 2.0
DEFAULT_MIN_POSTERIOR = 0.95
PAGE_OCR_AMBIGUITY_MARGIN = 1.0
OPERATOR_LINKS_DEFAULT = "operator_links.json"
MANUAL_REVIEW_QUEUE_DEFAULT = "manual_review_queue.json"
MANUAL_HISTORY_DEFAULT = "manual_history.json"
AUDIT_LOG_DEFAULT = "audit_log.json"

# Классификация аномалий.
ANOMALY_INFO = "INFO"
ANOMALY_WARNING = "WARNING"
ANOMALY_CRITICAL = "CRITICAL"

# Итоговые статусы аудитории (боевые).
AUDITORIUM_STATUS_CLEAN = "CLEAN"
AUDITORIUM_STATUS_AUTO_FIXED = "AUTO_FIXED"
AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
AUDITORIUM_STATUS_PARTIALLY_FIXED = "PARTIALLY_FIXED"
AUDITORIUM_STATUS_FINALIZED = "FINALIZED"

# Пороги показа оператору по confidence ребра / альтернативы.
CONFIDENCE_AUTO_HIDE = 0.95
CONFIDENCE_OPTIONAL_REVIEW = 0.80
CONFIDENCE_REQUIRED_REVIEW = 0.60

REVIEW_PRIORITY_CRITICAL = 1
REVIEW_PRIORITY_HIGH = 2
REVIEW_PRIORITY_MEDIUM = 3
REVIEW_PRIORITY_LOW = 4

REVIEW_TYPE_OCR_CONFLICT = "ocr_conflict"
REVIEW_TYPE_NEXT_BLANK_CONFLICT = "next_blank_conflict"
REVIEW_TYPE_PAGE_CONFLICT = "page_conflict"
REVIEW_TYPE_DUPLICATE_BLANK = "duplicate_blank"
REVIEW_TYPE_MULTIPLE_TITLES = "multiple_titles"
REVIEW_TYPE_ORPHAN = "orphan"
REVIEW_TYPE_CHAIN_GAP = "chain_gap"
REVIEW_TYPE_CYCLE = "cycle"
REVIEW_TYPE_NO_TRANSITION = "no_viable_transition"
REVIEW_TYPE_LOW_CONFIDENCE = "low_confidence"

FINAL_STATUS_CLEAN = "CLEAN"
FINAL_STATUS_AUTO_FIXED = "AUTO_FIXED"
FINAL_STATUS_PARTIALLY_MANUAL = "PARTIALLY_MANUAL"
FINAL_STATUS_WAITING_OPERATOR = "WAITING_OPERATOR"
FINAL_STATUS_COMPLETE = "COMPLETE"


BLANK_ALPHABET = "0234567"
PAGE_ALPHABET = "0234567"
CODE_LENGTH = 13
PAGE_LENGTH = 3
EPS = 1e-12
HAMMING_BOUNDARY = 97000

_PRESET_GENERATORS: Tuple[Tuple[int, np.ndarray], ...] = (
    (
        8,
        np.array(
            [
                [4, 2, 0, 1, 1, 5, 0, 4, 1, 1, 0, 5, 5],
                [3, 3, 1, 4, 4, 0, 3, 3, 3, 6, 2, 5, 6],
                [6, 1, 5, 6, 3, 1, 1, 5, 6, 6, 5, 0, 3],
                [6, 4, 0, 6, 2, 5, 3, 0, 5, 0, 1, 2, 0],
            ],
            dtype=np.int16,
        ),
    ),
    (
        7,
        np.array(
            [
                [4, 3, 2, 6, 0, 0, 1, 4, 1, 1, 3, 1, 3],
                [4, 0, 4, 2, 5, 4, 1, 1, 5, 0, 2, 6, 0],
                [2, 0, 4, 0, 4, 0, 5, 4, 3, 1, 3, 3, 0],
                [1, 2, 5, 4, 5, 1, 5, 1, 1, 4, 3, 0, 5],
                [1, 5, 5, 0, 2, 4, 6, 0, 1, 4, 4, 0, 5],
            ],
            dtype=np.int16,
        ),
    ),
    (
        6,
        np.array(
            [
                [4, 1, 5, 5, 5, 3, 0, 1, 3, 2, 3, 0, 4],
                [3, 1, 1, 0, 6, 5, 3, 3, 4, 4, 6, 3, 4],
                [1, 2, 5, 4, 2, 0, 6, 1, 6, 2, 6, 3, 3],
                [4, 2, 6, 0, 1, 2, 6, 6, 1, 1, 5, 5, 6],
                [2, 3, 2, 3, 6, 6, 1, 0, 3, 4, 2, 6, 0],
                [2, 3, 1, 6, 3, 5, 0, 2, 1, 1, 3, 2, 4],
            ],
            dtype=np.int16,
        ),
    ),
)


@dataclass(frozen=True)
class CodebookStats:
    size: int
    min_distance: int
    corrects_errors: int
    detects_errors: int
    singleton_upper_bound_for_d9: int
    hamming_upper_bound_for_d9: int
    note: str = (
        "d=9 при n=13, q=7 и 97000 кодах невозможен. "
        "Практическая устойчивость: QR + OCR + цепочка + аудитория."
    )


@dataclass
class _Node:
    number: str
    titul: Optional[Mapping[str, Any]] = None
    blan1: Optional[Mapping[str, Any]] = None
    blan2: Optional[Mapping[str, Any]] = None
    inferred_page: Optional[int] = None
    page_log_probs: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def is_title(self) -> bool:
        return self.titul is not None


@dataclass(frozen=True)
class _Edge:
    src: int
    dst: int
    score: float
    next_score: float
    struct_score: float
    bayes_factor: float
    log_margin: float
    reason: str
    forced: bool = False
    auto_eligible: bool = True


@dataclass(frozen=True)
class _ChainPath:
    title_idx: int
    blank_indices: Tuple[int, ...]
    edges: Tuple[_Edge, ...]
    total_score: float
    closed: bool


@dataclass(frozen=True)
class _ChainSolution:
    rank: int
    links: Dict[str, str]
    chains: Tuple[Dict[str, Any], ...]
    total_score: float
    joint_confidence_score: float
    warnings: Tuple[Dict[str, Any], ...]


def singleton_upper_bound(q: int, n: int, min_distance: int) -> int:
    if min_distance < 1 or min_distance > n + 1:
        return 0
    return q ** (n - min_distance + 1)


def hamming_upper_bound(q: int, n: int, min_distance: int) -> int:
    radius = (min_distance - 1) // 2
    volume = sum(math.comb(n, i) * (q - 1) ** i for i in range(radius + 1))
    return (q**n) // volume


def max_correctable_errors(min_distance: int) -> int:
    return (min_distance - 1) // 2


def _stable_seed(value: Any) -> int:
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _numeric_messages(q: int, dimension: int) -> np.ndarray:
    count = q**dimension
    values = np.arange(count, dtype=np.int64)
    powers = (q ** np.arange(dimension, dtype=np.int64))[None, :]
    return ((values[:, None] // powers) % q).astype(np.int16)


def _linear_code_numeric(generator: np.ndarray) -> np.ndarray:
    messages = _numeric_messages(len(BLANK_ALPHABET), generator.shape[0])
    return (messages @ generator % len(BLANK_ALPHABET)).astype(np.int16)


def _verify_linear_distance(codes_numeric: np.ndarray) -> int:
    non_zero = codes_numeric[1:]
    if len(non_zero) == 0:
        return CODE_LENGTH
    return int(np.count_nonzero(non_zero, axis=1).min())


def _encode_numeric_codes(codes_numeric: np.ndarray) -> List[str]:
    alphabet = np.array(list(BLANK_ALPHABET))
    return ["".join(row) for row in alphabet[codes_numeric]]


def generate_hamming13_codes(
    size: int = HAMMING_BOUNDARY,
    min_distance: int = 6,
    seed: int = 42,
    verify: bool = True,
) -> List[str]:
    if size < 1:
        raise ValueError("size must be positive")
    singleton = singleton_upper_bound(len(BLANK_ALPHABET), CODE_LENGTH, min_distance)
    if size > singleton:
        raise ValueError(
            f"Impossible: {size} codes with d={min_distance}, Singleton max {singleton}."
        )
    for preset_distance, generator in _PRESET_GENERATORS:
        capacity = len(BLANK_ALPHABET) ** generator.shape[0]
        if preset_distance >= min_distance and capacity >= size:
            numeric = _linear_code_numeric(generator)
            if verify:
                actual = _verify_linear_distance(numeric)
                if actual < preset_distance:
                    raise RuntimeError(f"Generator verify failed: d={actual}")
            order = np.random.default_rng(seed).permutation(len(numeric))
            return _encode_numeric_codes(numeric[order[:size]])
    raise ValueError(f"No generator for {size} codes with d>={min_distance}.")


def generate_hamming13_file(
    path: os.PathLike[str] | str = "hamming13.txt",
    size: int = HAMMING_BOUNDARY,
    min_distance: int = 6,
    seed: int = 42,
    overwrite: bool = False,
) -> List[str]:
    file_path = Path(path)
    if file_path.exists() and not overwrite:
        codes = [ln.strip() for ln in file_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(codes) < size:
            raise ValueError(f"{file_path}: {len(codes)} codes, need {size}")
        return codes[:size]
    codes = generate_hamming13_codes(size=size, min_distance=min_distance, seed=seed)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(codes) + "\n", encoding="utf-8")
    return codes


def codebook_stats(size: int = HAMMING_BOUNDARY, min_distance: int = 6) -> CodebookStats:
    return CodebookStats(
        size=size,
        min_distance=min_distance,
        corrects_errors=max_correctable_errors(min_distance),
        detects_errors=min_distance - 1,
        singleton_upper_bound_for_d9=singleton_upper_bound(7, 13, 9),
        hamming_upper_bound_for_d9=hamming_upper_bound(7, 13, 9),
    )


def hamming_distance(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def _codes_to_numeric(codes: Sequence[str]) -> np.ndarray:
    char_to_idx = {c: i for i, c in enumerate(BLANK_ALPHABET)}
    matrix = np.empty((len(codes), CODE_LENGTH), dtype=np.int16)
    for row, code in enumerate(codes):
        matrix[row] = [char_to_idx[ch] for ch in code]
    return matrix


def _load_json(path: Path, default: Mapping[str, Any]) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(default)


def _save_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_operator_links(
    auditorium_id: int | str,
    path: os.PathLike[str] | str = OPERATOR_LINKS_DEFAULT,
) -> Dict[str, str]:
    """Жёстко зафиксированные оператором связи {src_qr: dst_qr} для аудитории."""
    store = _load_json(Path(path), {"auditoriums": {}})
    aud = store.get("auditoriums", {}).get(str(auditorium_id), {})
    links = aud.get("force_links", {})
    return {str(k): str(v) for k, v in links.items()}


def save_operator_link(
    auditorium_id: int | str,
    src_number: str,
    dst_number: str,
    path: os.PathLike[str] | str = OPERATOR_LINKS_DEFAULT,
    operator_id: Optional[str] = None,
    note: str = "",
) -> Dict[str, str]:
    """Сохранить решение оператора и вернуть все force_links аудитории."""
    file_path = Path(path)
    store = _load_json(file_path, {"auditoriums": {}})
    key = str(auditorium_id)
    aud = store.setdefault("auditoriums", {}).setdefault(key, {"force_links": {}, "history": []})
    aud.setdefault("force_links", {})[str(src_number)] = str(dst_number)
    aud.setdefault("history", []).append(
        {
            "src": str(src_number),
            "dst": str(dst_number),
            "operator_id": operator_id,
            "note": note,
        }
    )
    _save_json(file_path, store)
    return dict(aud["force_links"])


def load_manual_review_queue(
    auditorium_id: int | str,
    path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
) -> List[Dict[str, Any]]:
    store = _load_json(Path(path), {"auditoriums": {}})
    return list(store.get("auditoriums", {}).get(str(auditorium_id), {}).get("pending", []))


def load_resolved_manual_reviews(
    auditorium_id: int | str,
    path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
) -> List[Dict[str, Any]]:
    store = _load_json(Path(path), {"auditoriums": {}})
    return list(store.get("auditoriums", {}).get(str(auditorium_id), {}).get("resolved", []))


def save_manual_review_queue(
    auditorium_id: int | str,
    queue: Sequence[Mapping[str, Any]],
    path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
    resolved: Optional[Sequence[Mapping[str, Any]]] = None,
) -> None:
    file_path = Path(path)
    store = _load_json(file_path, {"auditoriums": {}})
    key = str(auditorium_id)
    aud = store.setdefault("auditoriums", {}).setdefault(key, {"pending": [], "resolved": []})
    aud["pending"] = list(queue)
    if resolved is not None:
        aud["resolved"] = list(resolved)
    _save_json(file_path, store)


def _review_candidate_numbers(review: Mapping[str, Any]) -> List[str]:
    links = review.get("candidate_links", [])
    if links:
        return [str(item.get("dst", "")) for item in links if item.get("dst")]
    raw = review.get("candidates", [])
    if not raw:
        return []
    if isinstance(raw[0], Mapping):
        return [str(item.get("number", "")) for item in raw if item.get("number")]
    return [str(x) for x in raw]


def _mark_review_resolved(
    auditorium_id: int | str,
    review_id: str,
    chosen_candidate: str,
    path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
) -> Optional[Dict[str, Any]]:
    file_path = Path(path)
    store = _load_json(file_path, {"auditoriums": {}})
    key = str(auditorium_id)
    aud = store.setdefault("auditoriums", {}).setdefault(key, {"pending": [], "resolved": []})
    pending = list(aud.get("pending", []))
    resolved_item: Optional[Dict[str, Any]] = None
    for item in pending:
        if item.get("review_id") == review_id:
            resolved_item = dict(item)
            resolved_item["resolved"] = True
            resolved_item["status"] = "resolved"
            resolved_item["chosen_candidate"] = str(chosen_candidate)
            break
    if resolved_item is None:
        return None
    src_blank = resolved_item.get("blank")
    aud["pending"] = [
        item for item in pending
        if item.get("review_id") != review_id and item.get("blank") != src_blank
    ]
    aud.setdefault("resolved", []).append(resolved_item)
    _save_json(file_path, store)
    return resolved_item


def load_manual_history(
    auditorium_id: int | str,
    path: os.PathLike[str] | str = MANUAL_HISTORY_DEFAULT,
) -> List[Dict[str, Any]]:
    store = _load_json(Path(path), {"auditoriums": {}})
    return list(store.get("auditoriums", {}).get(str(auditorium_id), {}).get("entries", []))


def append_manual_history(
    auditorium_id: int | str,
    blank: str,
    old_value: Optional[str],
    new_value: str,
    operator_id: Optional[str] = None,
    reason: str = "",
    review_id: Optional[str] = None,
    path: os.PathLike[str] | str = MANUAL_HISTORY_DEFAULT,
    audit_details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    file_path = Path(path)
    store = _load_json(file_path, {"auditoriums": {}})
    key = str(auditorium_id)
    aud = store.setdefault("auditoriums", {}).setdefault(key, {"entries": []})
    entry = {
        "blank": str(blank),
        "old": old_value,
        "new": str(new_value),
        "operator": operator_id,
        "time": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "review_id": review_id,
    }
    if audit_details:
        entry["audit"] = dict(audit_details)
    aud.setdefault("entries", []).append(entry)
    _save_json(file_path, store)
    return entry


def load_audit_log(
    auditorium_id: int | str,
    path: os.PathLike[str] | str = AUDIT_LOG_DEFAULT,
) -> List[Dict[str, Any]]:
    store = _load_json(Path(path), {"auditoriums": {}})
    return list(store.get("auditoriums", {}).get(str(auditorium_id), {}).get("entries", []))


def append_audit_log(
    auditorium_id: int | str,
    entry: Mapping[str, Any],
    path: os.PathLike[str] | str = AUDIT_LOG_DEFAULT,
) -> Dict[str, Any]:
    file_path = Path(path)
    store = _load_json(file_path, {"auditoriums": {}})
    key = str(auditorium_id)
    aud = store.setdefault("auditoriums", {}).setdefault(key, {"entries": []})
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        **dict(entry),
    }
    aud.setdefault("entries", []).append(record)
    _save_json(file_path, store)
    return record


def _classify_reason(reason: str, review_type: str = "") -> str:
    reason_l = str(reason).lower()
    review_l = str(review_type).lower()
    critical_markers = (
        "foreign",
        "cycle",
        "duplicate",
        "multiple_titles",
        "orphan",
        "not_issued",
    )
    warning_markers = (
        "low_confidence",
        "low_bayes",
        "low_log_margin",
        "ocr",
        "ambiguous",
        "no_viable",
        "page_order",
        "page_number_ambiguous",
        "skipped_uncertain",
        "title_last_mismatch",
    )
    info_markers = (
        "missing_page",
        "manual_review_candidate",
        "unknown_type",
        "bad_qr",
    )
    haystack = f"{reason_l} {review_l}"
    if any(x in haystack for x in critical_markers):
        return ANOMALY_CRITICAL
    if any(x in haystack for x in warning_markers):
        return ANOMALY_WARNING
    if any(x in haystack for x in info_markers):
        return ANOMALY_INFO
    if review_l in {REVIEW_TYPE_CYCLE, REVIEW_TYPE_ORPHAN, REVIEW_TYPE_DUPLICATE_BLANK, REVIEW_TYPE_MULTIPLE_TITLES}:
        return ANOMALY_CRITICAL
    if review_l in {REVIEW_TYPE_OCR_CONFLICT, REVIEW_TYPE_LOW_CONFIDENCE, REVIEW_TYPE_NEXT_BLANK_CONFLICT, REVIEW_TYPE_NO_TRANSITION, REVIEW_TYPE_PAGE_CONFLICT}:
        return ANOMALY_WARNING
    if review_l == REVIEW_TYPE_CHAIN_GAP:
        return ANOMALY_INFO
    return ANOMALY_WARNING


def _operator_review_eligible(severity: str) -> bool:
    return severity in {ANOMALY_WARNING, ANOMALY_CRITICAL}


def _build_candidate_links(
    src_blank: str,
    candidate_numbers: Sequence[str],
    scores: Sequence[float],
    confidence_hint: float = 0.0,
) -> List[Dict[str, Any]]:
    alternatives = _build_alternatives(candidate_numbers, scores, confidence_hint)
    return [
        {
            "src": str(src_blank),
            "dst": alt["number"],
            "confidence": alt["probability"],
            "probability_percent": alt["probability_percent"],
            "ocr_score": alt["log_score"],
            "bayes_factor": alt["bayes_factor"],
            "rank": alt["rank"],
        }
        for alt in alternatives
    ]


def _related_blanks_for_review(
    blank: str,
    candidate_numbers: Sequence[str],
    title: Optional[str],
) -> List[str]:
    related = [str(blank)]
    for num in candidate_numbers:
        if num and num not in related:
            related.append(str(num))
    if title and title not in related:
        related.append(str(title))
    return related


def _entropy_from_probabilities(probabilities: Sequence[float]) -> float:
    total = 0.0
    for prob in probabilities:
        p = max(float(prob), EPS)
        total -= p * math.log(p)
    return float(total)


def _review_priority(review_type: str, confidence: float) -> int:
    critical = {
        REVIEW_TYPE_ORPHAN,
        REVIEW_TYPE_CYCLE,
        REVIEW_TYPE_NO_TRANSITION,
    }
    high = {
        REVIEW_TYPE_OCR_CONFLICT,
        REVIEW_TYPE_NEXT_BLANK_CONFLICT,
        REVIEW_TYPE_LOW_CONFIDENCE,
    }
    medium = {REVIEW_TYPE_PAGE_CONFLICT, REVIEW_TYPE_CHAIN_GAP}
    if review_type in critical or confidence < CONFIDENCE_REQUIRED_REVIEW:
        return REVIEW_PRIORITY_CRITICAL
    if review_type in high or confidence < CONFIDENCE_OPTIONAL_REVIEW:
        return REVIEW_PRIORITY_HIGH
    if review_type in medium:
        return REVIEW_PRIORITY_MEDIUM
    return REVIEW_PRIORITY_LOW


def _infer_title_for_blank(
    blank: str,
    chains: Sequence[Mapping[str, Any]],
    nodes: Sequence[_Node],
) -> Optional[str]:
    for chain in chains:
        if blank == chain.get("title"):
            return str(chain.get("title"))
        if blank in chain.get("blanks", []):
            return str(chain.get("title"))
    node = next((n for n in nodes if n.number == blank), None)
    if node and node.is_title:
        return node.number
    return None


def _build_alternatives(
    candidate_numbers: Sequence[str],
    scores: Sequence[float],
    confidence_hint: float = 0.0,
) -> List[Dict[str, Any]]:
    score_list = [float(s) for s in scores]
    if not candidate_numbers:
        return []
    if score_list:
        log_norm = _logsumexp(np.array(score_list, dtype=np.float64))
        posteriors = [
            float(math.exp(s - log_norm)) if math.isfinite(log_norm) else 0.0
            for s in score_list
        ]
    else:
        posteriors = [confidence_hint] + [0.0] * (len(candidate_numbers) - 1)
    entropy = _entropy_from_probabilities(posteriors) if posteriors else 0.0
    alternatives: List[Dict[str, Any]] = []
    for idx, number in enumerate(candidate_numbers):
        prob = posteriors[idx] if idx < len(posteriors) else 0.0
        alternatives.append(
            {
                "number": str(number),
                "probability": round(prob, 6),
                "probability_percent": round(prob * 100.0, 1),
                "log_score": round(score_list[idx], 4) if idx < len(score_list) else 0.0,
                "bayes_factor": round(prob, 6),
                "entropy": round(entropy, 6),
                "rank": idx + 1,
            }
        )
    return alternatives


def _enrich_review_item(
    item: Dict[str, Any],
    nodes: Sequence[_Node],
    chains: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    review_id = str(item.get("review_id", item.get("id", uuid4())))
    candidate_numbers = _review_candidate_numbers(item)
    scores = item.get("scores", [])
    if not candidate_numbers and item.get("candidate_details"):
        candidate_numbers = [str(x.get("number", "")) for x in item["candidate_details"]]
        scores = [x.get("log_score", 0.0) for x in item["candidate_details"]]
    confidence = float(item.get("confidence", item.get("automatic_probability", 0.0)) or 0.0)
    review_type = str(item.get("type", REVIEW_TYPE_NEXT_BLANK_CONFLICT))
    blank = str(item.get("blank", ""))
    title = item.get("title") or _infer_title_for_blank(blank, chains, nodes)
    alternatives = _build_alternatives(candidate_numbers, scores, confidence)
    priority = int(item.get("priority", _review_priority(review_type, confidence)))
    severity = str(item.get("severity", _classify_reason(str(item.get("reason", "")), review_type)))
    candidate_links = _build_candidate_links(blank, candidate_numbers, scores, confidence)
    related_blanks = _related_blanks_for_review(blank, candidate_numbers, str(title) if title else None)
    enriched = dict(item)
    enriched.update(
        {
            "id": review_id,
            "review_id": review_id,
            "priority": priority,
            "severity": severity,
            "title": title,
            "related_blanks": related_blanks,
            "candidate_links": candidate_links,
            "alternatives": alternatives,
            "confidence": round(confidence, 6),
            "show_to_operator": _operator_review_eligible(severity),
            "requires_operator": severity == ANOMALY_CRITICAL or confidence < CONFIDENCE_REQUIRED_REVIEW,
        }
    )
    if alternatives and not enriched.get("recommended"):
        enriched["recommended"] = alternatives[0]["number"]
        enriched["automatic_choice"] = alternatives[0]["number"]
    return enriched


def _build_edge_confidence_map(
    nodes: Sequence[_Node],
    outgoing: Dict[int, List[_Edge]],
    links: Mapping[str, str],
    forced_links: Mapping[str, str],
    source_candidates: Dict[int, List[Tuple[int, float]]],
) -> Dict[str, Dict[str, Any]]:
    number_to_idx = {n.number: i for i, n in enumerate(nodes)}
    edge_conf: Dict[str, Dict[str, Any]] = {}
    for src, dst in links.items():
        src_idx = number_to_idx.get(str(src))
        if src_idx is None:
            continue
        edge = next((e for e in outgoing.get(src_idx, []) if nodes[e.dst].number == str(dst)), None)
        cands = source_candidates.get(src_idx, [])
        score_list = [float(s) for _, s in cands[:8]]
        if score_list:
            log_norm = _logsumexp(np.array(score_list, dtype=np.float64))
            posteriors = [
                float(math.exp(s - log_norm)) if math.isfinite(log_norm) else 0.0
                for s in score_list
            ]
        else:
            posteriors = [1.0]
        entropy = _entropy_from_probabilities(posteriors)
        confidence = 1.0 if str(src) in forced_links else (edge.bayes_factor if edge else posteriors[0])
        if edge and edge.forced:
            confidence = 1.0
        edge_conf[str(src)] = {
            "dst": str(dst),
            "confidence": round(float(confidence), 6),
            "bayes_factor": round(float(edge.bayes_factor if edge else confidence), 6),
            "entropy": round(entropy, 6),
            "log_margin": round(float(edge.log_margin if edge else math.inf), 6),
            "ocr_score": round(float(edge.next_score if edge else 0.0), 6),
            "struct_score": round(float(edge.struct_score if edge else 0.0), 6),
            "forced": bool(str(src) in forced_links or (edge.forced if edge else False)),
            "operator_fixed": bool(str(src) in forced_links or (edge.forced if edge else False)),
            "show_to_operator": float(confidence) < CONFIDENCE_OPTIONAL_REVIEW and str(src) not in forced_links,
            "requires_operator": float(confidence) < CONFIDENCE_REQUIRED_REVIEW and str(src) not in forced_links,
            "alternatives": _build_alternatives(
                [nodes[j].number for j, _ in cands[:5]],
                [float(s) for _, s in cands[:5]],
                float(confidence),
            ),
        }
    return edge_conf


def _graph_component_titles(
    src_blank: str,
    dst_blank: str,
    links: Mapping[str, str],
    chains: Sequence[Mapping[str, Any]],
    nodes: Sequence[_Node],
    forced_links: Mapping[str, str],
) -> Set[str]:
    """Компонента графа, которую нужно пересчитать после решения оператора."""
    seed: Set[str] = set()
    for chain in chains:
        title = str(chain.get("title", ""))
        blanks = {str(b) for b in chain.get("blanks", [])}
        if src_blank == title or dst_blank == title or src_blank in blanks or dst_blank in blanks:
            seed.add(title)
    if not seed:
        dst_node = next((n for n in nodes if n.number == dst_blank), None)
        src_node = next((n for n in nodes if n.number == src_blank), None)
        if dst_node and dst_node.is_title:
            seed.add(dst_blank)
        elif src_node and src_node.is_title:
            seed.add(src_blank)
    if not seed:
        seed = {dst_blank, src_blank}
    component_blanks: Set[str] = set(seed)
    for title in list(seed):
        for chain in chains:
            if str(chain.get("title", "")) == title:
                component_blanks.add(title)
                component_blanks.update(str(b) for b in chain.get("blanks", []))
    # расширяем по текущим связям вокруг src/dst
    walk = {str(src_blank), str(dst_blank)}
    expanded = set(walk)
    for _ in range(len(links) + 2):
        changed = False
        for s, d in links.items():
            if s in expanded or d in expanded:
                if s not in expanded:
                    expanded.add(s)
                    changed = True
                if d not in expanded:
                    expanded.add(d)
                    changed = True
        for s, d in forced_links.items():
            if s in expanded or d in expanded:
                if s not in expanded:
                    expanded.add(s)
                    changed = True
                if d not in expanded:
                    expanded.add(d)
                    changed = True
        if not changed:
            break
    titles: Set[str] = set()
    for chain in chains:
        title = str(chain.get("title", ""))
        blanks = {str(b) for b in chain.get("blanks", [])}
        if title in expanded or expanded & blanks:
            titles.add(title)
    for num in expanded:
        node = next((n for n in nodes if n.number == num), None)
        if node and node.is_title:
            titles.add(num)
    return titles or seed


def _chain_path_from_result_chain(
    chain: Mapping[str, Any],
    nodes: Sequence[_Node],
) -> Optional[_ChainPath]:
    number_to_idx = {n.number: i for i, n in enumerate(nodes)}
    title = str(chain.get("title", ""))
    if title not in number_to_idx:
        return None
    blank_indices = tuple(
        number_to_idx[str(b)] for b in chain.get("blanks", []) if str(b) in number_to_idx
    )
    return _ChainPath(number_to_idx[title], blank_indices, tuple(), float(chain.get("total_score", 0.0)), bool(chain.get("closed_by_ocr")))


def resolve_operator_decision(
    auditorium_id: int | str,
    scan_data: Sequence[Mapping[str, Any]],
    src_number: str,
    dst_number: str,
    operator_id: Optional[str] = None,
    operator_links_path: os.PathLike[str] | str = OPERATOR_LINKS_DEFAULT,
    manual_review_queue_path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
    manual_history_path: os.PathLike[str] | str = MANUAL_HISTORY_DEFAULT,
    review_id: Optional[str] = None,
    reason: str = "operator_decision",
    previous_result: Optional[Mapping[str, Any]] = None,
    recalc_scope: str = "local",
    **process_kwargs: Any,
) -> Dict[str, Any]:
    """
    Оператор выбрал связь src -> dst.
    1) Фиксируем в operator_links.json
    2) Пишем manual_history.json
    3) Помечаем manual_review как resolved (если указан review_id)
    4) Локально или полностью пересчитываем аудиторию
    """
    old_value = None
    if previous_result is not None:
        old_value = previous_result.get("links", {}).get(str(src_number))
    elif auditorium_id is not None:
        old_value = load_operator_links(auditorium_id, operator_links_path).get(str(src_number))

    save_operator_link(
        auditorium_id, src_number, dst_number,
        path=operator_links_path, operator_id=operator_id, note=reason,
    )
    append_manual_history(
        auditorium_id,
        blank=str(src_number),
        old_value=old_value,
        new_value=str(dst_number),
        operator_id=operator_id,
        reason=reason,
        review_id=review_id,
        path=manual_history_path,
    )
    audit_path = process_kwargs.get("audit_log_path", AUDIT_LOG_DEFAULT)
    append_audit_log(
        auditorium_id,
        {
            "decision_type": "operator_fix",
            "src": str(src_number),
            "dst": str(dst_number),
            "old": old_value,
            "operator_intervention": True,
            "operator_fixed": True,
            "reason": reason,
            "review_id": review_id,
            "final_reason": "operator_selected_candidate",
            "alternatives": previous_result.get("manual_review_queue", []) if previous_result else [],
        },
        path=audit_path,
    )
    if review_id:
        _mark_review_resolved(auditorium_id, review_id, dst_number, manual_review_queue_path)
    else:
        pending = load_manual_review_queue(auditorium_id, manual_review_queue_path)
        resolved = load_resolved_manual_reviews(auditorium_id, manual_review_queue_path)
        pending = [item for item in pending if item.get("blank") != str(src_number)]
        save_manual_review_queue(auditorium_id, pending, manual_review_queue_path, resolved=resolved)

    if recalc_scope == "full":
        result = recalculate_auditorium(
            scan_data,
            auditorium_id=auditorium_id,
            operator_links_path=operator_links_path,
            manual_review_queue_path=manual_review_queue_path,
            manual_history_path=manual_history_path,
            **process_kwargs,
        )
    else:
        result = update_manual_decision_local(
            scan_data,
            auditorium_id=auditorium_id,
            src_number=str(src_number),
            dst_number=str(dst_number),
            previous_result=previous_result,
            operator_links_path=operator_links_path,
            manual_review_queue_path=manual_review_queue_path,
            manual_history_path=manual_history_path,
            **process_kwargs,
        )
    result["recalc_scope"] = recalc_scope
    return result


def apply_manual_review(
    review_id: str,
    chosen_candidate: str,
    auditorium_id: int | str,
    scan_data: Sequence[Mapping[str, Any]],
    operator_id: Optional[str] = None,
    operator_links_path: os.PathLike[str] | str = OPERATOR_LINKS_DEFAULT,
    manual_review_queue_path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
    manual_history_path: os.PathLike[str] | str = MANUAL_HISTORY_DEFAULT,
    previous_result: Optional[Mapping[str, Any]] = None,
    recalc_scope: str = "local",
    **process_kwargs: Any,
) -> Dict[str, Any]:
    """
    Оператор выбрал кандидата для manual_review.
    Решение фиксируется как жёсткое ребро графа, review помечается resolved,
    затем выполняется локальный (по умолчанию) или полный пересчёт.
    """
    pending = load_manual_review_queue(auditorium_id, manual_review_queue_path)
    review = next((item for item in pending if item.get("review_id") == review_id), None)
    if review is None:
        raise ValueError(f"Manual review {review_id!r} not found in pending queue.")
    if review.get("resolved") or review.get("status") == "resolved":
        raise ValueError(f"Manual review {review_id!r} is already resolved.")

    valid_candidates = _review_candidate_numbers(review)
    chosen = str(chosen_candidate)
    if valid_candidates and chosen not in valid_candidates:
        raise ValueError(
            f"Chosen candidate {chosen!r} is not among review candidates: {valid_candidates}."
        )

    src_blank = str(review.get("blank", ""))
    if not src_blank:
        raise ValueError(f"Manual review {review_id!r} has no blank number.")

    if previous_result is None:
        previous_result = process_auditorium_blanks(
            scan_data,
            auditorium_id=auditorium_id,
            return_details=True,
            persist_review_queue=False,
            operator_links_path=operator_links_path,
            manual_review_queue_path=manual_review_queue_path,
            manual_history_path=manual_history_path,
            **process_kwargs,
        )

    return resolve_operator_decision(
        auditorium_id,
        scan_data,
        src_blank,
        chosen,
        operator_id=operator_id,
        operator_links_path=operator_links_path,
        manual_review_queue_path=manual_review_queue_path,
        manual_history_path=manual_history_path,
        review_id=review_id,
        reason=str(review.get("reason", "manual_review")),
        previous_result=previous_result,
        recalc_scope=recalc_scope,
        **process_kwargs,
    )


def update_manual_decision(
    review_id: str,
    chosen_candidate: str,
    auditorium_id: int | str,
    scan_data: Sequence[Mapping[str, Any]],
    previous_result: Optional[Mapping[str, Any]] = None,
    recalc_scope: str = "local",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Основной API для UI оператора: выбор альтернативы и локальный пересчёт."""
    return apply_manual_review(
        review_id,
        chosen_candidate,
        auditorium_id,
        scan_data,
        previous_result=previous_result,
        recalc_scope=recalc_scope,
        **kwargs,
    )


def update_manual_decision_local(
    scan_data: Sequence[Mapping[str, Any]],
    auditorium_id: int | str,
    src_number: str,
    dst_number: str,
    previous_result: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Локальный пересчёт затронутых цепочек после решения оператора.
    Незатронутые завершённые цепочки сохраняются из previous_result.
    """
    kwargs = dict(kwargs)
    kwargs["return_details"] = True
    kwargs.setdefault("auditorium_id", auditorium_id)

    if previous_result is None:
        return process_auditorium_blanks(scan_data, **kwargs)

    affected_titles = _graph_component_titles(
        str(src_number),
        str(dst_number),
        previous_result.get("links", {}),
        previous_result.get("chains", []),
        _aggregate_nodes(scan_data, kwargs.get("issued_numbers"))[0],
        load_operator_links(auditorium_id, kwargs.get("operator_links_path", OPERATOR_LINKS_DEFAULT)),
    )
    kwargs["locked_chains"] = [
        chain for chain in previous_result.get("chains", [])
        if str(chain.get("title", "")) not in affected_titles
    ]
    kwargs["affected_titles"] = sorted(affected_titles)
    result = process_auditorium_blanks(scan_data, **kwargs)
    result["recalc_scope"] = "local"
    result["affected_titles"] = sorted(affected_titles)
    result["locked_titles"] = [
        str(chain.get("title", ""))
        for chain in kwargs["locked_chains"]
    ]
    return result


def recalculate_auditorium(
    scan_data: Sequence[Mapping[str, Any]],
    auditorium_id: int | str,
    recalc_scope: str = "full",
    previous_result: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Пересчёт аудитории (полный или локальный после решения оператора)."""
    if recalc_scope == "local" and previous_result is not None:
        kwargs = dict(kwargs)
        kwargs["return_details"] = True
        kwargs.setdefault("auditorium_id", auditorium_id)
        kwargs["locked_chains"] = [
            chain for chain in previous_result.get("chains", [])
            if str(chain.get("title", "")) not in set(map(str, kwargs.get("affected_titles", [])))
        ]
        return process_auditorium_blanks(scan_data, **kwargs)
    kwargs = dict(kwargs)
    kwargs["return_details"] = True
    kwargs.setdefault("auditorium_id", auditorium_id)
    return process_auditorium_blanks(scan_data, **kwargs)


def solve_auditorium_until_clean(
    scan_data: Sequence[Mapping[str, Any]],
    auditorium_id: int | str,
    max_rounds: int = 10,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Итерационный режим до стабилизации:
      solve -> конфликты? -> (оператор через update_manual_decision) -> local recalc -> ...
    """
    return stabilize_auditorium_graph(scan_data, auditorium_id, max_rounds=max_rounds, **kwargs)


def stabilize_auditorium_graph(
    scan_data: Sequence[Mapping[str, Any]],
    auditorium_id: int | str,
    max_rounds: int = 10,
    previous_result: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Итерационный цикл до стабилизации графа.
    Без вмешательства оператора возвращает manual_reviews, если они остались.
    """
    kwargs = dict(kwargs)
    kwargs["return_details"] = True
    kwargs["auditorium_id"] = auditorium_id
    last: Dict[str, Any] = dict(previous_result) if previous_result else {}
    for _ in range(max_rounds):
        last = process_auditorium_blanks(scan_data, **kwargs)
        pending = int(last.get("remaining_manual_reviews", len(last.get("manual_reviews", []))))
        auditorium_status = str(last.get("auditorium_status", ""))
        if pending or auditorium_status == AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED:
            last["graph_stable"] = False
            return last
        if auditorium_status in {
            AUDITORIUM_STATUS_CLEAN,
            AUDITORIUM_STATUS_AUTO_FIXED,
            AUDITORIUM_STATUS_FINALIZED,
            AUDITORIUM_STATUS_PARTIALLY_FIXED,
        }:
            last["graph_stable"] = True
            return last
    last["graph_stable"] = False
    return last


def issue_blank_numbers(
    auditorium_id: int | str,
    count: int = 1,
    codebook_path: os.PathLike[str] | str = "hamming13.txt",
    store_path: os.PathLike[str] | str = "issued_blanks.json",
    codebook_size: int = HAMMING_BOUNDARY,
    codebook_min_distance: int = 6,
    unique_global: bool = True,
    candidate_sample: int = 12000,
) -> List[str]:
    if count < 1:
        return []
    codes = generate_hamming13_file(codebook_path, size=codebook_size, min_distance=codebook_min_distance)
    store_file = Path(store_path)
    store = _load_json(store_file, {"global_used": [], "auditoriums": {}})
    key = str(auditorium_id)
    auditorium_used = list(store["auditoriums"].get(key, []))
    global_used = set(store.get("global_used", []))
    numeric_codes = _codes_to_numeric(codes)
    code_to_index = {c: i for i, c in enumerate(codes)}
    selected: List[str] = []
    rng = np.random.default_rng(_stable_seed(key))
    for _ in range(count):
        unavailable = set(global_used if unique_global else ())
        unavailable.update(auditorium_used)
        available_idx = np.array([i for i, c in enumerate(codes) if c not in unavailable], dtype=np.int64)
        if len(available_idx) == 0:
            raise RuntimeError("No blank ids left")
        if len(available_idx) > candidate_sample:
            available_idx = rng.choice(available_idx, size=candidate_sample, replace=False)
        if auditorium_used:
            existing = numeric_codes[[code_to_index[c] for c in auditorium_used]]
            best_idx, best_dist = int(available_idx[0]), -1
            for start in range(0, len(available_idx), 512):
                chunk_idx = available_idx[start : start + 512]
                chunk = numeric_codes[chunk_idx]
                dists = np.count_nonzero(chunk[:, None, :] != existing[None, :, :], axis=2).min(axis=1)
                pos = int(np.argmax(dists))
                if int(dists[pos]) > best_dist:
                    best_dist, best_idx = int(dists[pos]), int(chunk_idx[pos])
        else:
            best_idx = int(available_idx[_stable_seed(key) % len(available_idx)])
        code = codes[best_idx]
        selected.append(code)
        auditorium_used.append(code)
        global_used.add(code)
    store["auditoriums"][key] = auditorium_used
    store["global_used"] = sorted(global_used)
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected


def issued_numbers_for_auditorium(auditorium_id: int | str, store_path: os.PathLike[str] | str = "issued_blanks.json") -> List[str]:
    store = _load_json(Path(store_path), {"global_used": [], "auditoriums": {}})
    return list(store.get("auditoriums", {}).get(str(auditorium_id), []))


def _normal_prob(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError):
        return 0.0
    if p > 1.0:
        p /= 100.0
    return max(0.0, min(1.0, p))


def _position_probability(position: Mapping[Any, Any], char: str) -> float:
    if char in position:
        return _normal_prob(position[char])
    alt = int(char) if char.isdigit() else char
    return _normal_prob(position[alt]) if alt in position else 0.0


def _extract_veroytn(record: Optional[Mapping[str, Any]], field: str) -> Optional[Sequence[Mapping[Any, Any]]]:
    if not record:
        return None
    value = record.get("veroytn")
    if isinstance(value, list):
        return value
    if not isinstance(value, Mapping):
        return None
    aliases = {
        "next": ("next", "first", "sled", "next_blank"),
        "last": ("last", "last_blank"),
        "page": ("page", "list", "sheet", "number"),
    }
    for key in aliases.get(field, (field,)):
        cand = value.get(key)
        if isinstance(cand, list):
            return cand
    return None


def _sequence_log_prob(field_probs: Optional[Sequence[Mapping[Any, Any]]], target: str, missing_log: float = -math.inf) -> float:
    if field_probs is None or len(field_probs) != len(target):
        return missing_log
    return sum(math.log(max(_position_probability(p, c), EPS)) for p, c in zip(field_probs, target))


def _field_log_table(field_probs: Optional[Sequence[Mapping[Any, Any]]], alphabet: str, length: int) -> Optional[np.ndarray]:
    if field_probs is None or len(field_probs) != length:
        return None
    table = np.empty((length, len(alphabet)), dtype=np.float64)
    for pos, probs in enumerate(field_probs):
        for idx, char in enumerate(alphabet):
            table[pos, idx] = math.log(max(_position_probability(probs, char), EPS))
    return table


def _logsumexp(values: np.ndarray) -> float:
    if len(values) == 0:
        return -math.inf
    mx = float(np.max(values))
    if not math.isfinite(mx):
        return -math.inf
    return mx + math.log(float(np.exp(values - mx).sum()))


def _top_candidates(field_probs, candidate_indices, id_matrix, top_k) -> List[Tuple[int, float]]:
    if len(candidate_indices) == 0:
        return []
    table = _field_log_table(field_probs, BLANK_ALPHABET, CODE_LENGTH)
    if table is None:
        return []
    cm = id_matrix[candidate_indices]
    scores = sum(table[pos, cm[:, pos]] for pos in range(CODE_LENGTH))
    take = min(top_k, len(candidate_indices))
    rough = np.argpartition(-scores, take - 1)[:take]
    order = rough[np.argsort(-scores[rough])]
    return [(int(candidate_indices[i]), float(scores[i])) for i in order]


def _page_log_distribution(node: _Node, max_page: int) -> np.ndarray:
    result = np.full(max_page + 1, -math.inf, dtype=np.float64)
    if node.is_title:
        result[0] = 0.0
        return result
    field = _extract_veroytn(node.blan2, "page")
    if field is None or len(field) != PAGE_LENGTH:
        result[1:] = -math.log(max_page)
        return result
    for page in range(1, max_page + 1):
        result[page] = _sequence_log_prob(field, f"{page:03d}", missing_log=-math.inf)
    norm = _logsumexp(result[1:])
    if math.isfinite(norm):
        result[1:] -= norm
    return result


def _infer_page(node: _Node, max_page: int) -> None:
    logs = _page_log_distribution(node, max_page)
    node.page_log_probs = logs
    node.inferred_page = 0 if node.is_title else (int(np.argmax(logs[1:])) + 1 if len(logs) > 1 else None)


def _page_transition_log(src_pages: np.ndarray, dst_pages: np.ndarray) -> float:
    if len(src_pages) != len(dst_pages) or len(src_pages) <= 2:
        return -math.inf
    return _logsumexp(src_pages[1:-1] + dst_pages[2:])


def _aggregate_nodes(scan_data, allowed_numbers):
    allowed = set(map(str, allowed_numbers)) if allowed_numbers is not None else None
    nodes: Dict[str, _Node] = {}
    suspicious: List[Dict[str, Any]] = []
    for item in scan_data:
        form_type = str(item.get("type", "")).strip()
        number = str(item.get("number", "")).strip()
        if form_type not in {"titul", "blan1", "blan2"}:
            suspicious.append({"number": number, "reason": f"unknown_type:{form_type}"})
            continue
        if len(number) != CODE_LENGTH:
            suspicious.append({"number": number, "reason": "bad_qr_length"})
            continue
        if allowed is not None and number not in allowed:
            suspicious.append({"number": number, "reason": "not_issued_to_auditorium", "foreign": True})
            continue
        if number not in nodes:
            nodes[number] = _Node(number=number)
        node = nodes[number]
        if getattr(node, form_type) is not None:
            suspicious.append({"number": number, "reason": f"duplicate_{form_type}"})
        setattr(node, form_type, item)
    return list(nodes.values()), suspicious


def _log_margin_from_candidates(candidates: List[Tuple[int, float]]) -> float:
    if len(candidates) >= 2:
        return float(candidates[0][1] - candidates[1][1])
    return math.inf


def _edge_is_auto_eligible(
    bayes_factor: float,
    log_margin: float,
    min_bayes_factor: float,
    min_log_margin: float,
    forced: bool,
) -> bool:
    if forced:
        return True
    return bayes_factor >= min_bayes_factor and log_margin >= min_log_margin


def _apply_forced_links(
    nodes: Sequence[_Node],
    outgoing: Dict[int, List[_Edge]],
    forced_links: Dict[str, str],
    source_candidates: Dict[int, List[Tuple[int, float]]],
) -> Dict[int, List[_Edge]]:
    """Оставляет только forced-ребро для зафиксированных src (или добавляет синтетическое)."""
    if not forced_links:
        return outgoing
    number_to_idx = {n.number: i for i, n in enumerate(nodes)}
    result: Dict[int, List[_Edge]] = {i: list(edges) for i, edges in outgoing.items()}
    for src_num, dst_num in forced_links.items():
        if src_num not in number_to_idx or dst_num not in number_to_idx:
            continue
        src_idx = number_to_idx[src_num]
        dst_idx = number_to_idx[dst_num]
        existing = [e for e in result.get(src_idx, []) if e.dst == dst_idx]
        if existing:
            result[src_idx] = [
                _Edge(
                    e.src, e.dst, e.score + 1000.0, e.next_score, e.struct_score,
                    1.0, math.inf, e.reason, forced=True, auto_eligible=True,
                )
                for e in existing
            ]
        else:
            sc = 0.0
            cands = source_candidates.get(src_idx, [])
            for idx, s in cands:
                if idx == dst_idx:
                    sc = s
                    break
            result[src_idx] = [
                _Edge(src_idx, dst_idx, sc + 1000.0, sc, 0.0, 1.0, math.inf, "operator_forced", True, True)
            ]
    return result


def _hungarian_maximize(cost: np.ndarray) -> List[int]:
    """Максимизация суммы: cost shape (n,n), returns assignment row->col."""
    n = cost.shape[0]
    if n == 0:
        return []
    u = np.zeros(n + 1)
    v = np.zeros(n + 1)
    p = np.zeros(n + 1, dtype=np.int64)
    way = np.zeros(n + 1, dtype=np.int64)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(n + 1, math.inf)
        used = np.zeros(n + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = int(p[j0])
            delta = math.inf
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = -cost[i0 - 1, j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = int(way[j0])
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] > 0:
            assignment[int(p[j]) - 1] = j - 1
    return assignment


def _resolve_incoming_conflicts_hungarian(
    nodes: Sequence[_Node],
    candidate_edges: List[_Edge],
) -> List[_Edge]:
    """
    Если несколько src претендуют на один dst (не титул), выбираем глобально оптимальное
    сопоставление через Hungarian algorithm.
    """
    if len(candidate_edges) <= 1:
        return candidate_edges
    by_dst: Dict[int, List[_Edge]] = {}
    for e in candidate_edges:
        if nodes[e.dst].is_title:
            continue
        by_dst.setdefault(e.dst, []).append(e)
    conflict_dsts = {d for d, es in by_dst.items() if len(es) > 1}
    if not conflict_dsts:
        return candidate_edges

    keep: Set[Tuple[int, int]] = set()
    for dst in conflict_dsts:
        edges = by_dst[dst]
        n = len(edges)
        cost = np.zeros((n, n), dtype=np.float64)
        for i, e in enumerate(edges):
            cost[i, i] = e.score
            for j in range(n):
                if i != j:
                    cost[i, j] = -1e9
        assign = _hungarian_maximize(cost)
        for i, j in enumerate(assign):
            if j == i:
                keep.add((edges[i].src, edges[i].dst))

    resolved: List[_Edge] = []
    for e in candidate_edges:
        if nodes[e.dst].is_title or e.dst not in conflict_dsts:
            resolved.append(e)
        elif (e.src, e.dst) in keep:
            resolved.append(e)
    return resolved


def _build_manual_review_item(
    nodes: Sequence[_Node],
    src_idx: int,
    source_candidates: Dict[int, List[Tuple[int, float]]],
    reason: str,
    auditorium_id: Optional[str],
    review_type: str = REVIEW_TYPE_NEXT_BLANK_CONFLICT,
    automatic_choice: Optional[str] = None,
    automatic_probability: float = 0.0,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    cands = source_candidates.get(src_idx, [])[:5]
    scores_arr = [float(s) for _, s in cands]
    candidate_numbers = [nodes[j].number for j, _ in cands]
    log_norm = _logsumexp(np.array(scores_arr, dtype=np.float64)) if scores_arr else -math.inf
    posteriors = [
        round(math.exp(s - log_norm), 6) if math.isfinite(log_norm) else 0.0
        for s in scores_arr
    ]
    recommended = automatic_choice or (candidate_numbers[0] if candidate_numbers else None)
    confidence = automatic_probability or (posteriors[0] if posteriors else 0.0)
    item: Dict[str, Any] = {
        "review_id": str(uuid4()),
        "type": review_type,
        "auditorium_id": str(auditorium_id) if auditorium_id is not None else "",
        "blank": nodes[src_idx].number,
        "candidates": candidate_numbers,
        "scores": [round(s, 4) for s in scores_arr],
        "reason": reason,
        "recommended": recommended,
        "confidence": round(confidence, 6),
        "resolved": False,
        "status": "pending",
        "field": "next_blank",
        "automatic_choice": recommended,
        "automatic_probability": round(confidence, 6),
        "candidate_details": [
            {"number": num, "log_score": round(s, 4), "posterior": p}
            for num, s, p in zip(candidate_numbers, scores_arr, posteriors)
        ],
    }
    if extra:
        item.update(dict(extra))
    return item


def _build_structural_review_item(
    blank: str,
    review_type: str,
    reason: str,
    auditorium_id: Optional[str],
    candidates: Optional[Sequence[str]] = None,
    scores: Optional[Sequence[float]] = None,
    recommended: Optional[str] = None,
    confidence: float = 0.0,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    cand_list = list(candidates or [])
    score_list = [round(float(s), 4) for s in (scores or [])]
    if len(score_list) < len(cand_list):
        score_list.extend([0.0] * (len(cand_list) - len(score_list)))
    item: Dict[str, Any] = {
        "review_id": str(uuid4()),
        "type": review_type,
        "auditorium_id": str(auditorium_id) if auditorium_id is not None else "",
        "blank": blank,
        "candidates": cand_list,
        "scores": score_list[: len(cand_list)],
        "reason": reason,
        "recommended": recommended,
        "confidence": round(confidence, 6),
        "resolved": False,
        "status": "pending",
        "field": "next_blank",
        "automatic_choice": recommended,
        "automatic_probability": round(confidence, 6),
        "candidate_details": [
            {"number": num, "log_score": score_list[i] if i < len(score_list) else 0.0, "posterior": 0.0}
            for i, num in enumerate(cand_list)
        ],
    }
    if extra:
        item.update(dict(extra))
    return item


def _detect_cycles_in_links(links: Mapping[str, str]) -> List[List[str]]:
    cycles: List[List[str]] = []
    visited: Set[str] = set()
    for start in links:
        if start in visited:
            continue
        path: List[str] = []
        index_in_path: Dict[str, int] = {}
        current: Optional[str] = start
        while current is not None and current in links:
            if current in index_in_path:
                cycles.append(path[index_in_path[current] :])
                break
            if current in visited:
                break
            index_in_path[current] = len(path)
            path.append(current)
            current = links.get(current)
        visited.update(path)
    return cycles


def _propagate_graph_constraints(
    nodes: Sequence[_Node],
    outgoing: Dict[int, List[_Edge]],
    source_candidates: Dict[int, List[Tuple[int, float]]],
    forced_links: Dict[str, str],
    min_bayes_factor: float,
    min_log_margin: float,
) -> Dict[str, str]:
    """
    После фиксации оператором пытаться вывести соседние связи из ограничений графа.
    Возвращает только новые производные связи (не дублирует operator force_links).
    """
    number_to_idx = {n.number: i for i, n in enumerate(nodes)}
    derived: Dict[str, str] = {}
    all_fixed = dict(forced_links)
    changed = True

    def _try_add(src_num: str, dst_num: str) -> bool:
        if src_num in all_fixed or src_num not in number_to_idx or dst_num not in number_to_idx:
            return False
        src_idx = number_to_idx[src_num]
        edges = outgoing.get(src_idx, [])
        match = next((e for e in edges if nodes[e.dst].number == dst_num), None)
        if match is None:
            return False
        if not match.auto_eligible and not match.forced:
            return False
        if match.bayes_factor < min_bayes_factor or match.log_margin < min_log_margin:
            return False
        all_fixed[src_num] = dst_num
        derived[src_num] = dst_num
        return True

    while changed:
        changed = False
        for src_num, dst_num in list(all_fixed.items()):
            src_idx = number_to_idx.get(src_num)
            dst_idx = number_to_idx.get(dst_num)
            if src_idx is None or dst_idx is None:
                continue
            src_node = nodes[src_idx]
            dst_node = nodes[dst_idx]

            if src_node.is_title and not dst_node.is_title:
                dst_page = dst_node.inferred_page or 1
                successors = [
                    n for n in nodes
                    if not n.is_title and (n.inferred_page or 0) == dst_page + 1
                ]
                if len(successors) == 1:
                    changed = _try_add(dst_num, successors[0].number) or changed

            if not src_node.is_title and dst_node.is_title:
                src_page = src_node.inferred_page or 0
                if src_page > 1:
                    predecessors = [
                        n for n in nodes
                        if not n.is_title and (n.inferred_page or 0) == src_page - 1
                    ]
                    if len(predecessors) == 1:
                        changed = _try_add(predecessors[0].number, src_num) or changed

            if not src_node.is_title and not dst_node.is_title:
                src_page = src_node.inferred_page or 0
                dst_page = dst_node.inferred_page or 0
                if dst_page == src_page + 1:
                    prev_candidates = [
                        n for n in nodes
                        if not n.is_title and (n.inferred_page or 0) == src_page - 1
                    ]
                    if len(prev_candidates) == 1:
                        changed = _try_add(prev_candidates[0].number, src_num) or changed
                    next_candidates = [
                        n for n in nodes
                        if not n.is_title and (n.inferred_page or 0) == dst_page + 1
                    ]
                    if len(next_candidates) == 1:
                        changed = _try_add(dst_num, next_candidates[0].number) or changed

    return derived


def _detect_ambiguities(
    nodes: Sequence[_Node],
    outgoing: Dict[int, List[_Edge]],
    source_candidates: Dict[int, List[Tuple[int, float]]],
    forced_links: Dict[str, str],
    solutions: Sequence[_ChainSolution],
    chains: Sequence[Mapping[str, Any]],
    links: Mapping[str, str],
    suspicious: Sequence[Mapping[str, Any]],
    auditorium_id: Optional[str],
    min_bayes_factor: float,
    min_log_margin: float,
) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str]] = set()
    forced_src = set(forced_links.keys())

    def add_item(item: Dict[str, Any]) -> None:
        key = (str(item.get("type", "")), str(item.get("blank", "")))
        if key in seen_keys:
            return
        seen_keys.add(key)
        queue.append(item)

    for src_idx, edges in outgoing.items():
        src_num = nodes[src_idx].number
        if src_num in forced_src:
            continue

        cands = source_candidates.get(src_idx, [])
        if len(cands) >= 2 and cands[0][1] - cands[1][1] < min_log_margin:
            add_item(
                _build_manual_review_item(
                    nodes,
                    src_idx,
                    source_candidates,
                    "ocr_candidates_too_close",
                    auditorium_id,
                    review_type=REVIEW_TYPE_OCR_CONFLICT,
                    automatic_choice=nodes[cands[0][0]].number,
                    automatic_probability=float(math.exp(cands[0][1] - _logsumexp(np.array([x[1] for x in cands[:5]], dtype=np.float64)))),
                )
            )

        if not edges:
            if not nodes[src_idx].is_title:
                add_item(
                    _build_manual_review_item(
                        nodes,
                        src_idx,
                        source_candidates,
                        "no_viable_transition",
                        auditorium_id,
                        review_type=REVIEW_TYPE_NO_TRANSITION,
                    )
                )
            continue

        best = edges[0]
        if best.auto_eligible:
            continue

        reason = "ambiguous_transition"
        review_type = REVIEW_TYPE_NEXT_BLANK_CONFLICT
        if best.bayes_factor < min_bayes_factor:
            reason = "low_bayes_factor"
            review_type = REVIEW_TYPE_LOW_CONFIDENCE
        elif best.log_margin < min_log_margin:
            reason = "low_log_margin"
            review_type = REVIEW_TYPE_LOW_CONFIDENCE

        add_item(
            _build_manual_review_item(
                nodes,
                src_idx,
                source_candidates,
                reason,
                auditorium_id,
                review_type=review_type,
                automatic_choice=nodes[best.dst].number,
                automatic_probability=best.bayes_factor,
            )
        )

    for node in nodes:
        if node.is_title or node.inferred_page in (None, 0):
            continue
        page_logs = node.page_log_probs
        if page_logs is None or len(page_logs) <= 2:
            continue
        top2 = np.argsort(-page_logs[1:])[:2] + 1
        if len(top2) >= 2:
            p1 = float(page_logs[int(top2[0])])
            p2 = float(page_logs[int(top2[1])])
            if abs(p1 - p2) < PAGE_OCR_AMBIGUITY_MARGIN:
                add_item(
                    _build_structural_review_item(
                        node.number,
                        REVIEW_TYPE_PAGE_CONFLICT,
                        "page_number_ambiguous",
                        auditorium_id,
                        candidates=[f"{int(top2[0]):03d}", f"{int(top2[1]):03d}"],
                        scores=[p1, p2],
                        recommended=f"{int(top2[0]):03d}",
                        confidence=float(math.exp(p1 - _logsumexp(page_logs[1:]))),
                    )
                )

    for chain in chains:
        pages = list(chain.get("pages", []))
        blanks = list(chain.get("blanks", []))
        for i in range(1, len(pages)):
            prev_page, next_page = pages[i - 1], pages[i]
            if prev_page and next_page and next_page <= prev_page:
                blank = blanks[i] if i < len(blanks) else (blanks[0] if blanks else str(chain.get("title", "")))
                add_item(
                    _build_structural_review_item(
                        str(blank),
                        REVIEW_TYPE_PAGE_CONFLICT,
                        "page_order_not_monotonic",
                        auditorium_id,
                        recommended=str(next_page),
                        confidence=0.0,
                        extra={"from_page": prev_page, "to_page": next_page, "title": chain.get("title")},
                    )
                )

    blank_to_titles: Dict[str, Set[str]] = {}
    for chain in chains:
        title = str(chain.get("title", ""))
        for blank in chain.get("blanks", []):
            blank_to_titles.setdefault(str(blank), set()).add(title)
    for blank, titles in blank_to_titles.items():
        if len(titles) > 1:
            add_item(
                _build_structural_review_item(
                    blank,
                    REVIEW_TYPE_MULTIPLE_TITLES,
                    "blank_belongs_to_multiple_chains",
                    auditorium_id,
                    candidates=sorted(titles),
                    recommended=sorted(titles)[0],
                    confidence=1.0 / len(titles),
                    extra={"titles": sorted(titles)},
                )
            )

    if len(solutions) >= 2:
        usage: Dict[str, int] = {}
        for sol in solutions[:3]:
            for blank in {b for ch in sol.chains for b in ch.get("blanks", [])}:
                usage[str(blank)] = usage.get(str(blank), 0) + 1
        for blank, count in usage.items():
            if count > 1:
                add_item(
                    _build_structural_review_item(
                        blank,
                        REVIEW_TYPE_DUPLICATE_BLANK,
                        "blank_used_in_multiple_solution_variants",
                        auditorium_id,
                        confidence=1.0 / count,
                        extra={"solution_hits": count},
                    )
                )

    for item in suspicious:
        if item.get("reason") == "orphan_blank_not_linked":
            blank = str(item.get("number", ""))
            src_idx = next((i for i, n in enumerate(nodes) if n.number == blank), None)
            if src_idx is not None:
                add_item(
                    _build_manual_review_item(
                        nodes,
                        src_idx,
                        source_candidates,
                        "orphan_blank_not_linked",
                        auditorium_id,
                        review_type=REVIEW_TYPE_ORPHAN,
                    )
                )

    for chain in chains:
        blank_indices = [
            next(i for i, n in enumerate(nodes) if n.number == b)
            for b in chain.get("blanks", [])
            if any(n.number == b for n in nodes)
        ]
        for warning in _detect_page_gaps(tuple(blank_indices), nodes):
            # INFO: пропуск страницы не отправляем оператору автоматически.
            warning["severity"] = ANOMALY_INFO
            warning["type"] = REVIEW_TYPE_CHAIN_GAP

    for cycle in _detect_cycles_in_links(links):
        if not cycle:
            continue
        add_item(
            _build_structural_review_item(
                cycle[0],
                REVIEW_TYPE_CYCLE,
                "cycle_detected_in_proposed_links",
                auditorium_id,
                candidates=list(cycle),
                confidence=0.0,
                extra={"cycle": cycle},
            )
        )

    return queue


def _collect_manual_review_queue(
    nodes: Sequence[_Node],
    outgoing: Dict[int, List[_Edge]],
    source_candidates: Dict[int, List[Tuple[int, float]]],
    forced_links: Dict[str, str],
    auditorium_id: Optional[str],
    min_bayes_factor: float,
    min_log_margin: float,
    solutions: Optional[Sequence[_ChainSolution]] = None,
    chains: Optional[Sequence[Mapping[str, Any]]] = None,
    links: Optional[Mapping[str, str]] = None,
    suspicious: Optional[Sequence[Mapping[str, Any]]] = None,
    persisted_pending: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    detected = _detect_ambiguities(
        nodes,
        outgoing,
        source_candidates,
        forced_links,
        solutions or (),
        chains or (),
        links or {},
        suspicious or (),
        auditorium_id,
        min_bayes_factor,
        min_log_margin,
    )
    merged: Dict[str, Dict[str, Any]] = {}
    for item in persisted_pending or ():
        if item.get("status") == "pending" and not item.get("resolved"):
            merged[str(item.get("blank", ""))] = dict(item)
    for item in detected:
        blank = str(item.get("blank", ""))
        if blank in forced_links:
            continue
        if blank not in merged:
            merged[blank] = item
    enriched = [
        _enrich_review_item(item, nodes, chains or ())
        for item in merged.values()
    ]
    operator_reviews = [item for item in enriched if item.get("show_to_operator")]
    operator_reviews.sort(key=lambda x: (int(x.get("priority", REVIEW_PRIORITY_LOW)), -float(x.get("confidence", 0.0))))
    return operator_reviews


def _annotate_anomaly_severity(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        reason = str(item.get("reason", ""))
        review_type = str(item.get("type", ""))
        item["severity"] = _classify_reason(reason, review_type)
        annotated.append(item)
    return annotated


def _split_classified_anomalies(
    suspicious: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    chains: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    combined = _annotate_anomaly_severity(list(suspicious) + list(warnings))
    for chain in chains:
        for warning in chain.get("warnings", []):
            w = dict(warning)
            w["severity"] = _classify_reason(str(w.get("reason", "")), str(w.get("type", "")))
            combined.append(w)
    result = {ANOMALY_INFO: [], ANOMALY_WARNING: [], ANOMALY_CRITICAL: []}
    seen: Set[str] = set()
    for item in combined:
        key = json.dumps({"n": item.get("number", item.get("blank", item.get("qr", ""))), "r": item.get("reason", "")}, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        severity = str(item.get("severity", ANOMALY_INFO))
        if severity not in result:
            severity = ANOMALY_INFO
        result[severity].append(item)
    return result


def _compute_chain_confidence(
    chain: Mapping[str, Any],
    edge_confidence: Mapping[str, Mapping[str, Any]],
    forced_links: Mapping[str, str],
) -> float:
    title = str(chain.get("title", ""))
    blanks = list(chain.get("blanks", []))
    edge_keys = []
    if blanks:
        for i in range(len(blanks) - 1):
            edge_keys.append(str(blanks[i]))
        edge_keys.append(str(blanks[-1]))
    if title and title not in edge_keys:
        edge_keys.insert(0, title)
    confidences: List[float] = []
    for src in edge_keys:
        if src in edge_confidence:
            confidences.append(float(edge_confidence[src].get("confidence", 0.0)))
        elif src in forced_links:
            confidences.append(1.0)
    if not confidences:
        return 1.0 if chain.get("closed_by_ocr") else 0.5
    if not chain.get("closed_by_ocr"):
        confidences.append(0.85)
    return round(float(math.exp(sum(math.log(max(c, EPS)) for c in confidences))), 6)


def _enrich_chains_with_confidence(
    chains: Sequence[Mapping[str, Any]],
    edge_confidence: Mapping[str, Mapping[str, Any]],
    forced_links: Mapping[str, str],
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for chain in chains:
        ch = dict(chain)
        ch["chain_confidence"] = _compute_chain_confidence(ch, edge_confidence, forced_links)
        enriched.append(ch)
    return enriched


def _compute_auditorium_confidence(
    chains: Sequence[Mapping[str, Any]],
    manual_reviews: Sequence[Mapping[str, Any]],
    classified: Mapping[str, Sequence[Mapping[str, Any]]],
    forced_links: Mapping[str, str],
) -> float:
    if not chains:
        return 0.0
    chain_scores = [float(c.get("chain_confidence", 0.0)) for c in chains]
    base = float(math.exp(sum(math.log(max(s, EPS)) for s in chain_scores))) if chain_scores else 0.0
    penalty = 1.0
    penalty *= 0.5 ** len(classified.get(ANOMALY_CRITICAL, []))
    penalty *= 0.8 ** len(classified.get(ANOMALY_WARNING, []))
    penalty *= 0.95 ** len(classified.get(ANOMALY_INFO, []))
    penalty *= 0.9 ** len(manual_reviews)
    if forced_links:
        penalty = max(penalty, 0.75)
    return round(min(1.0, base * penalty), 6)


def _compute_auditorium_status(
    manual_reviews: Sequence[Mapping[str, Any]],
    forced_links: Mapping[str, str],
    derived_links: Mapping[str, str],
    classified: Mapping[str, Sequence[Mapping[str, Any]]],
    legacy_status: str,
    resolved_reviews_count: int,
) -> str:
    if manual_reviews:
        return AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED
    if legacy_status == "NEEDS_OPERATOR":
        return AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED
    has_critical = bool(classified.get(ANOMALY_CRITICAL))
    if forced_links and resolved_reviews_count > 0 and not has_critical:
        return AUDITORIUM_STATUS_FINALIZED
    if forced_links and not has_critical:
        return AUDITORIUM_STATUS_PARTIALLY_FIXED
    if derived_links or classified.get(ANOMALY_WARNING):
        return AUDITORIUM_STATUS_AUTO_FIXED
    if legacy_status == "CLEAN":
        return AUDITORIUM_STATUS_CLEAN
    if forced_links:
        return AUDITORIUM_STATUS_PARTIALLY_FIXED
    return AUDITORIUM_STATUS_AUTO_FIXED if legacy_status == "PARTIAL" else AUDITORIUM_STATUS_CLEAN


def _build_automatic_audit_entries(
    links: Mapping[str, str],
    edge_confidence: Mapping[str, Mapping[str, Any]],
    forced_links: Mapping[str, str],
    derived_links: Mapping[str, str],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for src, dst in links.items():
        meta = edge_confidence.get(str(src), {})
        entries.append(
            {
                "decision_type": "automatic_link",
                "src": str(src),
                "dst": str(dst),
                "ocr_score": meta.get("ocr_score", 0.0),
                "struct_score": meta.get("struct_score", 0.0),
                "confidence": meta.get("confidence", 0.0),
                "bayes_factor": meta.get("bayes_factor", 0.0),
                "entropy": meta.get("entropy", 0.0),
                "log_margin": meta.get("log_margin", 0.0),
                "operator_intervention": False,
                "operator_fixed": str(src) in forced_links,
                "derived": str(src) in derived_links,
                "final_reason": "operator_forced" if str(src) in forced_links else (
                    "graph_propagation" if str(src) in derived_links else "automatic_selection"
                ),
                "alternatives": meta.get("alternatives", []),
                "penalties": [],
            }
        )
    return entries


def _legacy_final_status_from_auditorium(auditorium_status: str, manual_reviews: Sequence[Mapping[str, Any]]) -> str:
    if auditorium_status == AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED or manual_reviews:
        return FINAL_STATUS_WAITING_OPERATOR
    if auditorium_status == AUDITORIUM_STATUS_CLEAN:
        return FINAL_STATUS_CLEAN
    if auditorium_status == AUDITORIUM_STATUS_AUTO_FIXED:
        return FINAL_STATUS_AUTO_FIXED
    if auditorium_status in {AUDITORIUM_STATUS_PARTIALLY_FIXED, AUDITORIUM_STATUS_FINALIZED}:
        return FINAL_STATUS_COMPLETE
    return FINAL_STATUS_PARTIALLY_MANUAL


def _compute_link_statistics(
    links: Mapping[str, str],
    forced_links: Mapping[str, str],
    derived_links: Mapping[str, str],
    resolved_reviews: Sequence[Mapping[str, Any]],
    pending_reviews: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    manual_keys = set(forced_links.keys())
    automatic_links = {k: v for k, v in links.items() if k not in manual_keys}
    manual_links = {k: v for k, v in links.items() if k in manual_keys}
    total_reviews = len(resolved_reviews) + len(pending_reviews)
    resolved_count = len(resolved_reviews)
    remaining = len(pending_reviews)
    auto_rate = (resolved_count / total_reviews) if total_reviews else 1.0
    return {
        "automatic_links": dict(automatic_links),
        "manual_links": dict(manual_links),
        "derived_links": dict(derived_links),
        "manual_reviews_total": total_reviews,
        "manual_reviews_resolved": resolved_count,
        "remaining_manual_reviews": remaining,
        "auto_resolution_rate": round(auto_rate, 6),
    }


def _compute_final_status(
    legacy_status: str,
    pending_reviews: Sequence[Mapping[str, Any]],
    forced_links: Mapping[str, str],
    suspicious: Sequence[Mapping[str, Any]],
    derived_links: Mapping[str, str],
    warnings: Sequence[Mapping[str, Any]],
) -> str:
    if pending_reviews:
        return FINAL_STATUS_WAITING_OPERATOR
    if legacy_status == "NEEDS_OPERATOR":
        return FINAL_STATUS_WAITING_OPERATOR
    serious_suspicious = [
        s for s in suspicious
        if s.get("reason") in {"orphan_blank_not_linked", "duplicate_blan1", "duplicate_blan2", "duplicate_titul"}
    ]
    if legacy_status == "CLEAN" and not serious_suspicious:
        if forced_links:
            return FINAL_STATUS_COMPLETE
        if derived_links or any(w.get("reason") == "skipped_uncertain_edge" for w in warnings):
            return FINAL_STATUS_AUTO_FIXED
        return FINAL_STATUS_CLEAN
    if forced_links and legacy_status in {"CLEAN", "PARTIAL"}:
        return FINAL_STATUS_PARTIALLY_MANUAL if serious_suspicious else FINAL_STATUS_COMPLETE
    if legacy_status == "PARTIAL":
        return FINAL_STATUS_PARTIALLY_MANUAL
    if not serious_suspicious and not pending_reviews:
        return FINAL_STATUS_COMPLETE
    return FINAL_STATUS_PARTIALLY_MANUAL


def _build_outgoing_adjacency(
    nodes,
    max_page,
    max_candidates,
    min_edge_log_prob,
    page_weight,
    title_last_weight,
    min_bayes_factor,
    min_log_margin,
    forced_links,
):
    id_matrix = _codes_to_numeric([n.number for n in nodes])
    titles = np.array([i for i, n in enumerate(nodes) if n.is_title], dtype=np.int64)
    answers = np.array([i for i, n in enumerate(nodes) if not n.is_title], dtype=np.int64)
    all_idx = np.arange(len(nodes), dtype=np.int64)
    for node in nodes:
        _infer_page(node, max_page)
    page_logs = [n.page_log_probs for n in nodes]
    outgoing: Dict[int, List[_Edge]] = {i: [] for i in range(len(nodes))}
    source_candidates: Dict[int, List[Tuple[int, float]]] = {}
    for src_idx, src in enumerate(nodes):
        next_rec = src.titul if src.is_title else src.blan1
        next_field = _extract_veroytn(next_rec, "next")
        pool = answers if src.is_title else all_idx[all_idx != src_idx]
        candidates = _top_candidates(next_field, pool, id_matrix, max_candidates)
        if not src.is_title:
            for ti in titles:
                if int(ti) != src_idx:
                    candidates.append((int(ti), _sequence_log_prob(next_field, nodes[int(ti)].number)))
        best_by_dst: Dict[int, float] = {}
        for dst_idx, sc in candidates:
            if dst_idx != src_idx:
                best_by_dst[dst_idx] = max(sc, best_by_dst.get(dst_idx, -math.inf))
        sorted_next = sorted(best_by_dst.items(), key=lambda x: x[1], reverse=True)
        source_candidates[src_idx] = sorted_next
        log_margin = _log_margin_from_candidates(sorted_next)
        log_norm = _logsumexp(np.array([s for _, s in sorted_next], dtype=np.float64))
        forced_dst = forced_links.get(src.number)
        forced_dst_idx = next((i for i, n in enumerate(nodes) if n.number == forced_dst), None) if forced_dst else None

        for dst_idx, next_score in sorted_next:
            dst = nodes[dst_idx]
            if src.is_title and dst.is_title:
                continue
            if src.is_title and not dst.is_title:
                struct = float(page_logs[dst_idx][1])
                reason = "title_to_first_blank"
            elif not src.is_title and not dst.is_title:
                struct = _page_transition_log(page_logs[src_idx], page_logs[dst_idx])
                reason = "blank_to_next_blank"
            elif not src.is_title and dst.is_title:
                last_f = _extract_veroytn(dst.titul, "last")
                struct = title_last_weight * _sequence_log_prob(last_f, src.number, missing_log=0.0)
                reason = "last_blank_to_title"
            else:
                continue
            score = next_score + page_weight * struct
            if score < min_edge_log_prob:
                continue
            bf = float(math.exp(next_score - log_norm)) if math.isfinite(log_norm) else 0.0
            is_forced = forced_dst_idx is not None and dst_idx == forced_dst_idx
            auto_ok = _edge_is_auto_eligible(bf, log_margin, min_bayes_factor, min_log_margin, is_forced)
            outgoing[src_idx].append(
                _Edge(src_idx, dst_idx, score, next_score, struct, bf, log_margin, reason, is_forced, auto_ok)
            )

        if forced_dst_idx is not None and not any(e.dst == forced_dst_idx for e in outgoing[src_idx]):
            outgoing[src_idx].append(
                _Edge(
                    src_idx, forced_dst_idx, 1000.0,
                    _sequence_log_prob(next_field, nodes[forced_dst_idx].number),
                    0.0, 1.0, math.inf, "operator_forced", True, True,
                )
            )

        outgoing[src_idx].sort(key=lambda e: e.score, reverse=True)
        if forced_dst_idx is not None:
            outgoing[src_idx] = [e for e in outgoing[src_idx] if e.forced or e.dst == forced_dst_idx]

    for src_idx in list(outgoing.keys()):
        auto_edges = [e for e in outgoing[src_idx] if e.auto_eligible]
        if auto_edges:
            outgoing[src_idx] = _resolve_incoming_conflicts_hungarian(nodes, auto_edges)
        elif outgoing[src_idx]:
            outgoing[src_idx] = [outgoing[src_idx][0]]

    return outgoing, source_candidates


def _decode_greedy(field_probs: Sequence[Mapping[Any, Any]], alphabet: str) -> Tuple[str, float]:
    chars: List[str] = []
    confs: List[float] = []
    for pos in field_probs:
        best = max(alphabet, key=lambda c: _position_probability(pos, c))
        chars.append(best)
        confs.append(_position_probability(pos, best))
    return "".join(chars), min(confs) if confs else 0.0


def _foreign_next_intent(
    src_idx: int,
    nodes: Sequence[_Node],
    source_candidates: Dict[int, List[Tuple[int, float]]],
    allowed_set: Optional[set[str]],
    min_confidence: float = 0.55,
    log_margin: float = 2.0,
) -> Optional[str]:
    """Detect when a student wrote another person's blank number."""
    src = nodes[src_idx]
    field = _extract_veroytn(src.blan1 if not src.is_title else src.titul, "next")
    if not field or len(field) != CODE_LENGTH:
        return None

    decoded, min_conf = _decode_greedy(field, BLANK_ALPHABET)
    if min_conf < min_confidence:
        return None

    node_by_number = {n.number: i for i, n in enumerate(nodes)}
    cands = source_candidates.get(src_idx, [])
    if len(cands) >= 2 and cands[0][1] - cands[1][1] < log_margin:
        # OCR not confident enough to break the chain on foreign intent alone.
        if decoded in node_by_number:
            return None

    if decoded not in node_by_number:
        return decoded

    dst_idx = node_by_number[decoded]
    if nodes[dst_idx].is_title:
        return None

    src_page = src.inferred_page or 0
    dst_page = nodes[dst_idx].inferred_page or 0
    if dst_page <= src_page:
        return decoded

    if allowed_set is not None and decoded not in allowed_set:
        return decoded

    return None


def _beam_paths_from_title(
    title_idx,
    nodes,
    outgoing,
    source_candidates,
    allowed_set,
    beam_width,
    max_depth,
    globally_used=None,
):
    used_global = globally_used or set()
    beam = [(0.0, title_idx, tuple(), tuple())]
    completed: List[_ChainPath] = []
    for _ in range(max_depth):
        nxt = []
        for total, cur, blanks, edges in beam:
            if cur != title_idx and nodes[cur].is_title:
                completed.append(_ChainPath(title_idx, blanks, edges, total, True))
                continue

            foreign_ref = None
            if cur != title_idx and not nodes[cur].is_title:
                foreign_ref = _foreign_next_intent(cur, nodes, source_candidates, allowed_set)

            for edge in outgoing.get(cur, []):
                if not edge.auto_eligible and not edge.forced:
                    continue
                dst = edge.dst
                if foreign_ref and not nodes[dst].is_title and dst != title_idx:
                    # Student wrote someone else's blank — stop chain here.
                    continue
                if dst == title_idx and cur != title_idx:
                    completed.append(_ChainPath(title_idx, blanks, edges + (edge,), total + edge.score, True))
                    continue
                if nodes[dst].is_title and cur != title_idx:
                    completed.append(_ChainPath(title_idx, blanks, edges, total, False))
                    continue
                if dst in blanks or dst in used_global:
                    continue
                nxt.append((total + edge.score, dst, blanks + (dst,), edges + (edge,)))
        if not nxt:
            break
        nxt.sort(key=lambda x: x[0], reverse=True)
        beam = nxt[:beam_width]
    for total, cur, blanks, edges in beam:
        if blanks:
            completed.append(_ChainPath(title_idx, blanks, edges, total, False))
    completed.sort(key=lambda p: (p.closed, p.total_score), reverse=True)
    uniq, seen = [], set()
    for p in completed:
        if p.blank_indices in seen:
            continue
        seen.add(p.blank_indices)
        uniq.append(p)
        if len(uniq) >= beam_width:
            break
    return uniq


def _detect_page_gaps(blank_indices, nodes):
    pages = sorted({nodes[i].inferred_page for i in blank_indices if nodes[i].inferred_page and nodes[i].inferred_page > 0})
    warnings = []
    for a, b in zip(pages, pages[1:]):
        if b - a > 1:
            warnings.append({"reason": "missing_page_in_chain", "from_page": a, "to_page": b, "missing": list(range(a + 1, b))})
    return warnings


def _path_to_chain(path, nodes, source_candidates, min_bayes_factor, pending_review_blanks):
    title = nodes[path.title_idx]
    warnings: List[Dict[str, Any]] = []
    links: Dict[str, str] = {}
    nums = [nodes[i].number for i in path.blank_indices]
    if not nums:
        return links, {"title": title.number, "blanks": [], "closed_by_ocr": path.closed, "warnings": warnings}, warnings
    warnings.extend(_detect_page_gaps(path.blank_indices, nodes))
    last_f = _extract_veroytn(title.titul, "last")
    if last_f is not None and _sequence_log_prob(last_f, nums[-1]) < -20.0:
        warnings.append({"number": title.number, "reason": "title_last_mismatch", "expected_last": nums[-1]})
    for i in range(len(path.blank_indices) - 1):
        src_num = nodes[path.blank_indices[i]].number
        dst_num = nodes[path.blank_indices[i + 1]].number
        if src_num in pending_review_blanks:
            continue
        links[src_num] = dst_num
    last_num = nums[-1]
    if last_num not in pending_review_blanks:
        links[last_num] = title.number
    for edge in path.edges:
        if not edge.auto_eligible and not edge.forced:
            warnings.append({
                "number": nodes[edge.src].number,
                "reason": "skipped_uncertain_edge",
                "bayes_factor": edge.bayes_factor,
                "log_margin": edge.log_margin,
            })
        elif edge.bayes_factor < min_bayes_factor and not edge.forced:
            alts = source_candidates.get(edge.src, [])[:3]
            warnings.append({
                "qr": nodes[edge.src].number,
                "field": "next_blank",
                "automatic_choice": nodes[edge.dst].number,
                "automatic_probability": edge.bayes_factor,
                "alternatives": [{"candidate": nodes[j].number, "score": s} for j, s in alts],
                "reason": "manual_review_candidate",
            })
    chain = {
        "title": title.number,
        "blanks": nums,
        "pages": [nodes[i].inferred_page for i in path.blank_indices],
        "closed_by_ocr": path.closed,
        "total_score": path.total_score,
        "warnings": warnings,
    }
    return links, chain, warnings


def _solve_global_chains(
    nodes,
    outgoing,
    source_candidates,
    allowed_set,
    beam_width,
    min_bayes_factor,
    pending_review_blanks,
    max_solutions=3,
    locked_paths: Optional[Dict[int, _ChainPath]] = None,
    only_title_indices: Optional[Set[int]] = None,
):
    titles = [i for i, n in enumerate(nodes) if n.is_title]
    answers = sum(1 for n in nodes if not n.is_title)
    locked_paths = locked_paths or {}
    title_best: Dict[int, List[_ChainPath]] = {}
    for t in titles:
        if only_title_indices is not None and t not in only_title_indices and t in locked_paths:
            title_best[t] = [locked_paths[t]]
        else:
            title_best[t] = _beam_paths_from_title(
                t, nodes, outgoing, source_candidates, allowed_set, beam_width, min(answers + 1, 200)
            )
    solutions: List[_ChainSolution] = []
    seen_keys: set[str] = set()

    def try_config(picks: List[_ChainPath]) -> Optional[_ChainSolution]:
        used: set[int] = set()
        links: Dict[str, str] = {}
        chains: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        total = 0.0
        confs: List[float] = []
        for path in picks:
            if set(path.blank_indices) & used:
                return None
            used.update(path.blank_indices)
            pl, ch, w = _path_to_chain(path, nodes, source_candidates, min_bayes_factor, pending_review_blanks)
            links.update(pl)
            chains.append(ch)
            warnings.extend(w)
            total += path.total_score
            confs.extend(e.bayes_factor for e in path.edges)
        key = json.dumps(links, sort_keys=True)
        if key in seen_keys:
            return None
        seen_keys.add(key)
        joint = float(math.exp(sum(math.log(max(c, EPS)) for c in confs))) if confs else (0.0 if warnings else 1.0)
        return _ChainSolution(0, links, tuple(chains), total, joint, tuple(warnings))

    for alt in range(beam_width):
        picks: List[_ChainPath] = []
        used: set[int] = set()
        for t in titles:
            paths = title_best[t]
            if not paths:
                continue
            pick = paths[alt] if alt < len(paths) else paths[0]
            if set(pick.blank_indices) & used:
                pick = next((p for p in paths if not (set(p.blank_indices) & used)), paths[0])
            picks.append(pick)
            used.update(pick.blank_indices)
        sol = try_config(picks)
        if sol:
            solutions.append(sol)
        if len(solutions) >= max_solutions:
            break
    solutions.sort(key=lambda s: s.total_score, reverse=True)
    return [
        _ChainSolution(i + 1, s.links, s.chains, s.total_score, s.joint_confidence_score, s.warnings)
        for i, s in enumerate(solutions[:max_solutions])
    ]


def assess_automation_risks(result: Mapping[str, Any], blanks_in_auditorium: int = 0) -> Dict[str, Any]:
    suspicious = list(result.get("suspicious", []))
    warnings = list(result.get("warnings", []))
    manual = list(result.get("manual_review_queue", result.get("manual_reviews", [])))
    status = str(result.get("status", ""))
    orphans = sum(1 for x in suspicious if x.get("reason") == "orphan_blank_not_linked")
    foreign = sum(1 for x in suspicious if x.get("foreign") or "foreign" in str(x.get("reason", "")))
    open_chains = sum(1 for c in result.get("chains", []) if not c.get("closed_by_ocr"))
    page_gaps = sum(1 for w in warnings if w.get("reason") == "missing_page_in_chain")
    joint = float(result.get("joint_confidence_score", result.get("approx_clean_probability", 0.0)))
    score = joint * (0.5 ** orphans) * (0.3 ** foreign) * (0.7 ** open_chains) * (0.8 ** page_gaps) * (0.9 ** len(manual))
    if blanks_in_auditorium > 2500:
        score *= 0.92
    elif blanks_in_auditorium > 1500:
        score *= 0.96
    if status == "CLEAN" and score >= 0.985:
        verdict = "Полная автоматизация реалистична для этой аудитории"
    elif status == "CLEAN" or score >= 0.95:
        verdict = "Почти без оператора; редкие ручные проверки"
    elif score >= 0.85:
        verdict = "Нужен оператор только на спорных цепочках"
    else:
        verdict = "Высокий риск; нужен контроль оператора"
    return {
        "automation_score": round(score, 4),
        "estimated_no_human_probability_percent": round(score * 100, 2),
        "verdict": verdict,
        "orphan_blanks": orphans,
        "foreign_blanks": foreign,
        "open_chains": open_chains,
        "page_gaps": page_gaps,
        "manual_review_items": len(manual),
        "risks": [
            "d=9 при 97000 кодах недостижим — опираемся на QR+OCR+цепочку+аудиторию",
            "При >1500 бланков растёт риск коллизий OCR",
            "Чужой номер бланка: лист не учитывается, цепь замыкается",
            "Пропуск страницы (001-003) — потерянный лист или OCR",
        ],
    }


def process_auditorium_blanks(
    scan_data: Sequence[Mapping[str, Any]],
    auditorium_id: Optional[int | str] = None,
    issued_numbers: Optional[Iterable[str]] = None,
    issued_store_path: os.PathLike[str] | str = "issued_blanks.json",
    operator_links_path: os.PathLike[str] | str = OPERATOR_LINKS_DEFAULT,
    manual_review_queue_path: os.PathLike[str] | str = MANUAL_REVIEW_QUEUE_DEFAULT,
    manual_history_path: os.PathLike[str] | str = MANUAL_HISTORY_DEFAULT,
    audit_log_path: os.PathLike[str] | str = AUDIT_LOG_DEFAULT,
    persist_audit_log: bool = False,
    max_page: int = 999,
    max_candidates: int = 16,
    min_edge_log_prob: float = -80.0,
    min_bayes_factor: float = DEFAULT_MIN_BAYES_FACTOR,
    min_log_margin: float = DEFAULT_MIN_LOG_MARGIN,
    beam_width: int = 12,
    max_solutions: int = 3,
    page_weight: float = 1.0,
    title_last_weight: float = 1.5,
    persist_review_queue: bool = True,
    return_details: bool = False,
    locked_chains: Optional[Sequence[Mapping[str, Any]]] = None,
    affected_titles: Optional[Sequence[str]] = None,
) -> Dict[str, Any] | Dict[str, str]:
    if issued_numbers is None and auditorium_id is not None and Path(issued_store_path).exists():
        issued_numbers = issued_numbers_for_auditorium(auditorium_id, issued_store_path)
    allowed_set = set(map(str, issued_numbers)) if issued_numbers is not None else None
    nodes, suspicious = _aggregate_nodes(scan_data, issued_numbers)
    if not nodes:
        empty = {
            "links": {}, "renames": {}, "chains": [], "solutions": [],
            "suspicious": suspicious, "warnings": [], "manual_reviews": [],
            "manual_review_queue": [], "status": "NEEDS_OPERATOR" if suspicious else "CLEAN",
            "final_status": FINAL_STATUS_WAITING_OPERATOR if suspicious else FINAL_STATUS_CLEAN,
            "review_required": bool(suspicious), "joint_confidence_score": 0.0,
            "approx_clean_probability": 0.0, "codebook_note": codebook_stats().note,
            "force_links_applied": {}, "derived_links_applied": {},
            "automatic_links": {}, "manual_links": {},
            "manual_reviews_total": 0, "manual_reviews_resolved": 0,
            "remaining_manual_reviews": 0, "auto_resolution_rate": 1.0,
            "edge_confidence": {}, "manual_history": [], "audit_log": [],
            "classified_anomalies": {ANOMALY_INFO: [], ANOMALY_WARNING: [], ANOMALY_CRITICAL: []},
            "auditorium_status": AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED if suspicious else AUDITORIUM_STATUS_CLEAN,
            "auditorium_confidence": 0.0,
        }
        empty["risk_assessment"] = assess_automation_risks(empty, 0)
        return empty if return_details else {}

    forced_links: Dict[str, str] = {}
    if auditorium_id is not None:
        forced_links = load_operator_links(auditorium_id, operator_links_path)

    persisted_pending = (
        load_manual_review_queue(auditorium_id, manual_review_queue_path)
        if auditorium_id is not None else []
    )
    resolved_reviews = (
        load_resolved_manual_reviews(auditorium_id, manual_review_queue_path)
        if auditorium_id is not None else []
    )
    manual_history = (
        load_manual_history(auditorium_id, manual_history_path)
        if auditorium_id is not None else []
    )

    locked_paths: Dict[int, _ChainPath] = {}
    if locked_chains:
        for chain in locked_chains:
            path = _chain_path_from_result_chain(chain, nodes)
            if path is not None:
                locked_paths[path.title_idx] = path
    only_title_indices: Optional[Set[int]] = None
    if affected_titles:
        affected_set = {str(t) for t in affected_titles}
        only_title_indices = {
            i for i, n in enumerate(nodes) if n.is_title and n.number in affected_set
        }
        if not only_title_indices:
            only_title_indices = None

    outgoing, source_candidates = _build_outgoing_adjacency(
        nodes, max_page, max_candidates, min_edge_log_prob, page_weight, title_last_weight,
        min_bayes_factor, min_log_margin, forced_links,
    )
    outgoing = _apply_forced_links(nodes, outgoing, forced_links, source_candidates)
    derived_links = _propagate_graph_constraints(
        nodes, outgoing, source_candidates, forced_links, min_bayes_factor, min_log_margin,
    )
    effective_forced = dict(forced_links)
    effective_forced.update(derived_links)
    if derived_links:
        outgoing, source_candidates = _build_outgoing_adjacency(
            nodes, max_page, max_candidates, min_edge_log_prob, page_weight, title_last_weight,
            min_bayes_factor, min_log_margin, effective_forced,
        )
        outgoing = _apply_forced_links(nodes, outgoing, effective_forced, source_candidates)

    preliminary_pending = _collect_manual_review_queue(
        nodes, outgoing, source_candidates, effective_forced,
        str(auditorium_id) if auditorium_id is not None else None,
        min_bayes_factor, min_log_margin,
        persisted_pending=persisted_pending,
    )
    pending_review_blanks = {
        item["blank"] for item in preliminary_pending if item.get("status") == "pending" and not item.get("resolved")
    }

    solutions = _solve_global_chains(
        nodes, outgoing, source_candidates, allowed_set, beam_width, min_bayes_factor,
        pending_review_blanks, max_solutions,
        locked_paths=locked_paths,
        only_title_indices=only_title_indices,
    )
    best = solutions[0] if solutions else None
    links = dict(best.links) if best else {}
    for src, dst in effective_forced.items():
        links[str(src)] = str(dst)
    chains = list(best.chains) if best else []
    warnings = list(best.warnings) if best else []

    used_blanks = {i for i, n in enumerate(nodes) if not n.is_title and n.number in {b for c in chains for b in c.get("blanks", [])}}
    for i, n in enumerate(nodes):
        if not n.is_title and i not in used_blanks:
            suspicious.append({"number": n.number, "reason": "orphan_blank_not_linked", "severity": ANOMALY_CRITICAL})
    suspicious = _annotate_anomaly_severity(suspicious)
    if allowed_set is not None:
        for src_idx, edges in outgoing.items():
            for edge in edges:
                dst_num = nodes[edge.dst].number
                if not nodes[edge.dst].is_title and dst_num not in allowed_set:
                    suspicious.append({
                        "number": nodes[src_idx].number,
                        "reason": "foreign_blank_reference",
                        "referenced": dst_num,
                        "foreign": True,
                        "severity": ANOMALY_CRITICAL,
                    })

    manual_review_queue = _collect_manual_review_queue(
        nodes, outgoing, source_candidates, effective_forced,
        str(auditorium_id) if auditorium_id is not None else None,
        min_bayes_factor, min_log_margin,
        solutions=solutions,
        chains=chains,
        links=links,
        suspicious=suspicious,
        persisted_pending=persisted_pending,
    )
    pending_review_blanks = {
        item["blank"] for item in manual_review_queue if item.get("status") == "pending" and not item.get("resolved")
    }

    renames = {qr: f"{qr}-{nxt}" for qr, nxt in links.items()}
    edge_confidence = _build_edge_confidence_map(
        nodes, outgoing, links, forced_links, source_candidates,
    )
    chains = _enrich_chains_with_confidence(chains, edge_confidence, forced_links)
    warnings = _annotate_anomaly_severity(warnings)
    classified_anomalies = _split_classified_anomalies(suspicious, warnings, chains)
    manual_reviews = list(manual_review_queue)

    link_stats = _compute_link_statistics(
        links, forced_links, derived_links, resolved_reviews, manual_review_queue,
    )
    auditorium_confidence = _compute_auditorium_confidence(
        chains, manual_reviews, classified_anomalies, forced_links,
    )

    has_pending = bool(manual_reviews) or bool(
        [s for s in suspicious if s.get("severity") == ANOMALY_CRITICAL and s.get("reason") == "orphan_blank_not_linked"]
    )
    if has_pending:
        status = "NEEDS_OPERATOR"
    elif suspicious:
        status = "PARTIAL"
    else:
        status = "CLEAN"

    auditorium_status = _compute_auditorium_status(
        manual_reviews, forced_links, derived_links, classified_anomalies,
        status, len(resolved_reviews),
    )
    final_status = _legacy_final_status_from_auditorium(auditorium_status, manual_reviews)

    automatic_audit = _build_automatic_audit_entries(links, edge_confidence, forced_links, derived_links)
    stored_audit = load_audit_log(auditorium_id, audit_log_path) if auditorium_id is not None else []
    if persist_audit_log and auditorium_id is not None:
        append_audit_log(
            auditorium_id,
            {
                "decision_type": "auditorium_snapshot",
                "auditorium_status": auditorium_status,
                "auditorium_confidence": auditorium_confidence,
                "links": dict(links),
                "manual_reviews_count": len(manual_reviews),
                "automatic_links": link_stats.get("automatic_links", {}),
                "operator_fixed_links": {
                    src: dst for src, dst in links.items() if str(src) in forced_links
                },
                "entries": automatic_audit,
            },
            audit_log_path,
        )
        stored_audit = load_audit_log(auditorium_id, audit_log_path)

    links_meta = {
        str(src): {
            "dst": str(dst),
            "operator_fixed": str(src) in forced_links,
            "derived": str(src) in derived_links,
            **edge_confidence.get(str(src), {}),
        }
        for src, dst in links.items()
    }

    if persist_review_queue and auditorium_id is not None:
        save_manual_review_queue(
            auditorium_id,
            manual_review_queue,
            manual_review_queue_path,
            resolved=resolved_reviews,
        )

    sol_payload = [{"rank": s.rank, "links": s.links, "total_score": s.total_score, "joint_confidence_score": s.joint_confidence_score, "chains": list(s.chains)} for s in solutions]
    details = {
        "links": links,
        "links_meta": links_meta,
        "renames": renames,
        "chains": chains,
        "solutions": sol_payload,
        "best_solution_rank": 1 if best else None,
        "second_best": sol_payload[1] if len(sol_payload) > 1 else None,
        "third_best": sol_payload[2] if len(sol_payload) > 2 else None,
        "suspicious": suspicious,
        "warnings": warnings,
        "classified_anomalies": classified_anomalies,
        "manual_reviews": manual_reviews,
        "manual_review_queue": manual_review_queue,
        "status": status,
        "auditorium_status": auditorium_status,
        "final_status": final_status,
        "review_required": auditorium_status == AUDITORIUM_STATUS_MANUAL_REVIEW_REQUIRED,
        "force_links_applied": forced_links,
        "derived_links_applied": derived_links,
        "thresholds": {
            "min_bayes_factor": min_bayes_factor,
            "min_log_margin": min_log_margin,
        },
        "joint_confidence_score": best.joint_confidence_score if best else 0.0,
        "approx_clean_probability": auditorium_confidence,
        "auditorium_confidence": auditorium_confidence,
        "codebook_note": codebook_stats().note,
        "edge_confidence": edge_confidence,
        "manual_history": manual_history[-20:],
        "audit_log": stored_audit[-100:],
        "audit_trace": automatic_audit,
        "confidence_thresholds": {
            "auto_hide": CONFIDENCE_AUTO_HIDE,
            "optional_review": CONFIDENCE_OPTIONAL_REVIEW,
            "required_review": CONFIDENCE_REQUIRED_REVIEW,
        },
        **link_stats,
    }
    details["risk_assessment"] = assess_automation_risks(details, sum(1 for n in nodes if not n.is_title))
    return details if return_details else links


def make_probability_field(target: str, alphabet: str, correct_prob: float = 99.0) -> List[Dict[str, float]]:
    wrong = (100.0 - correct_prob) / (len(alphabet) - 1)
    out = []
    for char in target:
        probs = {c: wrong for c in alphabet}
        probs[char] = correct_prob
        out.append(probs)
    return out


def simulate_clean_chain(title: str, blanks: Sequence[str]) -> List[Dict[str, Any]]:
    if not blanks:
        return [{"type": "titul", "number": title, "veroytn": {"next": make_probability_field(title, BLANK_ALPHABET), "last": make_probability_field(title, BLANK_ALPHABET)}}]
    data = [{"type": "titul", "number": title, "veroytn": {"next": make_probability_field(blanks[0], BLANK_ALPHABET), "last": make_probability_field(blanks[-1], BLANK_ALPHABET)}}]
    for page, blank in enumerate(blanks, start=1):
        nxt = blanks[page] if page < len(blanks) else title
        data.append({"type": "blan1", "number": blank, "veroytn": make_probability_field(nxt, BLANK_ALPHABET)})
        data.append({"type": "blan2", "number": blank, "veroytn": make_probability_field(f"{page:03d}", PAGE_ALPHABET)})
    return data


if __name__ == "__main__":
    print(codebook_stats())
    codes = generate_hamming13_codes(size=10, min_distance=6)
    demo = simulate_clean_chain(codes[0], codes[1:4])
    print(json.dumps(process_auditorium_blanks(demo, return_details=True), ensure_ascii=False, indent=2))
