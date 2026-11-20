"""Image-forensics and OCR pipeline for the UPI Shield prototype.

The checks are explainable heuristics, not proof of payment or a trained fraud
classifier. A missing reference set or OCR engine is reported as unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import warnings
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output

from database import save_scan_and_check_duplicates

logger = logging.getLogger("upi_shield.detector")
BASE_DIR = Path(__file__).resolve().parent
REFERENCE_ROOT = Path(
    os.getenv("UPI_SHIELD_REFERENCE_DIR", str(BASE_DIR / "data" / "reference_templates"))
)
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_SIDE = 10_000
MAX_ANALYSIS_SIDE = 1_800
INDIA_TZ = ZoneInfo("Asia/Kolkata")

if os.getenv("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]

APP_TEMPLATE_DIRS = {
    "Google Pay": "google_pay",
    "PhonePe": "phonepe",
    "Paytm": "paytm",
}

SUCCESS_RE = re.compile(
    r"\b(?:paid|payment\s+(?:successful|completed)|successfully\s+paid|"
    r"sent\s+successfully|transaction\s+successful|paid\s+to)\b",
    re.IGNORECASE,
)

TRANSACTION_PATTERNS = [
    re.compile(
        r"\b(?:UPI\s*)?(?:transaction\s*(?:id|no\.?|number|ref(?:erence)?)|"
        r"txn\s*(?:id|no\.?|ref)?|reference\s*(?:id|no\.?|number)|"
        r"ref(?:erence)?\s*(?:id|no\.?|number)|UTR)\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9/\-]{5,29})\b",
        re.IGNORECASE,
    ),
]

DATE_PATTERNS = [
    re.compile(r"\b(?:20\d{2})[/.\-](?:\d{1,2})[/.\-](?:\d{1,2})\b"),
    re.compile(r"\b(?:\d{1,2})[/.\-](?:\d{1,2})[/.\-](?:20\d{2}|\d{2})\b"),
    re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\s+20\d{2}\b",
        re.IGNORECASE,
    ),
]
TIME_PATTERN = re.compile(
    r"\b(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(AM|PM)?\b",
    re.IGNORECASE,
)

DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",
    "%d %b %Y", "%d %B %Y",
)


def decode_image(content: bytes) -> tuple[np.ndarray, str]:
    """Validate and decode an uploaded image, applying EXIF orientation."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(__import__("io").BytesIO(content)) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise ValueError("Only PNG and JPG/JPEG screenshots are supported.")
                source.verify()

            with Image.open(__import__("io").BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                width, height = image.size
                if width < 120 or height < 200:
                    raise ValueError("Image is too small to analyse. Upload a full screenshot.")
                if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
                    raise ValueError("Image dimensions are too large.")
                if width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image contains too many pixels.")

                if max(width, height) > MAX_ANALYSIS_SIDE:
                    scale = MAX_ANALYSIS_SIDE / max(width, height)
                    image = image.resize(
                        (max(1, int(width * scale)), max(1, int(height * scale))),
                        Image.Resampling.LANCZOS,
                    )

                rgb = np.asarray(image)
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                original_size = f"{width} × {height}"
                return bgr, original_size

    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("The uploaded file is not a valid or safe image.") from None


def preprocess_image(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Create a normalized grayscale image for OCR and forensic checks."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    # Light denoising retains glyph edges while reducing screenshot compression noise.
    denoised = cv2.medianBlur(enhanced, 3)
    return gray, denoised


def run_ocr(gray: np.ndarray) -> dict[str, Any]:
    """Extract text and word bounding boxes. Missing Tesseract is non-fatal."""
    if not shutil.which(str(pytesseract.pytesseract.tesseract_cmd)) and not Path(
        str(pytesseract.pytesseract.tesseract_cmd)
    ).exists():
        return {
            "status": "unavailable",
            "text": "",
            "words": [],
            "message": "Tesseract OCR is not installed or not available on PATH.",
        }

    try:
        data = pytesseract.image_to_data(
            gray,
            output_type=Output.DICT,
            config="--oem 3 --psm 6",
            timeout=2.5,
        )
        words: list[dict[str, Any]] = []
        text_parts: list[str] = []

        for index, raw_word in enumerate(data.get("text", [])):
            word = str(raw_word).strip()
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError, KeyError):
                confidence = -1.0

            if not word or confidence < 0:
                continue

            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            if width <= 0 or height <= 0:
                continue

            item = {
                "text": word,
                "confidence": confidence,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "block": int(data["block_num"][index]),
                "paragraph": int(data["par_num"][index]),
                "line": int(data["line_num"][index]),
            }
            words.append(item)
            text_parts.append(word)

        # Reconstruct OCR text by grouping words in reading order.
        lines: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for word in words:
            key = (word["block"], word["paragraph"], word["line"])
            lines.setdefault(key, []).append(word)

        ordered_lines = []
        for line_words in lines.values():
            line_words.sort(key=lambda item: item["left"])
            ordered_lines.append(" ".join(item["text"] for item in line_words))

        return {
            "status": "available",
            "text": "\n".join(ordered_lines)[:8000],
            "words": words,
            "message": None,
        }
    except pytesseract.TesseractNotFoundError:
        return {
            "status": "unavailable",
            "text": "",
            "words": [],
            "message": "Tesseract OCR could not be started.",
        }
    except RuntimeError as exc:
        logger.warning("OCR did not finish: %s", exc)
        return {
            "status": "timeout",
            "text": "",
            "words": [],
            "message": "OCR timed out. Try a clearer or smaller screenshot.",
        }
    except Exception as exc:  # OCR library can raise platform-specific errors.
        logger.warning("OCR unavailable: %s", exc)
        return {
            "status": "error",
            "text": "",
            "words": [],
            "message": "OCR could not read this screenshot.",
        }


def extract_transaction_id(text: str) -> str | None:
    """Extract an ID only when it is explicitly associated with a UTR/ref label."""
    normalized = re.sub(r"[\r\t]+", " ", text)
    for pattern in TRANSACTION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            candidate = re.sub(r"[^A-Z0-9]", "", match.group(1).upper())
            if 6 <= len(candidate) <= 30:
                return candidate
    return None


def validate_timestamp(text: str) -> dict[str, Any]:
    """Validate readable date/time values, including impossible and future times."""
    date_match = None
    for pattern in DATE_PATTERNS:
        date_match = pattern.search(text)
        if date_match:
            break

    time_match = TIME_PATTERN.search(text)
    if not date_match or not time_match:
        missing = []
        if not date_match:
            missing.append("date")
        if not time_match:
            missing.append("time")
        return {
            "status": "not_detected",
            "timestamp": None,
            "is_future": False,
            "reason": "Could not confidently extract the " + " and ".join(missing) + ".",
        }

    date_text = date_match.group(0)
    time_text = time_match.group(0)
    parsed_date: date | None = None
    for fmt in DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(date_text, fmt).date()
            break
        except ValueError:
            continue

    if parsed_date is None:
        return {
            "status": "invalid",
            "timestamp": f"{date_text} {time_text}",
            "is_future": False,
            "reason": "The detected date is not a valid calendar date.",
        }

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    second = int(time_match.group(3) or 0)
    meridiem = (time_match.group(4) or "").upper()

    if minute > 59 or second > 59:
        valid_time = False
    elif meridiem:
        valid_time = 1 <= hour <= 12
        if valid_time:
            hour = hour % 12 + (12 if meridiem == "PM" else 0)
    else:
        valid_time = 0 <= hour <= 23

    if not valid_time:
        return {
            "status": "invalid",
            "timestamp": f"{date_text} {time_text}",
            "is_future": False,
            "reason": "The detected time is outside the valid clock range.",
        }

    try:
        transaction_datetime = datetime.combine(
            parsed_date, time(hour, minute, second), tzinfo=INDIA_TZ
        )
    except ValueError:
        return {
            "status": "invalid",
            "timestamp": f"{date_text} {time_text}",
            "is_future": False,
            "reason": "The detected date/time combination is invalid.",
        }

    now = datetime.now(INDIA_TZ)
    is_future = transaction_datetime > now + timedelta(minutes=5)
    if is_future:
        reason = "The detected transaction timestamp is more than five minutes in the future."
        status = "future"
    else:
        reason = "Date and time are syntactically valid. This does not prove the payment occurred."
        status = "valid"

    return {
        "status": status,
        "timestamp": transaction_datetime.isoformat(),
        "is_future": is_future,
        "reason": reason,
    }


def analyze_typography(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimate same-line OCR box-height consistency, not actual font identity."""
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for word in words:
        key = (word["block"], word["paragraph"], word["line"])
        grouped.setdefault(key, []).append(word)

    lines_checked = 0
    flagged_lines = 0
    for line_words in grouped.values():
        if len(line_words) < 4:
            continue
        heights = np.array([item["height"] for item in line_words], dtype=float)
        median_height = float(np.median(heights))
        if median_height <= 0:
            continue
        lines_checked += 1
        ratio = float(np.max(heights) / max(1.0, np.min(heights)))
        variation = float(np.std(heights) / max(1.0, np.mean(heights)))
        # A deliberately conservative threshold: headings and mixed-size lines
        # are common, so one unusual line alone is not considered strong evidence.
        if ratio >= 2.2 and variation >= 0.38:
            flagged_lines += 1

    suspicious = lines_checked >= 2 and flagged_lines >= 2
    return {
        "status": "analysed" if lines_checked else "insufficient_text",
        "lines_checked": lines_checked,
        "flagged_lines": flagged_lines,
        "suspicious": suspicious,
        "method": "OCR word-box height variation within the same text line",
        "note": "This is a layout heuristic, not reliable font-family identification.",
    }


def analyze_pixel_anomalies(
    gray: np.ndarray,
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find unusually different high-frequency patches while excluding OCR text.

    Local compression, icons, gradients and screenshots from different devices
    can all change this metric. It is therefore a weak signal only.
    """
    height, width = gray.shape[:2]
    if height < 256 or width < 160:
        return {
            "status": "insufficient_image",
            "patches_checked": 0,
            "anomalous_patches": 0,
            "suspicious": False,
        }

    text_mask = np.zeros_like(gray, dtype=np.uint8)
    for word in words:
        x1 = max(0, word["left"] - 3)
        y1 = max(0, word["top"] - 3)
        x2 = min(width, word["left"] + word["width"] + 3)
        y2 = min(height, word["top"] + word["height"] + 3)
        if x2 > x1 and y2 > y1:
            text_mask[y1:y2, x1:x2] = 255

    background_mask = cv2.bitwise_not(text_mask)
    residual = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 1.2))
    patch_size = 64
    measurements: list[float] = []

    for y in range(0, height - patch_size + 1, patch_size):
        for x in range(0, width - patch_size + 1, patch_size):
            mask_patch = background_mask[y:y + patch_size, x:x + patch_size]
            if float(np.mean(mask_patch > 0)) < 0.72:
                continue
            values = residual[y:y + patch_size, x:x + patch_size][mask_patch > 0]
            if values.size < 100:
                continue
            measurements.append(float(np.std(values)))

    if len(measurements) < 8:
        return {
            "status": "insufficient_background_patches",
            "patches_checked": len(measurements),
            "anomalous_patches": 0,
            "suspicious": False,
        }

    values = np.asarray(measurements, dtype=float)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    robust_scale = max(1.0, 1.4826 * mad)
    z_scores = (values - median) / robust_scale
    anomalous = int(np.sum((z_scores > 4.5) & (values > median + 4.0)))
    suspicious = anomalous >= 3 and anomalous / len(values) >= 0.08

    return {
        "status": "analysed",
        "patches_checked": len(measurements),
        "anomalous_patches": anomalous,
        "suspicious": suspicious,
        "method": "robust outlier scan of local high-frequency residual variation",
        "note": "A pixel outlier is not proof of editing; UI elements and compression can cause outliers.",
    }


