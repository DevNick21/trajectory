"""Download and process UK government data into parquet files.

Sources:
- Sponsor Register (XLSX from gov.uk)
- SOC 2020 going rates (gov.uk immigration salary list)
- Appendix Skilled Occupations (immigration rules)
- ASHE Table 15 (4-digit SOC × region, ONS)  → ashe_soc4_region.parquet
- ASHE Table 3  (2-digit SOC × region, ONS)  → ashe_soc2_region.parquet
- ASHE Table 2  (2-digit SOC national, ONS)  → ashe_soc2_national.parquet

Usage: python scripts/fetch_gov_data.py
"""

from __future__ import annotations

import io
import logging
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DATA_RAW = Path(__file__).parent.parent / "data" / "raw"
DATA_PROCESSED = Path(__file__).parent.parent / "data" / "processed"
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Landing-page URL resolvers
#
# gov.uk and ONS both rotate the numeric asset IDs + release-date filenames
# of their downloads with every publication cycle. Hardcoding a download
# URL is therefore guaranteed to 404 after a few months. We resolve the
# current download URL by scraping the publication landing page and
# picking the first link that matches an agreed pattern.
# ---------------------------------------------------------------------------

SPONSOR_REGISTER_LANDING = (
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
)

# ONS dataset landing pages for the ASHE tables we consume.
# Each table has its OWN dataset page — there is no single umbrella
# "ashe" URL that lists all three. The ZIP download filenames rotate
# with every ONS publication cycle (e.g. `ashetable152025provisional.zip`
# → `ashetable152025revised.zip` → `ashetable152026provisional.zip`), so
# we resolve by scraping the landing page each run.
_ASHE_ROOT = (
    "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/"
    "earningsandworkinghours/datasets"
)
ASHE_LANDING_BY_TABLE = {
    15: f"{_ASHE_ROOT}/regionbyoccupation4digitsoc2010ashetable15",
    3:  f"{_ASHE_ROOT}/regionbyoccupation2digitsocashetable3",
    2:  f"{_ASHE_ROOT}/occupation2digitsocashetable2",
}

GOING_RATES_URL = (
    "https://www.gov.uk/government/publications/skilled-worker-visa-going-rates-for-eligible-jobs"
)

TIMEOUT = 60
_USER_AGENT = "Mozilla/5.0 (compatible; trajectory-fetch-gov-data/0.1)"


def _get(url: str) -> bytes:
    log.info("Fetching %s", url)
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    return r.content


def _get_text(url: str) -> str:
    log.info("Fetching %s", url)
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    # ONS returns 429 if we hammer the dataset pages back-to-back.
    # A five-second gap between landing-page fetches keeps the one-shot
    # `fetch_gov_data.py` well under their rate limit.
    import time
    time.sleep(5.0)
    return r.text


def _resolve_link(landing_url: str, href_pattern: re.Pattern[str]) -> Optional[str]:
    """Return the first absolute URL on `landing_url` whose href matches
    `href_pattern`. Returns None if the page is unreachable or nothing
    matches — caller falls back to an empty parquet skeleton.
    """
    try:
        html = _get_text(landing_url)
    except Exception as exc:
        log.warning("Landing page fetch failed for %s: %s", landing_url, exc)
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning(
            "beautifulsoup4 not installed; falling back to regex href scan."
        )
        m = re.search(rf'href="([^"]*)"', html)
        return m.group(1) if m and href_pattern.search(m.group(1)) else None

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href_pattern.search(href):
            if href.startswith("//"):
                return "https:" + href
            if href.startswith("/"):
                # Build absolute URL from landing page host.
                from urllib.parse import urljoin
                return urljoin(landing_url, href)
            return href
    return None


_SPONSOR_HREF_PATTERN = re.compile(
    r"assets\.publishing\.service\.gov\.uk/.+\.(?:csv|xlsx|ods)$",
    re.IGNORECASE,
)


