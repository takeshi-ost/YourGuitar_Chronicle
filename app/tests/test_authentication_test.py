import io

import pytest

pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
from fastapi.testclient import TestClient
from ygc import config
from ygc.authentication_test import decode_image, compare_images, text_match, texture_metrics
from ygc.db.repository import Repository
from ygc.web import app, CONSOLE_ADMIN_TOKEN


def image_bytes(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    return stream.getvalue()


def test_text_matching_does_not_accept_serial_substrings():
    ocr = {"status": "completed", "words": [{"text": "AB12345"}, {"text": "Z9"}, {"text": "X7"}]}
    assert text_match(ocr, "12345")["status"] == "not_read"
    assert text_match(ocr, "AB12345")["status"] == "matched"
    assert text_match(ocr, "Z9-X7")["status"] == "matched"


def test_flat_image_and_duplicate_measurements():
    empty_ocr = {"words": []}
    flat = np.full((320, 320), 255, dtype=np.uint8)
    assert texture_metrics(flat, empty_ocr)["screening"] == "very_simple_image"
    texture = np.random.default_rng(71).integers(0, 256, (320, 320), dtype=np.uint8)
    assert texture_metrics(texture, empty_ocr)["screening"] == "not_obviously_flat"
    result = compare_images(texture, texture.copy())
    assert result["phash_similarity_percent"] == 100
    assert result["geometric_inliers"] > 8
    assert result["feature_support_percent"] == 100
    assert compare_images(flat, flat)["feature_support_percent"] is None
    with pytest.raises(ValueError):
        decode_image(b"not an image")


def test_admin_endpoint_is_read_only_and_handles_unavailable_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("ygc.authentication_test.shutil.which", lambda _: None)
    repository = Repository(config.DB_PATH)
    repository.init_db()
    repository.create_user("Test")
    image = image_bytes(np.full((200, 200), 200, dtype=np.uint8))
    files = {"serial_closeup": ("closeup.png", image, "image/png"),
             "guitar_overview": ("overview.png", image, "image/png")}
    payload = {"challenge": "TEST1234", "serial": "ABC123"}
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345)) as client:
        assert client.post("/api/admin/authentication-test", data=payload, files=files).status_code == 403
        headers = {"X-YGC-Console-Admin": CONSOLE_ADMIN_TOKEN}
        before = repository.stats()
        response = client.post("/api/admin/authentication-test", data=payload, files=files, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["mode"] == "test_only"
        assert result["images"][0]["challenge"]["status"] == "unavailable"
        assert result["guitar_identity"]["status"] == "not_implemented"
        assert repository.stats() == before
        invalid = {**files, "serial_closeup": ("bad.png", b"invalid", "image/png")}
        assert client.post("/api/admin/authentication-test", data=payload, files=invalid, headers=headers).status_code == 400
        assert client.get("/").status_code == 200
        assert 'id="authentication-test"' in client.get("/").text
