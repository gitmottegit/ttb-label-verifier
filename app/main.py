"""TTB Label Verifier — FastAPI application.

Endpoints:
    GET  /              the single-page UI
    POST /api/verify    one label image + application fields -> verification report
    POST /api/batch     many label images + optional CSV of application data
    GET  /api/health    liveness / configuration probe
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .extraction import MODEL, ExtractionError, extract_label_fields
from .verification import build_report

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BATCH_CONCURRENCY = 8  # parallel model calls; keeps a 300-label dump moving
BATCH_MAX_FILES = 300
RATE_LIMIT_PER_MINUTE = 40  # per client IP; a batch upload counts as one request

app = FastAPI(title="TTB Label Verifier", version="1.0.0")

_request_log: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Light per-IP throttle so a public demo URL can't drain API credits."""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        window = _request_log[request.client.host if request.client else "unknown"]
        now = time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            return JSONResponse(
                {"error": "Too many requests from this address — wait a minute and retry."},
                status_code=429)
        window.append(now)
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict:
    import os
    return {"status": "ok", "model": MODEL,
            "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


async def _verify_one(filename: str, image_bytes: bytes, application: dict) -> dict:
    started = time.perf_counter()
    try:
        extracted = await extract_label_fields(image_bytes)
    except ExtractionError as exc:
        return {"filename": filename, "ok": False, "error": str(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    report = build_report(extracted, application)
    return {
        "filename": filename,
        "ok": True,
        "report": asdict(report),
        "extracted": extracted,
        "application": application,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


@app.post("/api/verify")
async def verify(
    image: UploadFile = File(...),
    brand_name: str = Form(""),
    class_type: str = Form(""),
    alcohol_content: str = Form(""),
    net_contents: str = Form(""),
) -> JSONResponse:
    application = {
        "brand_name": brand_name.strip(),
        "class_type": class_type.strip(),
        "alcohol_content": alcohol_content.strip(),
        "net_contents": net_contents.strip(),
    }
    result = await _verify_one(image.filename or "label", await image.read(), application)
    return JSONResponse(result, status_code=200 if result["ok"] else 422)


def parse_application_csv(data: bytes) -> dict[str, dict]:
    """CSV columns: filename, brand_name, class_type, alcohol_content, net_contents."""
    rows: dict[str, dict] = {}
    text = data.decode("utf-8-sig", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        filename = row.get("filename")
        if filename:
            rows[filename] = {k: row.get(k, "") for k in
                              ("brand_name", "class_type", "alcohol_content", "net_contents")}
    return rows


@app.post("/api/batch")
async def batch(
    images: list[UploadFile] = File(...),
    applications_csv: UploadFile | None = File(None),
) -> JSONResponse:
    if len(images) > BATCH_MAX_FILES:
        return JSONResponse(
            {"error": f"Batch limit is {BATCH_MAX_FILES} images at a time."}, status_code=422)

    app_rows: dict[str, dict] = {}
    if applications_csv is not None:
        try:
            app_rows = parse_application_csv(await applications_csv.read())
        except Exception:
            return JSONResponse(
                {"error": "Could not read the CSV. Expected columns: filename, "
                          "brand_name, class_type, alcohol_content, net_contents."},
                status_code=422)

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def run(img: UploadFile, index: int) -> dict:
        filename = img.filename or f"label_{index}"
        # Read inside the semaphore so at most BATCH_CONCURRENCY images are
        # held in memory at once — a 300-file dump must not exhaust RAM.
        async with semaphore:
            data = await img.read()
            return await _verify_one(filename, data, app_rows.get(filename, {}))

    started = time.perf_counter()
    results = await asyncio.gather(*(run(img, i) for i, img in enumerate(images, start=1)))
    return JSONResponse({
        "count": len(results),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "csv_rows_matched": sum(1 for r in results if r["filename"] in app_rows),
        "results": list(results),
    })


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