def _resolve_sponsor_register_url() -> Optional[str]:
    """Find the current Sponsor Register download URL.

    gov.uk wraps the actual file in a numeric-asset path that rotates on
    every publication. We fetch the public landing page and pick the first
    link that points at an assets.publishing.service.gov.uk file with a
    spreadsheet extension (CSV / XLSX / ODS — Home Office has used all
    three historically).
    """
    return _resolve_link(SPONSOR_REGISTER_LANDING, _SPONSOR_HREF_PATTERN)


def fetch_sponsor_register() -> None:
    """Download the sponsor register and convert to parquet."""
    out_parquet = DATA_PROCESSED / "sponsor_register.parquet"
    if out_parquet.exists():
        log.info("sponsor_register.parquet exists — skipping")
        return

    url = _resolve_sponsor_register_url()
    content: Optional[bytes] = None
    resolved_ext = ""
    if url:
        resolved_ext = url.rsplit(".", 1)[-1].lower()
        try:
            content = _get(url)
        except Exception as exc:
            log.warning("Could not fetch sponsor register from %s: %s", url, exc)

    if content is None:
        log.warning(
            "Sponsor Register unavailable — writing empty skeleton parquet. "
            "Visa-holder verdicts will treat every company as NOT_LISTED "
            "until the register is downloaded successfully."
        )
        df = pd.DataFrame(
            columns=[
                "Organisation Name",
                "Town/City",
                "County",
                "Type & Rating",
                "Route",
            ]
        )
        df.to_parquet(out_parquet, index=False)
        return

    raw_path = DATA_RAW / f"sponsor_register.{resolved_ext or 'bin'}"
    raw_path.write_bytes(content)
    log.info("Saved raw: %s (%d bytes)", raw_path, len(content))

    try:
        if resolved_ext == "csv":
            df = pd.read_csv(io.BytesIO(content))
        else:
            try:
                df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
            except Exception:
                df = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        log.error("Sponsor register parse failed: %s — writing empty skeleton", exc)
        pd.DataFrame(
            columns=[
                "Organisation Name",
                "Town/City",
                "County",
                "Type & Rating",
                "Route",
            ]
        ).to_parquet(out_parquet, index=False)
        return

    log.info("Sponsor register: %d rows, columns: %s", len(df), df.columns.tolist())
    df.to_parquet(out_parquet, index=False)
    log.info("Saved: %s", out_parquet)


def fetch_going_rates() -> None:
    """Build a going-rates parquet from embedded SOC data.

    In the absence of a direct CSV download, we create a representative
    skeleton that covers the most common SOC codes. Run the real scraper
    against the gov.uk immigration salary list page for production use.
    """
    out_parquet = DATA_PROCESSED / "going_rates.parquet"
    if out_parquet.exists():
        log.info("going_rates.parquet exists — skipping")
        return

    # Representative SOC 2020 going rates (annual GBP).
    # PROCESS.md Entry 27: everything below except SOC 2136 reflects
    # the April 2024 ISL. SOC 2136 has been refreshed to April-2026
    # numbers (going_rate £52,000, new_entrant £33,400) because it's
    # the only code documented with confirmed 2026 values. The others
    # stay at 2024 pending a full-table refresh (scraper or verified
    # paste) — treat any verdict citing them as potentially stale.
    going_rates = [
        {"soc_code": "2136", "soc_title": "Programmers and software development professionals", "going_rate": 52000, "new_entrant_rate": 33400},
        {"soc_code": "2135", "soc_title": "IT business analysts, architects and systems designers", "going_rate": 42900, "new_entrant_rate": 30900},
        {"soc_code": "2137", "soc_title": "Web and multimedia professionals", "going_rate": 36100, "new_entrant_rate": 27800},
        {"soc_code": "2139", "soc_title": "Information technology and telecommunications professionals", "going_rate": 38700, "new_entrant_rate": 29600},
        {"soc_code": "3534", "soc_title": "Finance and investment analysts and advisers", "going_rate": 47300, "new_entrant_rate": 36300},
        {"soc_code": "2424", "soc_title": "Business and financial project management professionals", "going_rate": 51800, "new_entrant_rate": 39500},
        {"soc_code": "2221", "soc_title": "Medical practitioners", "going_rate": 51500, "new_entrant_rate": 39500},
        {"soc_code": "2119", "soc_title": "Natural and social science professionals", "going_rate": 33400, "new_entrant_rate": 25600},
        {"soc_code": "2425", "soc_title": "Management consultants and business analysts", "going_rate": 46500, "new_entrant_rate": 35600},
        {"soc_code": "1150", "soc_title": "Chief executives and senior officials", "going_rate": 86000, "new_entrant_rate": 66000},
    ]

    df = pd.DataFrame(going_rates)
    df.to_parquet(out_parquet, index=False)
    log.info("Saved going_rates.parquet (%d rows)", len(df))


