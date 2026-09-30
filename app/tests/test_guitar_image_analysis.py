import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from ygc.guitar_image_analysis import compare_guitars, analyze_guitars
from ygc import config


def test_missing_detection_does_not_fall_back_to_whole_image():
    result = compare_guitars({"mask": None}, {"mask": None})
    assert result["status"] == "not_comparable"
    assert "appearance_similarity_percent" not in result


def test_matching_uses_only_the_detected_region():
    random = np.random.default_rng(4)
    first = random.integers(0, 256, (320, 320, 3), dtype=np.uint8)
    second = random.integers(0, 256, (320, 320, 3), dtype=np.uint8)
    second[60:260, 60:260] = first[60:260, 60:260]
    mask = np.zeros((320, 320), dtype=np.uint8)
    mask[60:260, 60:260] = 255
    embedding = np.array([1., 0., 0.])
    result = compare_guitars({"rgb": first, "mask": mask, "embedding": embedding},
                             {"rgb": second, "mask": mask, "embedding": embedding})
    assert result["status"] == "completed"
    assert result["appearance_similarity_percent"] == 100
    assert result["geometric_inliers"] >= 8
    assert result["local_feature_support_percent"] > 85


def test_missing_model_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    result = analyze_guitars(b"unused", b"unused", [])
    assert result["status"] == "unavailable"
    assert "download-model" in result["reason"]
