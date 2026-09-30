"""Local guitar segmentation and masked similarity, separate from photo diagnostics."""
from __future__ import annotations

import argparse
import base64
import io
import threading
from functools import lru_cache

from ygc import config

MODEL_ID = "CIDAS/clipseg-rd64-refined"
MODEL_REVISION = "999e0328d9e10b484360c477313983f9afdd7050"
LOCK = threading.RLock()


def model_directory():
    return config.DATA_DIR / "models" / "clipseg-guitar"


def download_model():
    from transformers import CLIPSegProcessor, CLIPSegForImageSegmentation
    directory = model_directory()
    processor = CLIPSegProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION, use_fast=False)
    model = CLIPSegForImageSegmentation.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, use_safetensors=True, trust_remote_code=False)
    directory.mkdir(parents=True, exist_ok=True)
    processor.save_pretrained(directory)
    model.save_pretrained(directory, safe_serialization=True)
    print(f"Saved pinned CLIPSeg model to {directory}")


@lru_cache(maxsize=1)
def load_model(directory: str):
    import torch
    from transformers import CLIPSegProcessor, CLIPSegForImageSegmentation
    torch.set_num_threads(4)
    processor = CLIPSegProcessor.from_pretrained(directory, local_files_only=True, use_fast=False)
    model = CLIPSegForImageSegmentation.from_pretrained(
        directory, local_files_only=True, use_safetensors=True, trust_remote_code=False).eval()
    return torch, processor, model


def detect_guitar(rgb, runtime):
    import cv2
    import numpy as np
    from PIL import Image
    torch, processor, model = runtime
    inputs = processor(text=["a guitar"], images=[Image.fromarray(rgb)], return_tensors="pt")
    with torch.inference_mode():
        probabilities = torch.sigmoid(model(**inputs).logits)[0].cpu().numpy()
    probabilities = cv2.resize(probabilities, (rgb.shape[1], rgb.shape[0]))
    candidate = (probabilities >= .5).astype(np.uint8)
    count, components, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    if count < 2:
        return {"status": "not_detected", "reason": "No region exceeded the guitar segmentation threshold"}, None, None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (components == largest).astype(np.uint8) * 255
    fraction = float((mask > 0).mean())
    if fraction < .003 or fraction > .95:
        return {"status": "not_detected", "reason": "The candidate region is too small or covers almost the whole image"}, None, None
    x, y, width, height, area = [int(v) for v in stats[largest]]
    crop = rgb[y:y+height, x:x+width].copy()
    cropped_mask = mask[y:y+height, x:x+width]
    crop[cropped_mask == 0] = 128
    preview = Image.fromarray(crop)
    preview.thumbnail((320, 320))
    buffer = io.BytesIO()
    preview.save(buffer, format="PNG")
    image_input = processor(images=Image.fromarray(crop), return_tensors="pt")
    with torch.inference_mode():
        embedding = model.clip.get_image_features(pixel_values=image_input["pixel_values"])[0].cpu().numpy()
    embedding = embedding / max(float(np.linalg.norm(embedding)), 1e-8)
    result = {"status": "detected", "box": [x, y, width, height],
              "region_area_percent": round(fraction * 100, 1),
              "mean_region_response": round(float(probabilities[mask > 0].mean()), 3),
              "preview": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}
    return result, mask, embedding


def compare_guitars(first, second):
    import cv2
    import numpy as np
    if first["mask"] is None or second["mask"] is None:
        return {"status": "not_comparable", "reason": "A guitar region could not be detected in both images"}
    similarity = max(0., min(100., 100 * float(np.dot(first["embedding"], second["embedding"]))))
    sift = cv2.SIFT_create(nfeatures=1800)
    features = []
    for item in (first, second):
        gray = cv2.cvtColor(item["rgb"], cv2.COLOR_RGB2GRAY)
        mask = cv2.erode(item["mask"], np.ones((5, 5), np.uint8))
        features.append(sift.detectAndCompute(gray, mask))
    (ka, da), (kb, db) = features
    result = {"status": "insufficient_features", "appearance_similarity_percent": round(similarity, 1),
              "local_feature_support_percent": None, "geometric_inliers": 0,
              "features_first": len(ka), "features_second": len(kb)}
    if da is None or db is None or min(len(ka), len(kb)) < 8:
        return result
    pairs = cv2.BFMatcher().knnMatch(da, db, k=2)
    candidates = sorted([p[0] for p in pairs if len(p) == 2 and p[0].distance < .7 * p[1].distance], key=lambda m: m.distance)
    used = set()
    good = []
    for match in candidates:
        if match.trainIdx not in used:
            good.append(match)
            used.add(match.trainIdx)
    result["status"] = "insufficient_correspondence"
    if len(good) < 8:
        return result
    points_a = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    points_b = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, inliers = cv2.findHomography(points_a, points_b, cv2.RANSAC, 4.)
    count = int(inliers.sum()) if inliers is not None else 0
    result.update(status="completed" if count >= 8 else "insufficient_correspondence",
                  geometric_inliers=count,
                  local_feature_support_percent=round(100 * count / min(len(ka), len(kb)), 1) if count >= 8 else None)
    return result


def analyze_guitars(closeup: bytes, overview: bytes, references: list[tuple[str, bytes]]):
    from ygc.authentication_test import decode_image
    explanation = ("Guitar-region measurements only. Appearance can be similar for different guitars of the same model; "
                   "scores are not identity probabilities. Segmentation may omit parts or include background.")
    directory = model_directory()
    if not (directory / "model.safetensors").is_file():
        return {"status": "unavailable", "reason": "Prepare the local model: python -m ygc.guitar_image_analysis --download-model"}
    with LOCK:
        try:
            runtime = load_model(str(directory))
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            return {"status": "unavailable", "reason": "Install the guitar-detection extra and prepare its local model", "detail": type(exc).__name__}
        detected = []
        comparisons = []
        internal = []
        for label, content in [("Serial close-up", closeup), ("Guitar overview", overview), *references]:
            try:
                rgb = decode_image(content, color=True)
                result, mask, embedding = detect_guitar(rgb, runtime)
                detected.append({"image": label, **result})
                internal.append({"rgb": rgb, "mask": mask, "embedding": embedding})
            except ValueError:
                detected.append({"image": label, "status": "unreadable"})
                internal.append({"mask": None})
        comparisons.append({"pair": "Close-up vs overview", **compare_guitars(internal[0], internal[1])})
        for index, (label, _) in enumerate(references, 2):
            comparisons.append({"pair": f"Overview vs {label}", **compare_guitars(internal[1], internal[index])})
        return {"status": "completed", "model": MODEL_ID, "revision": MODEL_REVISION,
                "detections": detected, "comparisons": comparisons, "note": explanation}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-model", action="store_true", required=True)
    parser.parse_args()
    download_model()