def fetch_soc_codes() -> None:
    """Build SOC codes parquet (appendix skilled occupations)."""
    out_parquet = DATA_PROCESSED / "soc_codes.parquet"
    if out_parquet.exists():
        log.info("soc_codes.parquet exists — skipping")
        return

    # Skilled worker eligible SOC codes (Appendix Skilled Occupations)
    eligible_codes = [
        "1115", "1116", "1121", "1122", "1131", "1132", "1133", "1134", "1135", "1136",
        "1139", "1141", "1142", "1143", "1150", "1161", "1162", "1163", "1171", "1172",
        "2111", "2112", "2113", "2114", "2119", "2121", "2122", "2123", "2124", "2125",
        "2126", "2127", "2129", "2131", "2133", "2134", "2135", "2136", "2137", "2139",
        "2141", "2142", "2143", "2145", "2146", "2149", "2150", "2161", "2162", "2163",
        "2164", "2165", "2166", "2172", "2173", "2174", "2175", "2176", "2177", "2178",
        "2211", "2212", "2213", "2214", "2215", "2216", "2217", "2218", "2219", "2221",
        "2222", "2223", "2224", "2225", "2229", "2231", "2232", "2233", "2234", "2235",
        "2311", "2312", "2313", "2314", "2315", "2316", "2317", "2318", "2319", "2321",
        "2322", "2323", "2329", "2411", "2412", "2413", "2419", "2421", "2422", "2423",
        "2424", "2425", "2426", "2429", "2431", "2432", "2433", "2434", "2435", "2436",
        "3112", "3113", "3114", "3115", "3116", "3119", "3211", "3212", "3213", "3214",
        "3215", "3216", "3217", "3218", "3219", "3311", "3312", "3313", "3314", "3319",
        "3411", "3412", "3413", "3414", "3415", "3416", "3417", "3421", "3422", "3431",
        "3433", "3434", "3511", "3512", "3513", "3514", "3515", "3521", "3522", "3531",
        "3532", "3533", "3534", "3535", "3536", "3537", "3538", "3539", "3541", "3542",
        "3543", "3544", "3545", "3546", "3549", "3551", "3552", "3553", "3554", "3555",
        "3556", "3557", "3559",
    ]

    df = pd.DataFrame({"soc_code": eligible_codes, "on_appendix": True})
    df.to_parquet(out_parquet, index=False)
    log.info("Saved soc_codes.parquet (%d rows)", len(df))


# ---------------------------------------------------------------------------
# ASHE (Annual Survey of Hours and Earnings) — ONS
# ---------------------------------------------------------------------------

# ONS publishes ASHE results as .zip files containing .xlsx workbooks.
# Table 15 = gross annual pay by occupation (4-digit SOC) and region.
# Table 3  = gross annual pay by occupation (2-digit SOC) and region.
# Table 2  = gross annual pay by occupation (2-digit SOC) national.
#
# Canonical landing page: ASHE_LANDING (defined above). ONS URLs embed a
# release-year tag (e.g. "2024provisional", "2024revised", "2025provisional")
# which rotates with every publication cycle — resolving the download URL
# from the landing page every run is the only way to stay current.


def _ashe_href_pattern(table_number: int) -> re.Pattern[str]:
    """Match ONS ASHE ZIP URLs for a specific table number.

    ONS has used both `table15<year>provisional.zip` and
    `ashetable15<year>provisional.zip` filename patterns across release
    cycles — accept either. Also allow plain "final" or no-suffix
    variants for older editions. Year is not pinned: whichever edition
    the landing page currently advertises wins.
    """
    return re.compile(
        rf"(?:^|/)(?:ashe)?table{table_number}"
        r"\d{4}(?:provisional|revised|final)?\.zip",
        re.IGNORECASE,
    )