def compare_app_layout(image_bgr: np.ndarray, upi_app: str) -> dict[str, Any]:
    """Compare the image with curated screenshots for the selected UPI app.

    References must be supplied by the project team. The function never uses
    another app's templates and reports 'missing_reference' when none exist.
    """
    template_folder = REFERENCE_ROOT / APP_TEMPLATE_DIRS[upi_app]
    extensions = {".png", ".jpg", ".jpeg"}
    templates = sorted(
        path for path in template_folder.glob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ) if template_folder.exists() else []

    if not templates:
        return {
            "status": "missing_reference",
            "templates_checked": 0,
            "best_inlier_ratio": None,
            "good_matches": 0,
            "suspicious": False,
            "note": f"No approved {upi_app} reference screenshots are configured.",
        }

    target_gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=1800, scaleFactor=1.2, nlevels=8)
    target_keypoints, target_descriptors = orb.detectAndCompute(target_gray, None)
    if target_descriptors is None or len(target_keypoints) < 8:
        return {
            "status": "inconclusive",
            "templates_checked": len(templates),
            "best_inlier_ratio": None,
            "good_matches": 0,
            "suspicious": False,
            "note": "Not enough visual features for a reliable layout comparison.",
        }

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    results: list[tuple[float, int]] = []

    for template_path in templates:
        reference = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if reference is None:
            continue
        ratio_difference = abs(
            (reference.shape[1] / reference.shape[0]) -
            (target_gray.shape[1] / target_gray.shape[0])
        )
        if ratio_difference > 0.12:
            continue

        ref_keypoints, ref_descriptors = orb.detectAndCompute(reference, None)
        if ref_descriptors is None or len(ref_keypoints) < 8:
            continue

        try:
            pairs = matcher.knnMatch(ref_descriptors, target_descriptors, k=2)
        except cv2.error:
            continue
        good = [first for pair in pairs if len(pair) == 2
                for first, second in [pair] if first.distance < 0.75 * second.distance]

        if len(good) < 8:
            results.append((0.0, len(good)))
            continue

        source_points = np.float32(
            [ref_keypoints[item.queryIdx].pt for item in good]
        ).reshape(-1, 1, 2)
        target_points = np.float32(
            [target_keypoints[item.trainIdx].pt for item in good]
        ).reshape(-1, 1, 2)

        try:
            _, mask = cv2.findHomography(
                source_points, target_points, cv2.RANSAC, 5.0
            )
        except cv2.error:
            mask = None

        inliers = int(mask.sum()) if mask is not None else 0
        inlier_ratio = inliers / max(1, len(good))
        results.append((inlier_ratio, len(good)))

    if not results:
        return {
            "status": "inconclusive",
            "templates_checked": len(templates),
            "best_inlier_ratio": None,
            "good_matches": 0,
            "suspicious": False,
            "note": "No reference screenshot with a comparable aspect ratio was usable.",
        }

    best_ratio, best_matches = max(results, key=lambda item: item[0])
    enough_evidence = best_matches >= 18
    suspicious = enough_evidence and best_ratio < 0.18
    status = "mismatch_signal" if suspicious else (
        "similar_structure_signal" if enough_evidence else "inconclusive"
    )

    return {
        "status": status,
        "templates_checked": len(templates),
        "best_inlier_ratio": round(best_ratio, 3),
        "good_matches": best_matches,
        "suspicious": suspicious,
        "note": (
            "Visual structure differs substantially from the closest configured reference."
            if suspicious else
            "A structural match signal was found; this does not establish authenticity."
            if enough_evidence else
            "Too few stable visual features for a confident comparison."
        ),
    }


