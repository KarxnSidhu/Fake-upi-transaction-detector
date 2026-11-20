# UPI Shield — Fake UPI Payment Screenshot Detector

A web-based hackathon prototype for inspecting UPI payment-success screenshots. It accepts screenshots labelled as **Google Pay**, **PhonePe** or **Paytm**, runs a collection of explainable visual/text checks, and returns a risk score with reasons.

> **Critical safety limitation:** A screenshot cannot prove that money reached the merchant's bank account. UPI Shield is a screening aid only. Always confirm the credit in the merchant's own bank or UPI application before handing over goods or services.

## Current implementation

- Responsive HTML5/CSS3/vanilla JavaScript interface.
- FastAPI upload endpoint (`POST /api/analyze`).
- PNG/JPG/JPEG validation, 8 MB upload limit, pixel/dimension safety checks and EXIF orientation handling.
- OpenCV grayscale/CLAHE/denoising preprocessing.
- Pytesseract OCR with an explicit unavailable/timeout state if the Tesseract executable is missing.
- Label-based UTR/transaction-reference extraction.
- App-specific ORB feature matching when reference screenshots have been configured.
- Conservative OCR word-box height consistency check (a font/layout *heuristic*, not font-family identification).
- Weak local high-frequency pixel-patch outlier check.
- Date/time parsing, impossible calendar/clock values and future timestamp detection.
- SQLite persistence for image hashes and one-way hashes of extracted transaction IDs, so repeat scans are detected across server restarts.
- Recent scan history and health endpoints.

## What is not implemented / not claimed

- There is no trained CNN/MobileNet classifier in this project.
- There is no bank, NPCI or UPI network connection and no settlement verification.
- Font family or glyph provenance is not reliably established; the typography check only inspects OCR bounding-box height variation.
- Pixel outliers can be caused by normal UI elements, compression, device settings or app versions.
- App-specific layout comparison is **not available until your team adds legitimate reference screenshots** for each app.
- The 3-second requirement has not yet been benchmarked on a mid-range Android phone.
- The risk score is a weighted heuristic score, not a fraud probability or model confidence.

A result of `NO OBVIOUS ANOMALY DETECTED` must never be described as “genuine”, “real”, “verified” or “payment received”.

## 1. Requirements

- Python 3.10 or later (3.11 recommended).
- Tesseract OCR installed separately for text extraction. OpenCV and Pillow are installed through pip.

### Install Tesseract on Windows

1. Install the Tesseract OCR Windows build from the official UB Mannheim Tesseract distribution: <https://github.com/UB-Mannheim/tesseract/wiki>.
2. During installation, include English language data.
3. Add the Tesseract installation folder to PATH (commonly `C:\Program Files\Tesseract-OCR`).
4. Open a **new** terminal and run:

   ```powershell
   tesseract --version
   ```

If PATH is not configured, set `TESSERACT_CMD` to the full `tesseract.exe` path before starting the server. Example PowerShell:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Without Tesseract, the website still starts, but OCR-dependent checks will be marked unavailable and the result should require manual review.

## 2. Install and run

Open a terminal in the `upi-shield` project folder:

```bash
python -m venv .venv
```

Activate it:

**Windows PowerShell**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the backend:

```bash
uvicorn main:app --reload
```

Open the app:

- Website: <http://127.0.0.1:8000>
- Interactive API docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/api/health>

The SQLite database is created automatically at `data/upi_shield.sqlite3` on first startup.

## 3. Configure reference screenshots (important for H2)

The code does not ship fabricated “genuine” screenshots. Your team must collect reference images with appropriate permission and store them in the matching app folders:

```text
data/
└── reference_templates/
    ├── google_pay/
    │   ├── google_pay_ref_01.png
    │   └── google_pay_ref_02.png
    ├── phonepe/
    │   ├── phonepe_ref_01.png
    │   └── phonepe_ref_02.png
    └── paytm/
        ├── paytm_ref_01.png
        └── paytm_ref_02.png
```

Use several legitimate examples per app, app version and screen aspect ratio. Keep the normal app UI structure. Remove/redact personal identifiers only in a way that does not change the UI layout. Never use customer screenshots without permission. The ORB comparison checks whether stable visual structure matches a configured reference; it is not an authenticity certificate.

Until these files exist, the API returns `missing_reference`, and the verdict will require manual review rather than pretending that a template comparison occurred.

## 4. API

### `POST /api/analyze`

Multipart form fields:

- `file`: PNG/JPG/JPEG screenshot.
- `upi_app`: exactly `Google Pay`, `PhonePe` or `Paytm`.

The response contains `verdict`, `risk_score`, `reasons`, extracted text, a transaction/reference ID if confidently found, image size, individual check results and a safety notice.

Possible verdicts:

- `SUSPICIOUS` — strong or cumulative warning signals.
- `NEEDS MANUAL CHECK` — one or more required checks are missing, inconclusive or concerning.
- `NO OBVIOUS ANOMALY DETECTED` — the available heuristics found no major signal. This is **not** a genuine/paid verdict.

Other endpoints:

- `GET /api/history?limit=8` — recent scan metadata (does not return OCR text or raw IDs).
- `GET /api/stats` — aggregate scan counts.
- `GET /api/health` — service status.

## 5. Data and privacy notes

- The uploaded image is processed in memory and is not written to disk by this app.
- Full OCR text is returned to the browser for the current result but is not persisted in SQLite.
- SQLite stores the image SHA-256, a one-way SHA-256 hash of an extracted transaction ID, app label, verdict, score and timestamp for duplicate detection/history.
- The database is local to the server. For a public deployment, add authentication, authorization, HTTPS, request-rate limits, abuse protection, database backup/retention controls and a privacy notice. Restrict or remove history endpoints if multiple merchants share one deployment.

## 6. Test plan before the hackathon demo

1. Test one known legitimate sample and one altered sample for each supported app.
2. Test screenshots from different Android screen sizes and app versions.
3. Test invalid image files renamed to `.png`, empty files, oversized uploads and corrupted images.
4. Test impossible dates (`31/02/...`), impossible times (`28:75`), future timestamps and screenshots with no readable timestamp.
5. Upload the same exact screenshot twice; the second upload should flag a duplicate image.
6. Upload two screenshots that contain the same labelled transaction ID; the second should flag a duplicate transaction reference.
7. Restart the server and confirm duplicate checks still work (SQLite persistence).
8. Record latency on a mid-range Android phone and report median and 95th percentile, not just one fast run.
9. Measure precision, recall and false-positive rate on a held-out dataset not used to tune thresholds.

## Project structure

```text
upi-shield/
├── main.py              # FastAPI routes and upload validation
├── detector.py          # OpenCV, OCR, layout, pixel and timestamp checks
├── database.py          # SQLite persistence and duplicate lookup
├── requirements.txt
├── README.md
├── data/
│   └── reference_templates/
│       ├── README.md
│       ├── google_pay/
│       ├── phonepe/
│       └── paytm/
├── static/
│   ├── index.html
│   ├── style.css
│   └── script.js
└── tests/
    └── test_api.py
```

## Demo script

1. Select the correct UPI app.
2. Upload a test screenshot.
3. Explain the verdict and each visible forensic signal.
4. Upload the exact same image again to demonstrate persistent duplicate-image detection.
5. Show `/docs` and explain that the system is a screenshot risk screener, not bank verification.
# Responsive frontend update

This package includes the completed scanner, history and help frontend. See [FRONTEND.md](FRONTEND.md) for features, browser verification, screenshots, and remaining device-test limits. The Python backend below is preserved from the supplied project.

