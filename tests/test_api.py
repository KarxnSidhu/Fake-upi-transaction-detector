from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import database
import main


def make_test_png() -> bytes:
    image = Image.new("RGB", (480, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 80), "Payment successful", fill="black")
    draw.text((40, 130), "Paid to Test Merchant", fill="black")
    draw.text((40, 180), "UPI Ref No: 123456789012", fill="black")
    draw.text((40, 230), "20/11/2026 10:30 AM", fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_health_endpoint():
    with TestClient(main.app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["service"] == "UPI Shield"


def test_invalid_extension_is_rejected():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/analyze",
            data={"upi_app": "Google Pay"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 415


def test_invalid_image_content_is_rejected():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/analyze",
            data={"upi_app": "Google Pay"},
            files={"file": ("fake.png", b"not an image", "image/png")},
        )
    assert response.status_code == 400


def test_duplicate_image_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.sqlite3")
    database.init_db()
    content = make_test_png()

    with TestClient(main.app) as client:
        first = client.post(
            "/api/analyze",
            data={"upi_app": "Google Pay"},
            files={"file": ("payment.png", content, "image/png")},
        )
        second = client.post(
            "/api/analyze",
            data={"upi_app": "Google Pay"},
            files={"file": ("payment-again.png", content, "image/png")},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["checks"]["duplicate_image"]["detected"] is True
    assert second.json()["verdict"] == "SUSPICIOUS"