def _resolve_ashe_zip_url(table_number: int) -> Optional[str]:
    """Resolve the current download URL for the given ASHE table."""
    landing = ASHE_LANDING_BY_TABLE.get(table_number)
    if landing is None:
        log.warning("No ASHE landing page registered for table %d", table_number)
        return None
    return _resolve_link(landing, _ashe_href_pattern(table_number))


_ASHE_YEAR_RE = re.compile(r"(\d{4})(?:provisional|revised|final)?\.zip", re.I)


def _extract_ashe_year(url: str) -> int:
    m = _ASHE_YEAR_RE.search(url)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    from datetime import date as _d
    return _d.today().year

# Percentile column mappings inside the ASHE xlsx sheets.
#
# ASHE reports the 50th percentile in its own "Median" column — it is
# NOT present as the string "50" on the percentile header row. The other
# percentiles ("10", "20", "25", ..., "90") are on the header row as
# numeric/string cells after the fixed columns (Description, Code,
# Number of jobs, Median, pct-change, Mean, pct-change, Percentiles
# label) — so we match against the column label the cell actually
# carries, which is "Median" for p50 and the integer string otherwise.
_PCT_COLS = {
    "10": "p10",
    "25": "p25",
    "Median": "p50",
    "75": "p75",
    "90": "p90",
}


def _download_ashe_zip(url: str, label: str) -> bytes | None:
    try:
        return _get(url)
    except Exception as exc:
        log.warning("Could not fetch ASHE %s (%s): %s", label, url, exc)
        return None


