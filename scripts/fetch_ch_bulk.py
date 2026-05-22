"""Companies House bulk-data downloader + parquet builder.

Replaces the rate-limited /search/companies API path for name->CRN
resolution. The bulk product is the monthly "Free Company Data
Snapshot" (BasicCompanyDataAsOneFile-YYYY-MM-DD.zip), ~5M UK companies
with previous names and SIC codes. Pattern lifted from kanu's
`companies_house/bulk_downloader.py` (ADR 0014); adapted for AskPicky's
single-product scope.

Run:
    python scripts/fetch_ch_bulk.py --resolve-latest

This downloads (or no-ops via ETag) the newest snapshot, parses the
CSV in chunks, and writes a slim parquet to
`data/processed/ch_companies.parquet` containing just the columns the
resolver needs:
  - CompanyName            (str)
  - CompanyNumber          (str, 8 chars, the CRN)
  - CompanyStatus          (str)
  - PostCode               (str, optional)
  - IncorporationDate      (str ISO date)
  - DissolutionDate        (str ISO date or null)
  - SicText                (str — first SIC code text, others dropped)
  - PreviousNames          (JSON list[str], up to 10 historic names)

State sidecar at `data/processed/ch_bulk_state.json` records the
download URL, ETag, Last-Modified, size, and fetched_at so subsequent
runs short-circuit when nothing changed.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# Ensure repo root on sys.path for `from askpicky...` imports when run as a
# script outside the editable-install context.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from askpicky.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("fetch_ch_bulk")


CH_DOWNLOAD_HOST = "https://download.companieshouse.gov.uk"
FREE_COMPANY_DATA_INDEX = f"{CH_DOWNLOAD_HOST}/en_output.html"

# AsOneFile is the single ZIP'd CSV variant; the multi-part variant
# splits across N files which complicates streaming.
_LATEST_URL_RE = re.compile(
    r'href="([^"]*BasicCompanyDataAsOneFile-(\d{4}-\d{2}-\d{2})\.zip)"',
    re.IGNORECASE,
)

DEFAULT_TIMEOUT_SECONDS = 60
CHUNK_BYTES = 1 << 20  # 1 MiB streaming chunks
PARSE_CHUNK_ROWS = 100_000  # CSV chunk size for the parquet builder

# Columns we care about (the CSV ships with leading whitespace on some
# headers — strip before comparing).
COLUMN_CANDIDATES = {
    "CompanyName",
    "CompanyNumber",
    "CompanyStatus",
    "RegAddress.PostCode",
    "IncorporationDate",
    "DissolutionDate",
    "SICCode.SicText_1",
    "PreviousName_1.CompanyName",
    "PreviousName_2.CompanyName",
    "PreviousName_3.CompanyName",
    "PreviousName_4.CompanyName",
    "PreviousName_5.CompanyName",
    "PreviousName_6.CompanyName",
    "PreviousName_7.CompanyName",
    "PreviousName_8.CompanyName",
    "PreviousName_9.CompanyName",
    "PreviousName_10.CompanyName",
}


@dataclass
class BulkArtifact:
    """One downloaded snapshot — what we know about the file on disk."""

    url: str
    local_path: str
    etag: Optional[str]
    last_modified: Optional[str]
    fetched_at_utc: str
    size_bytes: int
    snapshot_date: Optional[str] = None
    parquet_path: Optional[str] = None


def _bulk_dir() -> Path:
    path = settings.data_dir / "ch_bulk"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return _bulk_dir() / "state.json"


def _parquet_path() -> Path:
    out = settings.data_dir / "processed"
    out.mkdir(parents=True, exist_ok=True)
    return out / "ch_companies.parquet"


def load_state() -> Optional[BulkArtifact]:
    p = _state_path()
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not raw:
        return None
    return BulkArtifact(**raw)


def save_state(artifact: BulkArtifact) -> None:
    p = _state_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(asdict(artifact), f, indent=2)


def resolve_latest_url() -> Optional[tuple[str, str]]:
    """Scrape the CH index page for the newest dated snapshot. Returns
    (url, date_str) or None on parse failure."""
    try:
        resp = requests.get(FREE_COMPANY_DATA_INDEX, timeout=DEFAULT_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch CH index page: %s", exc)
        return None
    matches = _LATEST_URL_RE.findall(resp.text)
    if not matches:
        logger.warning("No BasicCompanyDataAsOneFile-* links on %s",
                       FREE_COMPANY_DATA_INDEX)
        return None
    href, date_str = max(matches, key=lambda m: m[1])
    url = href if href.startswith("http") else f"{CH_DOWNLOAD_HOST}/{href.lstrip('/')}"
    logger.info("Latest CH snapshot: %s (date %s)", url, date_str)
    return url, date_str


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
def _stream_download(
    url: str, dest: Path, headers: Optional[dict] = None,
) -> tuple[int, dict[str, str]]:
    """Atomic stream download. 304 = not modified (caller treats as no-op)."""
    request_headers = dict(headers or {})
    with requests.get(
        url, stream=True, headers=request_headers, timeout=DEFAULT_TIMEOUT_SECONDS,
    ) as response:
        if response.status_code == 304:
            return 304, dict(response.headers)
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb", dir=str(dest.parent), delete=False,
            prefix=".dl-", suffix=".part",
        ) as tmp:
            tmp_path = Path(tmp.name)
            for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                if chunk:
                    tmp.write(chunk)
        shutil.move(str(tmp_path), str(dest))
        return response.status_code, dict(response.headers)


def fetch_snapshot(
    url: str, *, snapshot_date: Optional[str] = None,
) -> tuple[BulkArtifact, bool]:
    """Fetch (or 304-no-op) the snapshot. Returns (artifact, was_fresh)."""
    cached = load_state()
    name = url.rsplit("/", 1)[-1] or "ch_bulk.zip"
    dest = _bulk_dir() / name

    request_headers: dict[str, str] = {}
    if cached and dest.exists():
        if cached.etag:
            request_headers["If-None-Match"] = cached.etag
        if cached.last_modified:
            request_headers["If-Modified-Since"] = cached.last_modified

    status, response_headers = _stream_download(url, dest, headers=request_headers)
    if status == 304 and cached is not None and dest.exists():
        logger.info("CH snapshot unchanged (HTTP 304); reusing %s", dest)
        return cached, False

    artifact = BulkArtifact(
        url=url,
        local_path=str(dest),
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
        fetched_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        size_bytes=dest.stat().st_size,
        snapshot_date=snapshot_date,
    )
    logger.info(
        "Downloaded CH snapshot: %s (%.1f MB)",
        dest, artifact.size_bytes / 1_048_576,
    )
    return artifact, True


def _resolve_csv(zip_path: Path) -> Path:
    """Unpack the single CSV inside the ZIP if not already extracted."""
    extract_dir = zip_path.parent
    with zipfile.ZipFile(zip_path) as archive:
        csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV inside {zip_path}")
        csv_name = csv_names[0]
        extracted = extract_dir / Path(csv_name).name
        if not extracted.exists():
            logger.info("Extracting %s -> %s", csv_name, extracted)
            archive.extract(csv_name, extract_dir)
            extracted_raw = extract_dir / csv_name
            if extracted_raw != extracted:
                extracted_raw.rename(extracted)
        return extracted


def _strip_columns(df):
    """Strip leading/trailing whitespace from CH's slightly-wonky headers."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    return df


