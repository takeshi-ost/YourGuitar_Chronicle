"""Read-only, local evidence experiments. Scores are not ownership probabilities."""
from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path


def _libraries():
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError('Install the authentication-test extra: pip install -e ".[authentication-test]"') from exc
    return cv2, np, Image, ImageOps


def decode_image(content: bytes, *, color: bool = False):
    cv2, np, Image, ImageOps = _libraries()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                    raise ValueError("Use JPEG, PNG, WebP, or GIF images")
                if image.width * image.height > 20_000_000:
                    raise ValueError("Image exceeds 20 megapixels")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2000, 2000))
                pixels = np.asarray(image)
                return pixels if color else cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image exceeds the safe decoding limit") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("Cannot decode image") from exc


def normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def read_text(gray):
    cv2, _, _, _ = _libraries()
    executable = shutil.which("tesseract")
    if not executable:
        return {"status": "unavailable", "reason": "Install the Tesseract executable (English language data required)", "words": []}
    try:
        with tempfile.TemporaryDirectory(prefix="ygc-auth-test-") as directory:
            source = Path(directory) / "image.png"
            cv2.imwrite(str(source), gray)
            result = subprocess.run([executable, str(source), "stdout", "-l", "eng", "--psm", "11", "tsv"],
                                    capture_output=True, text=True, timeout=20, check=True)
        words = []
        for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
            text = str(row.get("text") or "").strip()
            if text:
                words.append({"text": text, "confidence": round(float(row["conf"]), 1),
                              "box": [int(row[key]) for key in ("left", "top", "width", "height")]})
        return {"status": "completed", "text": " ".join(w["text"] for w in words), "words": words}
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError, OSError):
        return {"status": "unavailable", "reason": "Tesseract failed or timed out", "words": []}


def text_match(ocr: dict, expected: str) -> dict:
    wanted = normalized(expected)
    if not wanted:
        return {"status": "not_requested"}
    if ocr["status"] != "completed":
        return {"status": "unavailable"}
    tokens = [normalized(w["text"]) for w in ocr["words"] if normalized(w["text"])]
    # Compare complete tokens, allowing OCR to split a serial into several words.
    matched = any("".join(tokens[start:end]) == wanted
                  for start in range(len(tokens))
                  for end in range(start + 1, min(start + 8, len(tokens)) + 1))
    return {"status": "matched" if matched else "not_read", "expected": expected}


def texture_metrics(gray, ocr: dict) -> dict:
    cv2, np, _, _ = _libraries()
    mask = np.ones(gray.shape, dtype=bool)
    for word in ocr["words"]:
        x, y, width, height = word["box"]
        pad = 3
        mask[max(0, y-pad):y+height+pad, max(0, x-pad):x+width+pad] = False
    pixels = gray[mask]
    if pixels.size < 100:
        return {"status": "insufficient", "reason": "Too little non-text image area"}
    frequencies = np.bincount(pixels, minlength=256) / pixels.size
    positive = frequencies[frequencies > 0]
    entropy = float(-(positive * np.log2(positive)).sum())
    mean = cv2.blur(gray.astype(np.float32), (9, 9))
    variance = cv2.blur(gray.astype(np.float32) ** 2, (9, 9)) - mean ** 2
    flat = float((variance[mask] < 4).mean() * 100)
    simple = entropy < 1.5 and flat > 95
    return {"status": "completed", "non_text_entropy_bits": round(entropy, 2),
            "flat_area_percent": round(flat, 1),
            "screening": "very_simple_image" if simple else "not_obviously_flat",
            "note": "Experimental screening only; texture does not establish photographic authenticity."}


def compare_images(first, second) -> dict:
    cv2, np, _, _ = _libraries()
    def phash(gray):
        reduced = cv2.resize(gray, (32, 32)).astype(np.float32)
        low = cv2.dct(reduced)[:8, :8].ravel()[1:]
        return low > np.median(low)
    similarity = round(float((phash(first) == phash(second)).mean() * 100), 1)
    detector = cv2.SIFT_create(nfeatures=1800)
    ka, da = detector.detectAndCompute(first, None)
    kb, db = detector.detectAndCompute(second, None)
    output = {"phash_similarity_percent": similarity, "features_first": len(ka),
              "features_second": len(kb), "matches": 0, "geometric_inliers": 0,
              "feature_support_percent": None,
              "note": "Whole-image similarity, not a guitar identity probability. Background and text can match."}
    if da is None or db is None or len(da) < 8 or len(db) < 8:
        output["status"] = "insufficient_features"
        return output
    matches = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < .7 * pair[1].distance]
    output["matches"] = len(good)
    if len(good) < 8:
        output["status"] = "insufficient_correspondence"
        return output
    source = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    target = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, inliers = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
    count = int(inliers.sum()) if inliers is not None else 0
    output.update(status="completed", geometric_inliers=count,
                  feature_support_percent=round(100 * count / min(len(ka), len(kb)), 1))
    return output


def analyze_images(closeup: bytes, overview: bytes, challenge: str, serial: str,
                   references: list[tuple[str, bytes]] | None = None) -> dict:
    from ygc.guitar_image_analysis import analyze_guitars
    images = [decode_image(closeup), decode_image(overview)]
    results = []
    for name, gray in zip(("serial_closeup", "guitar_overview"), images):
        ocr = read_text(gray)
        results.append({"image": name, "dimensions": [gray.shape[1], gray.shape[0]],
                        "ocr": ocr, "challenge": text_match(ocr, challenge),
                        "serial": text_match(ocr, serial) if name == "serial_closeup" else {"status": "not_required"},
                        "texture": texture_metrics(gray, ocr)})
    compared = []
    for label, content in references or []:
        try:
            reference = decode_image(content)
            compared.append({"reference": label, "overview": compare_images(images[1], reference),
                             "closeup": compare_images(images[0], reference)})
        except ValueError:
            compared.append({"reference": label, "status": "unreadable"})
    return {"mode": "test_only", "images": results,
            "between_submitted_images": compare_images(*images),
            "reference_comparisons": compared,
            "guitar_analysis": analyze_guitars(closeup, overview, references or []),
            "forgery_detection": {"status": "not_implemented", "reason": "No TruFor or generated-image detector is installed"},
            "decision": "No approval or ownership change; these are uncalibrated diagnostic measurements."}