def _extract_xlsx_from_zip(content: bytes) -> bytes | None:
    """Return the `Annual pay - Gross` xlsx if present, else the first xlsx.

    ASHE Tables 2/3/15 are published as a ZIP containing ~20 xlsx files,
    one per pay measure (Weekly pay, Hourly pay, Annual pay, Paid hours,
    Overtime, etc.). The one we want for salary floor + citation work is
    the *Annual pay - Gross* workbook. Filenames look like:
        PROV - Work Region Occupation SOC20 (2) Table 3.7a   Annual pay - Gross 2025.xlsx

    We also skip the `CV` (coefficient-of-variation) companion files —
    they carry quality metrics for the headline file, not the values.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xlsx_names = [
                n for n in zf.namelist()
                if n.lower().endswith(".xlsx") and " cv" not in n.lower()
            ]
            if not xlsx_names:
                return None
            preferred = next(
                (n for n in xlsx_names if "annual pay - gross" in n.lower()),
                None,
            )
            chosen = preferred or xlsx_names[0]
            log.info("ASHE ZIP: picking %s", chosen.split("/")[-1])
            return zf.read(chosen)
    except Exception as exc:
        log.warning("ZIP extraction failed: %s", exc)
    return None


def _parse_ashe_table(
    xlsx_bytes: bytes, by_region: bool, sample_year: int
) -> pd.DataFrame | None:
    """Parse an ASHE xlsx workbook into a tidy DataFrame.

    Expected sheet structure (ONS ASHE standard layout):
      - Row ~5 onwards: data rows with SOC code, description, region (if Table 15/3),
        and percentile columns (10, 25, 50, 75, 90).

    Returns a DataFrame with columns:
      soc_code, region (if by_region), p10, p25, p50, p75, p90, sample_year
    or None if parsing fails.
    """
    # ASHE workbooks have multiple sheets: "Notes", "Cover sheet", then a
    # data sheet per demographic ("All", "Male", "Female", "Full-Time", …).
    # Each data sheet holds several tables stacked vertically (Weekly pay,
    # Annual pay, Weekly hours, …) with their own percentile headers.
    # We iterate non-metadata sheets and return the first one that produces
    # a parseable percentile table.
    _META_SHEET_RE = re.compile(
        r"notes|cover|contents|introduction|info|metadata|sampling",
        re.IGNORECASE,
    )
    try:
        xl = pd.ExcelFile(io.BytesIO(xlsx_bytes), engine="openpyxl")
    except Exception as exc:
        log.warning("ASHE xlsx parse failed: %s", exc)
        return None

    candidate_sheets = [sh for sh in xl.sheet_names if not _META_SHEET_RE.search(sh)]
    if not candidate_sheets:
        candidate_sheets = xl.sheet_names

    def _normalise_cell(v: Any) -> str:
        # pandas can read percentile-header cells as numbers (10.0, 25.0,
        # 50.0) depending on cell type. Coerce integer-valued floats back
        # to their string form so the "10"/"25"/"50" match succeeds.
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v).strip()

    df_raw = None
    target_sheet = None
    header_row = None
    for sh in candidate_sheets:
        try:
            candidate = pd.read_excel(
                io.BytesIO(xlsx_bytes),
                sheet_name=sh,
                header=None,
                engine="openpyxl",
            )
        except Exception as exc:
            log.debug("Skipping sheet %s: %s", sh, exc)
            continue
        # Find a row containing the canonical percentile headers.
        # We don't require "50" — ASHE puts the 50th percentile in a
        # separate "Median" column rather than on the percentile header
        # row. Requiring 10/25/75 catches the row reliably without
        # false-matching the Median column itself.
        found_row = None
        for i, row in candidate.iterrows():
            vals = {_normalise_cell(v) for v in row.values}
            if {"10", "25", "75"}.issubset(vals):
                found_row = i
                break
        if found_row is not None:
            df_raw = candidate
            target_sheet = sh
            header_row = found_row
            break

    if df_raw is None:
        log.warning(
            "ASHE: no data sheet in %s yielded percentile headers. "
            "Sheet names: %s",
            "xlsx", xl.sheet_names,
        )
        return None

    df_raw.columns = [_normalise_cell(v) for v in df_raw.iloc[header_row]]
    df = df_raw.iloc[header_row + 1 :].copy().reset_index(drop=True)

    # Identify SOC code column (first numeric-ish column or labelled "Code")
    soc_col = None
    for col in df.columns:
        if "code" in col.lower() or col in ("Code", "SOC"):
            soc_col = col
            break
    if soc_col is None:
        # Heuristic: first column whose values look like 4-digit numbers
        for col in df.columns:
            sample = df[col].dropna().astype(str).str.strip()
            if sample.str.match(r"^\d{2,4}$").mean() > 0.3:
                soc_col = col
                break
    if soc_col is None:
        log.warning("ASHE: could not identify SOC code column")
        return None

    # Find a "description" column for human-readable labels (used to
    # capture region names in the regional tables).
    desc_col = None
    for col in df.columns:
        if "description" in col.lower():
            desc_col = col
            break

    # Region attribution in ASHE regional tables:
    # The tables don't have a dedicated `region` column. Instead, a row
    # whose Code looks like an ONS geography code (K02000001 for UK,
    # E12000001-E12000009 for English regions, W92000004 for Wales,
    # S92000003 for Scotland, N92000002 for NI) acts as a section
    # header — the SOC rows that follow belong to that region until the
    # next geography-code row appears.
    _GEO_CODE_RE = re.compile(r"^[A-Z]\d{7,9}$")

    rows = []
    current_region: Optional[str] = None
    for _, row in df.iterrows():
        code_val = str(row.get(soc_col, "")).strip()

        if by_region and _GEO_CODE_RE.match(code_val):
            # Region section header (Table 3 style).
            if desc_col is not None:
                current_region = str(row.get(desc_col, "")).strip() or current_region
            continue

        if not re.match(r"^\d{2,4}$", code_val):
            continue
        soc = code_val

        # Table 15 style: region is baked into the Description column as
        # "<Region>, <SOC title>" on every data row. Prefer the inline
        # prefix when it looks like a known UK region; fall back to the
        # section-header state picked up above.
        row_region = current_region
        if by_region and desc_col is not None:
            desc_val = str(row.get(desc_col, "")).strip()
            if "," in desc_val:
                prefix = desc_val.split(",", 1)[0].strip()
                if prefix and prefix.lower() not in ("united kingdom", "uk"):
                    row_region = prefix

        p_vals: dict = {}
        for raw_pct, field in _PCT_COLS.items():
            col_match = next((c for c in df.columns if str(c).strip() == raw_pct), None)
            if col_match:
                try:
                    v = float(str(row.get(col_match, "")).replace(",", "").strip())
                    # ASHE Table 15 publishes weekly pay in some sheets —
                    # heuristic convert when the value looks like pounds/week
                    # rather than pounds/year.
                    if v < 2000:
                        v = v * 52
                    p_vals[field] = int(v)
                except (ValueError, TypeError):
                    p_vals[field] = None

        entry = {"soc_code": soc, "sample_year": sample_year, **p_vals}
        if by_region:
            entry["region"] = row_region
        rows.append(entry)

    if not rows:
        log.warning("ASHE: no rows parsed from %s", target_sheet)
        return None

    result = pd.DataFrame(rows)
    # Drop rows where every percentile present is null. Guard against
    # missing columns — not every ASHE sheet has the full 10/25/50/75/90
    # set (Table 2 national omits some for confidentiality-threshold rows).
    present_pct_cols = [c for c in _PCT_COLS.values() if c in result.columns]
    if present_pct_cols:
        result = result.dropna(subset=present_pct_cols, how="all")
    # Backfill missing percentile columns with None so downstream lookups
    # see a stable schema regardless of which sheet we parsed.
    for field in _PCT_COLS.values():
        if field not in result.columns:
            result[field] = None
    return result


def _fetch_ashe_table(table_number: int, out_name: str, by_region: bool) -> None:
    out = DATA_PROCESSED / out_name
    if out.exists():
        log.info("%s exists — skipping", out_name)
        return

    landing = ASHE_LANDING_BY_TABLE.get(table_number, "<unknown>")
    url = _resolve_ashe_zip_url(table_number)
    if url is None:
        log.warning(
            "ASHE Table %d URL could not be resolved from %s — writing "
            "empty skeleton. Salary citations will be missing until the "
            "parquet is built successfully.",
            table_number, landing,
        )
        _write_empty_ashe(out, region=by_region)
        return

    sample_year = _extract_ashe_year(url)

    content = _download_ashe_zip(url, f"Table{table_number}")
    if content is None:
        _write_empty_ashe(out, region=by_region)
        return

    xlsx = _extract_xlsx_from_zip(content)
    if xlsx is None:
        _write_empty_ashe(out, region=by_region)
        return

    df = _parse_ashe_table(xlsx, by_region=by_region, sample_year=sample_year)
    if df is None or df.empty:
        _write_empty_ashe(out, region=by_region)
        return

    df.to_parquet(out, index=False)
    log.info(
        "Saved %s (%d rows, sample_year=%d, source=%s)",
        out_name, len(df), sample_year, url,
    )


def fetch_ashe_table15() -> None:
    """ASHE Table 15 — annual gross pay by 4-digit SOC and region."""
    _fetch_ashe_table(15, "ashe_soc4_region.parquet", by_region=True)


def fetch_ashe_table3() -> None:
    """ASHE Table 3 — annual gross pay by 2-digit SOC and region."""
    _fetch_ashe_table(3, "ashe_soc2_region.parquet", by_region=True)


def fetch_ashe_table2() -> None:
    """ASHE Table 2 — annual gross pay by 2-digit SOC, national."""
    _fetch_ashe_table(2, "ashe_soc2_national.parquet", by_region=False)


def _write_empty_ashe(out: Path, region: bool) -> None:
    cols = ["soc_code", "p10", "p25", "p50", "p75", "p90", "sample_year"]
    if region:
        cols.insert(1, "region")
    df = pd.DataFrame(columns=cols)
    df.to_parquet(out, index=False)
    log.info("Wrote empty skeleton %s (ASHE download failed)", out.name)


def main() -> None:
    log.info("Fetching UK government data…")
    fetch_sponsor_register()
    fetch_going_rates()
    fetch_soc_codes()
    fetch_ashe_table15()
    fetch_ashe_table3()
    fetch_ashe_table2()
    log.info("Done. Parquet files in %s", DATA_PROCESSED)


if __name__ == "__main__":
    main()
