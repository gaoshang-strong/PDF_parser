"""MinerU API adapter: submit a PDF to the MinerU cloud API and extract the
result into an output directory.

No local MinerU or ML packages are required.  Only `requests` is used.

Token is read from the MINERU_API_TOKEN environment variable.  It is never
written to logs or error messages.

Verified API workflow (mineru.net) — batch upload flow:
  1. POST  {base_url}/api/v4/file-urls/batch  →  put_url + batch_id
  2. PUT   {put_url}  (no Content-Type header) →  upload raw PDF bytes
  3. GET   {base_url}/api/v4/extract-results/batch/{batch_id}  →  poll per-file state
  4. On state="done": GET {full_zip_url}       →  download result ZIP
  5. Safe-extract ZIP into out_dir

Notes:
- The batch PUT URL signature does NOT include Content-Type; sending any
  Content-Type header causes HTTP 403.
- The /api/v4/file + /api/v4/extract/task flow (older single-file API) is NOT
  used because MinerU's processing backend cannot access the resulting signed
  CDN download URL — it always fails with "failed to read file".
"""

from __future__ import annotations

import os
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

import requests

_PARSER_NAME = "mineru_api"
_DEFAULT_BASE_URL = "https://mineru.net"
_DEFAULT_MODEL_VERSION = "vlm"
_POLL_INTERVAL_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 600.0


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def get_mineru_api_token() -> str:
    """Return the MinerU API token from MINERU_API_TOKEN.

    Raises RuntimeError if the variable is not set or empty.
    """
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MINERU_API_TOKEN environment variable is not set. "
            "Set it to your MinerU API token before calling this function."
        )
    return token


# ---------------------------------------------------------------------------
# Step 1: register file and get presigned upload URL via batch API
# ---------------------------------------------------------------------------

def request_mineru_batch_upload_url(
    pdf_name: str,
    token: str,
    base_url: str = _DEFAULT_BASE_URL,
    model_version: str = _DEFAULT_MODEL_VERSION,
) -> tuple[str, str]:
    """POST /api/v4/file-urls/batch to register a file and get (put_url, batch_id).

    put_url  — Alibaba OSS presigned URL to PUT the raw PDF bytes to (no CT header).
    batch_id — identifier used to poll /api/v4/extract-results/batch/{batch_id}.

    Raises RuntimeError on non-0 code or missing fields.
    Token is never included in exception messages.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v4/file-urls/batch"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        endpoint,
        json={
            "files": [{"name": pdf_name}],
            "model_version": model_version,
            "enable_formula": True,
            "enable_table": True,
        },
        headers=headers,
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"MinerU batch upload URL request failed: HTTP {response.status_code} "
            f"from {endpoint}"
        )

    data = response.json()
    code = data.get("code")
    if code != 0:
        raise RuntimeError(
            f"MinerU batch upload URL request returned code={code}: "
            f"{data.get('msg', 'unknown error')}"
        )

    inner = data.get("data", {})
    batch_id = inner.get("batch_id")
    file_urls = inner.get("file_urls", [])

    if not batch_id:
        raise RuntimeError("MinerU batch upload URL response missing batch_id")
    if not file_urls:
        raise RuntimeError("MinerU batch upload URL response missing file_urls")

    put_url = file_urls[0]
    if not put_url:
        raise RuntimeError("MinerU batch upload URL response has empty file_urls[0]")

    return str(put_url), str(batch_id)


# ---------------------------------------------------------------------------
# Step 2: upload PDF to presigned URL
# ---------------------------------------------------------------------------

def upload_pdf_to_mineru_upload_url(pdf_path: Path, put_url: str) -> None:
    """PUT the raw PDF bytes to the Alibaba OSS presigned URL.

    The batch PUT URL signature does NOT include Content-Type, so no
    Content-Type header must be sent — adding one causes HTTP 403.

    Reads the file into memory so that requests sets Content-Length correctly.

    Raises RuntimeError if the upload fails.
    """
    pdf_bytes = Path(pdf_path).read_bytes()
    response = requests.put(
        put_url,
        data=pdf_bytes,
        timeout=120,
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(
            f"PDF upload to presigned URL failed: HTTP {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Step 3: poll batch result until done or failed
# ---------------------------------------------------------------------------

def poll_mineru_batch_result(
    batch_id: str,
    token: str,
    base_url: str = _DEFAULT_BASE_URL,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    timeout: float = _POLL_TIMEOUT_SECONDS,
) -> str:
    """Poll GET /api/v4/extract-results/batch/{batch_id} until the first file is done.

    Returns the full_zip_url for the first file in the batch on success.
    Raises RuntimeError on failure or timeout.
    Token is never included in exception messages.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}"
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + timeout
    last_state = ""

    while time.monotonic() < deadline:
        response = requests.get(endpoint, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"MinerU batch result check failed: HTTP {response.status_code} "
                f"for batch_id={batch_id}"
            )

        data = response.json()
        results = data.get("data", {}).get("extract_result", [])
        if not results:
            time.sleep(poll_interval)
            continue

        file_result = results[0]
        state = file_result.get("state", "")

        if state != last_state:
            print(f"[mineru] batch_id={batch_id} state={state!r}")
            last_state = state

        if state == "done":
            zip_url = file_result.get("full_zip_url", "")
            if not zip_url:
                raise RuntimeError(
                    f"MinerU batch_id={batch_id} completed but full_zip_url is missing"
                )
            return str(zip_url)

        if state in ("failed", "error"):
            err = file_result.get("err_msg") or file_result.get("message") or "unknown error"
            raise RuntimeError(
                f"MinerU batch_id={batch_id} failed: {err}"
            )

        time.sleep(poll_interval)

    raise RuntimeError(
        f"MinerU batch_id={batch_id} timed out after {timeout:.0f}s"
    )