def _transaction_hash(transaction_id: str | None) -> str | None:
    if not transaction_id:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", transaction_id.upper())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _score_and_verdict(signals: dict[str, Any]) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []

    if signals["duplicate_image"]:
        score += 65
        reasons.append("This exact image has been submitted before on this installation.")
    if signals["duplicate_transaction"]:
        score += 60
        reasons.append("This transaction/reference ID has appeared in an earlier scan.")
    if signals["timestamp"]["status"] in {"invalid", "future"}:
        score += 35
        reasons.append(signals["timestamp"]["reason"])
    elif signals["timestamp"]["status"] == "not_detected":
        score += 8
        reasons.append(signals["timestamp"]["reason"])
    if signals["layout"]["suspicious"]:
        score += 20
        reasons.append("The screenshot layout differs from the configured app reference set.")
    elif signals["layout"]["status"] == "missing_reference":
        score += 8
        reasons.append("App-specific layout comparison was not performed because no reference screenshots are configured.")
    if not signals["transaction_id_found"]:
        score += 8
        reasons.append("No clearly labelled transaction/reference ID was extracted; check the details manually.")
    if signals["typography"]["suspicious"]:
        score += 12
        reasons.append("Unusual text-box height variation was found within multiple OCR lines.")
    if signals["pixels"]["suspicious"]:
        score += 10
        reasons.append("Some image patches have unusually different high-frequency texture.")
    if signals["ocr_status"] != "available":
        score += 15
        reasons.append("OCR was unavailable or incomplete, so key payment details could not be checked.")
    elif not signals["success_text_found"]:
        score += 10
        reasons.append("No clear payment-success wording was detected in the extracted text.")

    score = min(100, score)
    strong_signal = signals["duplicate_image"] or signals["duplicate_transaction"]
    if score >= 50 or strong_signal:
        verdict = "SUSPICIOUS"
    elif score >= 8:
        verdict = "NEEDS MANUAL CHECK"
    else:
        verdict = "NO OBVIOUS ANOMALY DETECTED"

    if not reasons:
        reasons.append(
            "No major anomaly was detected by the available checks. This is not proof of payment."
        )
    return score, verdict, reasons


