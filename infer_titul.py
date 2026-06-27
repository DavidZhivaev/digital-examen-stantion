"""
Домашний инференс титульного листа без сканера.

Пример:
    python infer_titul.py scan.png
    python infer_titul.py scan.jpg --out-dir titul_debug
    python infer_titul.py already_cropped.png --skip-align
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from blank_processor import process_scanned_blank
from digit_inference import (
    build_candidates,
    round_nested,
    save_result_image,
    set_seed,
)
from field_regions import FIELD_LAYOUT, cell_to_pixels
from recognizer import BLANK_ALPHABET, PAGE_ALPHABET, Recognizer, _is_empty_cell

BASE_DIR = Path(__file__).parent
WEIGHTS_PATH = BASE_DIR / "digit_model.pth"

FIELD_LABELS = {
    "next": ("next_blank", BLANK_ALPHABET),
    "last": ("last_blank", BLANK_ALPHABET),
    "count": ("blank_count", PAGE_ALPHABET),
}


def _load_config() -> dict:
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_rgb(path: Path, rgb) -> None:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr)


def run_titul_inference(
    image_path: str,
    weights_path: str = str(WEIGHTS_PATH),
    out_dir: str = "titul_debug",
    *,
    skip_align: bool = False,
) -> dict:
    set_seed(42)

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights not found: {weights_path}")

    out = Path(out_dir)
    crops_dir = out / "crops"
    processed_dir = out / "processed"
    crops_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    raw_pil = Image.open(image_path).convert("RGB")
    align_info: dict = {"aligned": False, "reason": "skip_align" if skip_align else ""}

    if skip_align:
        work_pil = raw_pil
    else:
        processed = process_scanned_blank(raw_pil, _load_config())
        align_info = {
            "aligned": processed.visible and processed.image is not None,
            "reason": processed.reason,
            "marker_count": processed.marker_count,
            "has_qr": processed.has_qr,
            "type_code": processed.qr_info.type_code if processed.qr_info else "",
        }
        if not processed.visible or processed.image is None:
            raise RuntimeError(
                "Не удалось выровнять изображение по маркерам. "
                f"{processed.reason}. "
                "Убедитесь, что на скане видны 4 угловых маркера (для титульника — 6). "
                "Если изображение уже обрезано станцией, запустите с --skip-align."
            )
        work_pil = processed.image

    rgb = np.asarray(work_pil)
    h, w = rgb.shape[:2]
    _save_rgb(out / "aligned.png", rgb)

    recognizer = Recognizer()
    result = recognizer.recognize(work_pil, blank_type="titul")

    raw_cells = result.raw_data.get("cells", [])
    cells_output = []
    global_idx = 0

    for field_key, cells in FIELD_LAYOUT["titul"].items():
        label, alphabet = FIELD_LABELS[field_key]
        veroytn_field: list = []
        if isinstance(result.veroytn, dict):
            veroytn_field = result.veroytn.get(field_key, [])

        for local_i, cell in enumerate(cells):
            x1, y1, x2, y2 = cell_to_pixels(
                cell, w, h, crop_margin_ratio=recognizer._crop_margin_ratio,
            )
            crop = rgb[y1:y2, x1:x2]
            empty = crop.size == 0 or _is_empty_cell(crop)

            entry: dict = {
                "field": label,
                "index": local_i,
                "global_index": global_idx,
                "is_empty": empty,
            }

            raw_path = crops_dir / f"{label}_{local_i:02d}_raw.png"
            _save_rgb(raw_path, crop if crop.size else rgb[:1, :1])
            entry["crop_path"] = str(raw_path.resolve())

            raw_cell = raw_cells[global_idx] if global_idx < len(raw_cells) else {}

            if empty:
                entry["digit"] = ""
                entry["confidence"] = 0.0
                entry["all_probabilities"] = {}
            else:
                # Preprocessing images (CPU only — no model call, result already computed).
                candidates, was_inv, bg, fg = build_candidates(crop)
                best_name = raw_cell.get("preprocessing", "")
                best_cand = next((c for c in candidates if c.name == best_name), candidates[0])

                proc_path = processed_dir / f"{label}_{local_i:02d}_proc.jpg"
                save_result_image(best_cand.image28, str(proc_path))

                entry["digit"] = raw_cell.get("digit", "")
                entry["confidence"] = raw_cell.get("confidence", 0.0)
                entry["all_probabilities"] = (
                    veroytn_field[local_i] if local_i < len(veroytn_field) else {}
                )
                entry["processed_path"] = str(proc_path.resolve())
                entry["diagnostics"] = {
                    "polarity_inverted": was_inv,
                    "background_brightness": bg,
                    "foreground_brightness": fg,
                    "selected_preprocessing": best_name,
                }

            if local_i < len(veroytn_field):
                entry["field_probabilities"] = veroytn_field[local_i]

            cells_output.append(entry)
            global_idx += 1

    def _decode(key: str) -> str:
        if not isinstance(result.veroytn, dict):
            return ""
        field = result.veroytn.get(key)
        if not isinstance(field, list):
            return ""
        _, alphabet = FIELD_LABELS[key]
        chars = []
        for pos in field:
            if isinstance(pos, dict):
                chars.append(max(alphabet, key=lambda c: float(pos.get(c, 0.0))))
        return "".join(chars)

    output = {
        "success": result.success,
        "confidence": result.confidence,
        "fields": {
            "next_blank": _decode("next"),
            "last_blank": _decode("last"),
            "blank_count": _decode("count"),
        },
        "veroytn": result.veroytn,
        "cells": cells_output,
        "diagnostics": {
            "image_size": [w, h],
            "source_image": str(Path(image_path).resolve()),
            "alignment": align_info,
            "aligned_image": str((out / "aligned.png").resolve()),
            "weights": str(Path(weights_path).resolve()),
            "out_dir": str(out.resolve()),
        },
    }

    summary_path = out / "result.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(round_nested(output, ndigits=4), f, ensure_ascii=False, indent=2)
    output["diagnostics"]["result_json"] = str(summary_path.resolve())

    return round_nested(output, ndigits=4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Инференс титульного листа по изображению с ПК")
    parser.add_argument("image_path", help="Путь к PNG/JPG скана титульника")
    parser.add_argument("--weights", default=str(WEIGHTS_PATH), help="Путь к digit_model.pth")
    parser.add_argument("--out-dir", default="titul_debug", help="Папка для crops/processed/result.json")
    parser.add_argument(
        "--skip-align",
        action="store_true",
        help="Не выравнивать по маркерам (если изображение уже обрезано станцией)",
    )
    args = parser.parse_args()

    output = run_titul_inference(
        args.image_path,
        args.weights,
        args.out_dir,
        skip_align=args.skip_align,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
