import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image


TARGET_CLASSES: List[int] = [0, 2, 3, 4, 5, 6, 7]
IDX_TO_CLASS: Dict[int, int] = {idx: cls for idx, cls in enumerate(TARGET_CLASSES)}
CLASS_TO_IDX: Dict[int, int] = {cls: idx for idx, cls in enumerate(TARGET_CLASSES)}

MNIST_MEAN = 0.1307
MNIST_STD = 0.3081


class ImprovedCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 16, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(16)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(32)
        self.fc1 = nn.Linear(32 * 7 * 7, 64)
        self.dropout = nn.Dropout(0.3)
        self.fc2 = nn.Linear(64, len(TARGET_CLASSES))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.pool(F.relu(self.bn1(self.conv1(x))))
        x = self.pool(F.relu(self.bn2(self.conv2(x))))
        x = x.view(-1, 32 * 7 * 7)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        return self.fc2(x)


@dataclass
class Candidate:
    name: str
    image28: np.ndarray
    tensor: torch.Tensor
    confidence: float = -1.0
    probs: torch.Tensor | None = None


def set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_model(weights_path: str, device: torch.device) -> ImprovedCNN:
    model = ImprovedCNN().to(device)
    state = torch.load(weights_path, map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model


def load_image(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.array(img)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def stretch_contrast(gray: np.ndarray) -> np.ndarray:
    lo = float(np.percentile(gray, 2))
    hi = float(np.percentile(gray, 98))
    if hi <= lo + 1e-6:
        return gray.copy()
    out = (gray.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_clahe(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _foreground_background_split(gray: np.ndarray) -> Tuple[float, float, np.ndarray]:
    border = np.concatenate([
        gray[0, :],
        gray[-1, :],
        gray[:, 0],
        gray[:, -1],
    ]).astype(np.float32)
    bg_level = float(np.median(border))

    diff = np.abs(gray.astype(np.float32) - bg_level).astype(np.uint8)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    fg_pixels = gray[mask > 0]
    if fg_pixels.size == 0:
        fg_level = 255.0 - bg_level
    else:
        fg_level = float(np.median(fg_pixels))

    return bg_level, fg_level, mask


def infer_invert(gray: np.ndarray) -> bool:
    bg_level, fg_level, mask = _foreground_background_split(gray)

    if np.count_nonzero(mask) == 0:
        return bg_level > 127.0

    return fg_level < bg_level


def detect_bbox(gray: np.ndarray) -> Tuple[int, int, int, int]:
    h, w = gray.shape[:2]

    border = np.concatenate([
        gray[0, :],
        gray[-1, :],
        gray[:, 0],
        gray[:, -1],
    ]).astype(np.float32)

    bg = float(np.median(border))
    diff = np.abs(gray.astype(np.float32) - bg).astype(np.uint8)

    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    if num_labels <= 1:
        return 0, 0, w, h

    best = 1
    best_area = 0
    for idx in range(1, num_labels):
        area = stats[idx, cv2.CC_STAT_AREA]
        if area > best_area:
            best_area = area
            best = idx

    x = stats[best, cv2.CC_STAT_LEFT]
    y = stats[best, cv2.CC_STAT_TOP]
    ww = stats[best, cv2.CC_STAT_WIDTH]
    hh = stats[best, cv2.CC_STAT_HEIGHT]

    if best_area < max(20, int(0.001 * h * w)):
        return 0, 0, w, h

    pad = int(max(2, 0.12 * max(ww, hh)))
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(w, x + ww + pad)
    y2 = min(h, y + hh + pad)

    if x2 <= x1 or y2 <= y1:
        return 0, 0, w, h

    return x1, y1, x2, y2


def crop_resize_to_28(gray: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = detect_bbox(gray)
    crop = gray[y1:y2, x1:x2]

    if crop.size == 0:
        crop = gray

    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        crop = gray
        h, w = crop.shape[:2]

    target = 20
    if h > w:
        new_h = target
        new_w = max(1, int(round(w * target / h)))
    else:
        new_w = target
        new_h = max(1, int(round(h * target / w)))

    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((28, 28), dtype=np.uint8)
    x_off = (28 - new_w) // 2
    y_off = (28 - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return canvas


def make_tensor(image28: np.ndarray) -> torch.Tensor:
    arr = image28.astype(np.float32) / 255.0
    arr = (arr - MNIST_MEAN) / MNIST_STD
    tensor = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)
    return tensor


def build_candidates(rgb: np.ndarray) -> Tuple[List[Candidate], bool, float, float]:
    gray = to_gray(rgb)

    should_invert = infer_invert(gray)
    bg_level, fg_level, _ = _foreground_background_split(gray)

    variants: List[Tuple[str, np.ndarray]] = []

    base = gray
    stretched = stretch_contrast(gray)
    clahe = apply_clahe(gray)
    clahe_stretched = stretch_contrast(clahe)

    for name, g in [
        ("gray", base),
        ("stretched", stretched),
        ("clahe", clahe),
        ("clahe_stretched", clahe_stretched),
    ]:
        prepared = 255 - g if should_invert else g
        prepared = cv2.GaussianBlur(prepared, (3, 3), 0)
        img28 = crop_resize_to_28(prepared)
        cand_name = f"{name}_{'inv' if should_invert else 'norm'}"
        variants.append((cand_name, img28))

    candidates: List[Candidate] = []
    for name, img28 in variants:
        tensor = make_tensor(img28)
        candidates.append(Candidate(name=name, image28=img28, tensor=tensor))

    return candidates, should_invert, bg_level, fg_level


def choose_best_candidate(model: ImprovedCNN, candidates: List[Candidate], device: torch.device) -> Candidate:
    batch = torch.cat([c.tensor for c in candidates], dim=0).to(device)

    with torch.inference_mode():
        logits = model(batch)
        probs = torch.softmax(logits, dim=1)

    for i, cand in enumerate(candidates):
        cand.probs = probs[i].detach().cpu()
        cand.confidence = float(cand.probs.max().item())

    best = max(candidates, key=lambda c: c.confidence)
    return best


def save_result_image(image28: np.ndarray, out_path: str = "result.jpg") -> None:
    enlarged = cv2.resize(image28, (280, 280), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(out_path, enlarged)


def probs_to_output(probs: torch.Tensor) -> Tuple[int, float, Dict[str, float]]:
    idx = int(torch.argmax(probs).item())
    predicted_digit = IDX_TO_CLASS[idx]
    confidence = float(probs[idx].item())

    all_probabilities: Dict[str, float] = {}
    for i, digit in IDX_TO_CLASS.items():
        all_probabilities[str(digit)] = float(probs[i].item())

    return predicted_digit, confidence, all_probabilities


def round_nested(obj, ndigits: int = 4):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: round_nested(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_nested(v, ndigits) for v in obj]
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Digit inference with robust preprocessing")
    parser.add_argument("image_path", help="Path to input image, for example 00.jpg")
    parser.add_argument("--weights", default="digit_model.pth", help="Path to model weights")
    parser.add_argument("--result", default="result.jpg", help="Path to save processed image")
    args = parser.parse_args()

    set_seed(42)

    if not os.path.exists(args.image_path):
        raise FileNotFoundError(f"Image not found: {args.image_path}")

    if not os.path.exists(args.weights):
        raise FileNotFoundError(f"Weights not found: {args.weights}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(args.weights, device)

    rgb = load_image(args.image_path)
    candidates, was_inverted, bg_level, fg_level = build_candidates(rgb)
    best = choose_best_candidate(model, candidates, device)
    assert best.probs is not None

    save_result_image(best.image28, args.result)

    predicted_digit, confidence, all_probabilities = probs_to_output(best.probs)

    output = {
        "predicted_digit": predicted_digit,
        "confidence": confidence,
        "all_probabilities": all_probabilities,
        "diagnostics": {
            "polarity_inverted": was_inverted,
            "background_brightness": bg_level,
            "foreground_brightness": fg_level,
            "selected_preprocessing": best.name,
        },
    }

    output = round_nested(output, ndigits=4)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()