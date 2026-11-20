from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import database
from detector import analyze_screenshot

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_APPS = {"Google Pay", "PhonePe", "Paytm"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upi_shield.api")

@asynccontextmanager
async def lifespan(application: FastAPI):
    database.init_db()
    logger.info("UPI Shield started. SQLite database: %s", database.DB_PATH)
    yield


app = FastAPI(
    title="UPI Shield API",
    description=(
        "Explainable screenshot-forensics prototype for Google Pay, PhonePe and Paytm. "
        "It cannot verify settlement or prove that a payment was received."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Invalid request data.",
            "errors": [
                {"field": ".".join(str(part) for part in error.get("loc", [])),
                 "message": error.get("msg", "Invalid value")}
                for error in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "An unexpected server error occurred. Please try again.",
        },
    )


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "UPI Shield",
        "database": "sqlite",
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), upi_app: str = Form(...)):
    """Receive a screenshot and return explainable forensic signals."""
    if upi_app not in ALLOWED_APPS:
        raise HTTPException(
            status_code=422,
            detail=f"upi_app must be one of: {', '.join(sorted(ALLOWED_APPS))}.",
        )

    filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Only PNG, JPG and JPEG screenshot files are supported.",
        )

    content_parts: list[bytes] = []
    total_bytes = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Screenshot exceeds the 8 MB upload limit.",
                )
            content_parts.append(chunk)
    finally:
        await file.close()

    if not total_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    content = b"".join(content_parts)
    try:
        result = await run_in_threadpool(analyze_screenshot, content, upi_app)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Screenshot analysis failed")
        raise HTTPException(
            status_code=500,
            detail="Screenshot analysis failed unexpectedly. Please try another image.",
        ) from exc


@app.get("/api/history")
def history(limit: int = 20):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100.")
    return {"items": database.get_history(limit)}


@app.get("/api/stats")
def stats():
    return database.get_stats()
