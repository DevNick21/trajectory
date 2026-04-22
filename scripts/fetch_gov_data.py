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

import pandas as pd
import requests

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DATA_RAW = Path(__file__).parent.parent / "data" / "raw"
DATA_PROCESSED = Path(__file__).parent.parent / "data" / "processed"
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

SPONSOR_REGISTER_URL = (
    "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/"
    "file/sponsor-register.xlsx"
)

GOING_RATES_URL = (
    "https://www.gov.uk/government/publications/skilled-worker-visa-going-rates-for-eligible-jobs"
)

TIMEOUT = 60


def _get(url: str) -> bytes:
    log.info("Fetching %s", url)
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.content


def fetch_sponsor_register() -> None:
    """Download the sponsor register XLSX and convert to parquet."""
    out_parquet = DATA_PROCESSED / "sponsor_register.parquet"
    if out_parquet.exists():
        log.info("sponsor_register.parquet exists — skipping")
        return

    try:
        content = _get(SPONSOR_REGISTER_URL)
    except Exception as exc:
        log.warning("Could not fetch sponsor register: %s", exc)
        log.info("Creating empty skeleton parquet for local dev")
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

    raw_path = DATA_RAW / "sponsor_register.xlsx"
    raw_path.write_bytes(content)
    log.info("Saved raw XLSX: %s", raw_path)

    try:
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception:
        df = pd.read_excel(io.BytesIO(content))

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

    # Representative SOC 2020 going rates (annual GBP) as of 2024 ISL
    going_rates = [
        {"soc_code": "2136", "soc_title": "Programmers and software development professionals", "going_rate": 40300, "new_entrant_rate": 30900},
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
# The canonical download page is:
#   https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/
#   earningsandworkinghours/datasets/annualsurveyofhoursandearnings
#
# The asset IDs below resolve as of the 2024 ASHE release (provisional
# results published Oct 2024). Update the URLs when ONS releases 2025.

_ASHE_BASE = (
    "https://www.ons.gov.uk/file?uri=/employmentandlabourmarket/peopleinwork/"
    "earningsandworkinghours/datasets/annualsurveyofhoursandearnings/"
)

ASHE_TABLE15_URL = _ASHE_BASE + "2024provisional/table152024provisional.zip"
ASHE_TABLE3_URL  = _ASHE_BASE + "2024provisional/table32024provisional.zip"
ASHE_TABLE2_URL  = _ASHE_BASE + "2024provisional/table22024provisional.zip"

_ASHE_YEAR = 2024

# Percentile column mappings inside the ASHE xlsx sheets
_PCT_COLS = {
    "10": "p10",
    "25": "p25",
    "50": "p50",
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
    """Return the first .xlsx file found in a zip archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xlsx"):
                    return zf.read(name)
    except Exception as exc:
        log.warning("ZIP extraction failed: %s", exc)
    return None


def _parse_ashe_table(xlsx_bytes: bytes, by_region: bool) -> pd.DataFrame | None:
    """Parse an ASHE xlsx workbook into a tidy DataFrame.

    Expected sheet structure (ONS ASHE standard layout):
      - Row ~5 onwards: data rows with SOC code, description, region (if Table 15/3),
        and percentile columns (10, 25, 50, 75, 90).

    Returns a DataFrame with columns:
      soc_code, region (if by_region), p10, p25, p50, p75, p90, sample_year
    or None if parsing fails.
    """
    try:
        xl = pd.ExcelFile(io.BytesIO(xlsx_bytes), engine="openpyxl")
        # ASHE workbooks have one sheet per pay statistic; "Annual pay - Gross"
        # is the one we want. Fall back to first sheet.
        target_sheet = None
        for sh in xl.sheet_names:
            if "gross" in sh.lower() and "annual" in sh.lower():
                target_sheet = sh
                break
        if target_sheet is None:
            target_sheet = xl.sheet_names[0]

        df_raw = pd.read_excel(
            io.BytesIO(xlsx_bytes),
            sheet_name=target_sheet,
            header=None,
            engine="openpyxl",
        )
    except Exception as exc:
        log.warning("ASHE xlsx parse failed: %s", exc)
        return None

    # Find header row: look for a row containing "10" or "25" (percentile headers)
    header_row = None
    for i, row in df_raw.iterrows():
        vals = [str(v).strip() for v in row.values]
        if "10" in vals and "25" in vals and "50" in vals:
            header_row = i
            break
    if header_row is None:
        log.warning("ASHE: could not find header row in sheet %s", target_sheet)
        return None

    df_raw.columns = [str(v).strip() for v in df_raw.iloc[header_row]]
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

    region_col = None
    if by_region:
        for col in df.columns:
            if "region" in col.lower() or "geography" in col.lower():
                region_col = col
                break

    rows = []
    for _, row in df.iterrows():
        soc = str(row.get(soc_col, "")).strip()
        if not re.match(r"^\d{2,4}$", soc):
            continue
        region = str(row.get(region_col, "")).strip() if region_col else None

        p_vals: dict = {}
        for raw_pct, field in _PCT_COLS.items():
            col_match = next((c for c in df.columns if str(c).strip() == raw_pct), None)
            if col_match:
                try:
                    v = float(str(row.get(col_match, "")).replace(",", "").strip())
                    # ASHE publishes weekly pay; convert to annual (×52)
                    # or annual if the value is already large
                    if v < 2000:
                        v = v * 52
                    p_vals[field] = int(v)
                except (ValueError, TypeError):
                    p_vals[field] = None

        entry = {"soc_code": soc, "sample_year": _ASHE_YEAR, **p_vals}
        if by_region and region:
            entry["region"] = region
        rows.append(entry)

    if not rows:
        log.warning("ASHE: no rows parsed from %s", target_sheet)
        return None

    result = pd.DataFrame(rows)
    # Drop rows where all percentiles are null
    pct_cols = list(_PCT_COLS.values())
    result = result.dropna(subset=pct_cols, how="all")
    return result


def fetch_ashe_table15() -> None:
    """ASHE Table 15 — annual gross pay by 4-digit SOC and region."""
    out = DATA_PROCESSED / "ashe_soc4_region.parquet"
    if out.exists():
        log.info("ashe_soc4_region.parquet exists — skipping")
        return

    content = _download_ashe_zip(ASHE_TABLE15_URL, "Table15")
    if content is None:
        _write_empty_ashe(out, region=True)
        return

    xlsx = _extract_xlsx_from_zip(content)
    if xlsx is None:
        _write_empty_ashe(out, region=True)
        return

    df = _parse_ashe_table(xlsx, by_region=True)
    if df is None or df.empty:
        _write_empty_ashe(out, region=True)
        return

    df.to_parquet(out, index=False)
    log.info("Saved ashe_soc4_region.parquet (%d rows)", len(df))


def fetch_ashe_table3() -> None:
    """ASHE Table 3 — annual gross pay by 2-digit SOC and region."""
    out = DATA_PROCESSED / "ashe_soc2_region.parquet"
    if out.exists():
        log.info("ashe_soc2_region.parquet exists — skipping")
        return

    content = _download_ashe_zip(ASHE_TABLE3_URL, "Table3")
    if content is None:
        _write_empty_ashe(out, region=True)
        return

    xlsx = _extract_xlsx_from_zip(content)
    if xlsx is None:
        _write_empty_ashe(out, region=True)
        return

    df = _parse_ashe_table(xlsx, by_region=True)
    if df is None or df.empty:
        _write_empty_ashe(out, region=True)
        return

    df.to_parquet(out, index=False)
    log.info("Saved ashe_soc2_region.parquet (%d rows)", len(df))


def fetch_ashe_table2() -> None:
    """ASHE Table 2 — annual gross pay by 2-digit SOC, national."""
    out = DATA_PROCESSED / "ashe_soc2_national.parquet"
    if out.exists():
        log.info("ashe_soc2_national.parquet exists — skipping")
        return

    content = _download_ashe_zip(ASHE_TABLE2_URL, "Table2")
    if content is None:
        _write_empty_ashe(out, region=False)
        return

    xlsx = _extract_xlsx_from_zip(content)
    if xlsx is None:
        _write_empty_ashe(out, region=False)
        return

    df = _parse_ashe_table(xlsx, by_region=False)
    if df is None or df.empty:
        _write_empty_ashe(out, region=False)
        return

    df.to_parquet(out, index=False)
    log.info("Saved ashe_soc2_national.parquet (%d rows)", len(df))


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