def analyze_screenshot(content: bytes, upi_app: str) -> dict[str, Any]:
    """Run the full prototype analysis and persist duplicate-detection metadata."""
    image_bgr, image_size = decode_image(content)
    gray, enhanced = preprocess_image(image_bgr)
    ocr = run_ocr(enhanced)
    text = ocr["text"]
    transaction_id = extract_transaction_id(text)
    timestamp = validate_timestamp(text) if text else {
        "status": "not_detected",
        "timestamp": None,
        "is_future": False,
        "reason": "OCR did not provide text for timestamp validation.",
    }
    typography = analyze_typography(ocr["words"])
    pixels = analyze_pixel_anomalies(gray, ocr["words"])
    layout = compare_app_layout(image_bgr, upi_app)
    success_text_found = bool(SUCCESS_RE.search(text)) if text else False

    image_hash = hashlib.sha256(content).hexdigest()
    duplicate_info = save_scan_and_check_duplicates(
        image_sha256=image_hash,
        transaction_hash=_transaction_hash(transaction_id),
        upi_app=upi_app,
        verdict="PENDING",
        risk_score=0,
    )

    signals = {
        "duplicate_image": duplicate_info["duplicate_image"],
        "duplicate_transaction": duplicate_info["duplicate_transaction"],
        "timestamp": timestamp,
        "layout": layout,
        "typography": typography,
        "pixels": pixels,
        "ocr_status": ocr["status"],
        "success_text_found": success_text_found,
        "transaction_id_found": transaction_id is not None,
    }
    risk_score, verdict, reasons = _score_and_verdict(signals)

    # Update the just-created row with the final verdict and risk score.
    from database import DB_PATH
    import sqlite3
    with sqlite3.connect(DB_PATH, timeout=10) as connection:
        connection.execute(
            "UPDATE scans SET verdict = ?, risk_score = ? WHERE id = ?",
            (verdict, risk_score, duplicate_info["scan_id"]),
        )

    return {
        "scan_id": duplicate_info["scan_id"],
        "verdict": verdict,
        "risk_score": risk_score,
        "reasons": reasons,
        "upi_app": upi_app,
        "extracted_text": text,
        "transaction_id": transaction_id,
        "image_size": image_size,
        "checks": {
            "image": {"status": "valid", "sha256_prefix": image_hash[:12]},
            "ocr": {"status": ocr["status"], "message": ocr["message"]},
            "payment_success_text": {"found": success_text_found},
            "layout_comparison": layout,
            "text_consistency": typography,
            "pixel_anomalies": pixels,
            "timestamp": timestamp,
            "duplicate_image": {"detected": duplicate_info["duplicate_image"]},
            "duplicate_transaction": {
                "detected": duplicate_info["duplicate_transaction"]
            },
        },
        "analysis_quality": (
            "partial" if ocr["status"] != "available" or layout["status"] == "missing_reference"
            else "heuristic"
        ),
        "notice": (
            "Screenshot analysis cannot confirm that money reached your bank account. "
            "Verify the credit in your own bank or UPI app before handing over goods."
        ),
    }