# ---------------------------------------------------------------------------
# Step 4: download result ZIP
# ---------------------------------------------------------------------------

def download_mineru_result_zip(zip_url: str, dest_path: Path) -> None:
    """Stream the result ZIP from the CDN URL (no auth needed) to dest_path.

    Raises RuntimeError on non-200 response or wrong content-type.
    """
    with requests.get(zip_url, stream=True, timeout=120) as response:
        if response.status_code != 200:
            raise RuntimeError(
                f"MinerU result ZIP download failed: HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "")
        if "zip" not in content_type and "octet-stream" not in content_type:
            raise RuntimeError(
                f"Expected ZIP from MinerU result URL, "
                f"got content-type={content_type!r}"
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=65536):
                fh.write(chunk)


# ---------------------------------------------------------------------------
# Step 5: safe-extract ZIP
# ---------------------------------------------------------------------------

def extract_mineru_zip(zip_path: Path, output_dir: Path) -> None:
    """Extract zip_path into output_dir, refusing path-traversal entries."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(
                    f"Refusing unsafe ZIP entry: {member.filename}"
                )
            target = (output_root / Path(*member_path.parts)).resolve()
            if target != output_root and output_root not in target.parents:
                raise RuntimeError(
                    f"Refusing unsafe ZIP entry: {member.filename}"
                )
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def run_mineru_api(
    pdf_path: Path,
    out_dir: Path,
    token: Optional[str] = None,
    base_url: str = _DEFAULT_BASE_URL,
    model_version: str = _DEFAULT_MODEL_VERSION,
) -> Path:
    """Submit a PDF to the MinerU cloud API and extract the results to out_dir.

    Returns out_dir on success.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path is not a .pdf file.
    Raises RuntimeError on API errors, task failure, timeout, or download failure.
    Token is read from MINERU_API_TOKEN if not passed explicitly.
    Token is never written to logs or error messages.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}"
        )

    if token is None:
        token = get_mineru_api_token()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_name = pdf_path.name
    pdf_size = pdf_path.stat().st_size
    print(f"[mineru] Registering {pdf_name} ({pdf_size:,} bytes, model={model_version})...")
    put_url, batch_id = request_mineru_batch_upload_url(pdf_name, token, base_url, model_version)
    print(f"[mineru] Uploading (batch_id={batch_id})...")
    upload_pdf_to_mineru_upload_url(pdf_path, put_url)
    print(f"[mineru] Polling for extraction result...")
    zip_url = poll_mineru_batch_result(batch_id, token, base_url)
    print(f"[mineru] Downloading result ZIP...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "result.zip"
        download_mineru_result_zip(zip_url, zip_path)
        print(f"[mineru] Extracting to {out_dir} ...")
        extract_mineru_zip(zip_path, out_dir)

    print(f"[mineru] Done. Output: {out_dir}")
    return out_dir