def _iter_chunks(csv_path: Path) -> Iterator:
    """Yield slim CSV chunks. Skips columns we don't care about."""
    import pandas as pd
    reader = pd.read_csv(
        csv_path,
        usecols=lambda c: c.strip() in COLUMN_CANDIDATES,
        chunksize=PARSE_CHUNK_ROWS,
        dtype=str,
        keep_default_na=False,
    )
    for chunk in reader:
        yield _strip_columns(chunk)


def build_parquet(csv_path: Path, parquet_path: Path) -> int:
    """Stream the CSV, collapse previous-name columns into a JSON list,
    write a single parquet. Returns the row count."""
    import pandas as pd

    logger.info("Building slim parquet: %s -> %s", csv_path, parquet_path)
    prev_name_cols = [f"PreviousName_{i}.CompanyName" for i in range(1, 11)]

    pieces: list = []
    total = 0
    for chunk in _iter_chunks(csv_path):
        chunk = chunk.rename(columns={
            "RegAddress.PostCode": "PostCode",
            "SICCode.SicText_1": "SicText",
        })
        # Collapse previous-name columns into one JSON-encoded list per row.
        present = [c for c in prev_name_cols if c in chunk.columns]
        if present:
            chunk["PreviousNames"] = chunk[present].apply(
                lambda row: json.dumps([
                    s.strip() for s in row.tolist() if s and s.strip()
                ]),
                axis=1,
            )
            chunk = chunk.drop(columns=present)
        else:
            chunk["PreviousNames"] = "[]"

        keep = [
            "CompanyName", "CompanyNumber", "CompanyStatus", "PostCode",
            "IncorporationDate", "DissolutionDate", "SicText", "PreviousNames",
        ]
        present_keep = [c for c in keep if c in chunk.columns]
        chunk = chunk[present_keep]
        pieces.append(chunk)
        total += len(chunk)
        if len(pieces) % 10 == 0:
            logger.info("  ... %d rows processed", total)

    if not pieces:
        logger.warning("CSV %s produced zero usable chunks", csv_path)
        return 0

    df = pd.concat(pieces, ignore_index=True)
    df["CompanyNumber"] = df["CompanyNumber"].str.zfill(8)
    df.to_parquet(parquet_path, compression="snappy", index=False)
    logger.info(
        "Wrote %s (%d rows, %.1f MB)",
        parquet_path, total, parquet_path.stat().st_size / 1_048_576,
    )
    return total


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download the Companies House Free Company Data snapshot and "
            "build a slim parquet for local name->CRN resolution. "
            "Honours ETag / If-Modified-Since so re-runs within the "
            "monthly cadence are network no-ops."
        ),
    )
    parser.add_argument(
        "--resolve-latest", action="store_true",
        help="Scrape the CH index page and download the newest snapshot.",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="Explicit snapshot URL (overrides --resolve-latest).",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Download + cache only; do not rebuild the parquet.",
    )
    parser.add_argument(
        "--force-rebuild", action="store_true",
        help="Rebuild the parquet even when the snapshot is unchanged.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if not args.url and not args.resolve_latest:
        print("Pass --resolve-latest or --url <snapshot.zip URL>.", file=sys.stderr)
        return 2

    snapshot_date: Optional[str] = None
    url = args.url
    if not url:
        latest = resolve_latest_url()
        if not latest:
            print("Could not resolve the latest snapshot URL.", file=sys.stderr)
            return 1
        url, snapshot_date = latest

    artifact, was_fresh = fetch_snapshot(url, snapshot_date=snapshot_date)

    if args.skip_build:
        save_state(artifact)
        return 0

    parquet_path = _parquet_path()
    if was_fresh or args.force_rebuild or not parquet_path.exists():
        csv_path = _resolve_csv(Path(artifact.local_path))
        build_parquet(csv_path, parquet_path)
        artifact.parquet_path = str(parquet_path)
    else:
        logger.info("Parquet exists + snapshot unchanged; skipping rebuild.")

    save_state(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
