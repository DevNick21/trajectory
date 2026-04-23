# Claude Code prompt — JSON-LD Tier 0 extractor

> Paste this entire file to Claude Code as the task brief. Read fully before writing code.
>
> **Scope:** add a pre-LLM parser that extracts structured fields from Schema.org `JobPosting` JSON-LD blocks in scraped HTML, before the Sonnet JD extractor ever runs. Additive. No live-path changes to existing behaviour unless JSON-LD is present.
>
> **When to run:** post-submission is safest. Pre-submission acceptable if all of prompt 01 is done and there are ≥6 hours before the deadline. The fix is small but touches `company_scraper.py` — the scraper is in the hot path.

---

## Why this exists

Two concrete weaknesses in the current pipeline that a JSON-LD pre-parser fixes:

1. **`extracted_jd.posted_date` is the weakest signal in the ghost-job detector.** The Sonnet JD extractor infers `posted_date` from whatever natural-language cue it can find ("posted 3 weeks ago" vs "2025-03-15"). Many postings have no explicit date in the body text but ship an accurate `datePosted` in the Schema.org JSON-LD block. Reading that field directly gives the ghost-job detector ground truth where today it gets inference.

2. **Salary bands are sometimes Schema.org-structured but not natural-language-stated.** A listing might have `{"baseSalary": {"minValue": 70000, "maxValue": 90000}}` in JSON-LD but only "competitive" in the body. Sonnet can't invent what isn't there; JSON-LD hands it over for free.

Specific sites with reliable `JobPosting` JSON-LD (known good as of April 2026):

- LinkedIn (`linkedin.com/jobs/view/...`)
- Workday (`*.myworkdayjobs.com`)
- Ashby (`jobs.ashbyhq.com`)
- Greenhouse (`boards.greenhouse.io`)
- Lever (`jobs.lever.co`)
- Civil Service Jobs (`civilservicejobs.service.gov.uk`)
- Indeed (`indeed.com/viewjob`) — inconsistent, but often present

Sites that don't reliably ship JSON-LD: small company sites on bespoke frameworks, some WordPress careers pages, Notion-hosted job boards.

## Reading you must do first

1. `src/trajectory/sub_agents/company_scraper.py` — specifically `_extract_jd`, `_fetch_html`, `_fetch_with_httpx`, `_html_to_text`.
2. `src/trajectory/schemas.py::ExtractedJobDescription` — know every field.
3. `src/trajectory/sub_agents/ghost_job_detector.py::_stale_signal` — uses `jd.posted_date`; this is the main consumer.
4. `src/trajectory/sub_agents/salary_data.py` — uses `posted_band`; also a consumer.
5. `PROCESS.md` — numbering for new entry.

## What to build

A new module `src/trajectory/sub_agents/jsonld_extractor.py` (not a sub-agent in the LLM sense, but fits the folder convention — it's scraping-adjacent).

One pure function:

```python
def extract_jsonld_jobposting(raw_html: str) -> Optional[JsonLdExtraction]:
    """Parse Schema.org JobPosting JSON-LD from raw HTML.

    Returns None if no parseable JobPosting block is found.
    Never raises — malformed JSON-LD returns None, not an exception.
    """
```

And a schema:

```python
class JsonLdExtraction(BaseModel):
    """Fields extracted from a JobPosting JSON-LD block.

    Only populated when the source is authoritative Schema.org. Values are
    ground truth — the Sonnet JD extractor should defer to these rather than
    re-inferring from body text.
    """
    title: Optional[str] = None
    date_posted: Optional[date] = None
    valid_through: Optional[date] = None
    hiring_organization_name: Optional[str] = None
    employment_type: Optional[str] = None  # FULL_TIME / PART_TIME / CONTRACTOR / etc.
    location: Optional[str] = None  # human-readable "City, Country" form
    salary_min_gbp: Optional[int] = None
    salary_max_gbp: Optional[int] = None
    salary_period: Optional[Literal["annual", "hourly", "daily", "monthly"]] = None
    description_plain: Optional[str] = None  # when present, cleaner than trafilatura output
    raw_fields_present: list[str] = Field(default_factory=list)  # for debug
```

## Implementation details

### What to parse

A JSON-LD block is `<script type="application/ld+json">` containing either:

- A single JSON object with `"@type": "JobPosting"`.
- An array of JSON objects, one of which has `"@type": "JobPosting"`.
- A `@graph` array containing a `JobPosting` object.
- Occasionally nested under Organization schema — traverse.

Multiple blocks on one page: pick the first `JobPosting` found. Log a warning if more than one is present (unusual; usually indicates the site ships both the listing page's JSON-LD and the company's Organization JSON-LD side by side, which is fine, but two `JobPosting` blocks on one page usually means the site has a bug worth noting).

### Fields to extract (Schema.org mapping)

| JSON-LD field | → | `JsonLdExtraction` field |
|---|---|---|
| `title` | → | `title` |
| `datePosted` (ISO 8601) | → | `date_posted` |
| `validThrough` (ISO 8601) | → | `valid_through` |
| `hiringOrganization.name` | → | `hiring_organization_name` |
| `employmentType` (string or array) | → | `employment_type` (first if array) |
| `jobLocation.address.addressLocality` + `addressCountry` | → | `location` as `"City, Country"` |
| `baseSalary.value.minValue` + `maxValue` | → | `salary_min_gbp`, `salary_max_gbp` |
| `baseSalary.value.unitText` | → | `salary_period` |
| `description` (HTML) → stripped | → | `description_plain` |

### Currency handling

`baseSalary.currency` is usually an ISO 4217 code ("GBP", "USD", "EUR"). Trajectory is UK-only.

- If currency is GBP: store as-is.
- If currency is anything else OR missing: **do not populate salary_min_gbp / salary_max_gbp.** Leave null. The JD extractor or salary_strategist can decide what to do with a non-GBP salary; this module doesn't convert.
- Log at DEBUG when skipping a non-GBP salary.

### Hourly/daily normalisation

`unitText` values encountered:

- `HOUR` / `hour` → `"hourly"`
- `DAY` / `day` → `"daily"`
- `WEEK` / `week` → log and skip (period rarely used for annual comparisons)
- `MONTH` / `month` → `"monthly"`
- `YEAR` / `year` / missing → `"annual"` (Schema.org default is YEAR when not specified; confirm against current Schema.org docs via web_search before trusting)

Do NOT multiply hourly values to produce an annual equivalent in this module. That's normalisation logic that belongs in `salary_data` or `salary_strategist`, not the extractor. Just surface the raw numbers with the correct `salary_period`.

### Robustness rules

- Wrap JSON parsing in try/except. Malformed JSON-LD is common; never let it crash the scraper.
- Values that are objects-wrapping-primitives (Schema.org sometimes nests `{"@value": "2025-03-15"}`) — unwrap safely with a helper.
- Bidi Unicode and zero-width characters can appear in JSON-LD strings. Strip them with the same helper `content_shield._strip_invisible` uses (import from there rather than duplicating).
- `datePosted` is sometimes a datetime (`"2025-03-15T10:00:00Z"`); parse with `dateutil.parser.isoparse` and take the date.
- Don't trust text that includes `[REDACTED:` — that's a shield marker from upstream content; skip the field.

### Integration into `company_scraper.run()`

The extractor runs between `_fetch_html` and `_extract_jd`. Modify `_extract_jd` to accept an optional `jsonld: Optional[JsonLdExtraction]` parameter, and when populated, include its fields in the user_input the Sonnet agent sees.

The Sonnet JD extractor prompt does NOT change. Instead, prepend a short structured block to the user_input it receives:

```python
user_input_parts = []
if jsonld is not None:
    user_input_parts.append(
        "GROUND-TRUTH FIELDS FROM SCHEMA.ORG (prefer these over inference from body text):\n"
        + json.dumps(jsonld.model_dump(exclude_none=True), default=str, indent=2)
    )
user_input_parts.append(f"JOB URL: {job_url}")
user_input_parts.append(f"POSTING PLATFORM HINT: {_host(job_url)}")
user_input_parts.append(f"<untrusted_content>\n{safe_jd}\n</untrusted_content>")
user_input = "\n\n".join(user_input_parts)
```

This is a small prompt-level nudge; the Sonnet extractor still runs and still emits `ExtractedJobDescription`, but now it has ground-truth fields to anchor against. Rule 7 compliance: Sonnet is still the right tier for this task; we haven't changed the model. We've just improved its input.

### Separate consumer: ghost-job detector

`sub_agents/ghost_job_detector.py::_stale_signal` reads `jd.posted_date`. The `ExtractedJobDescription` coming out of the (improved) extractor will have a more accurate `posted_date` when JSON-LD was present. No code change needed in the detector — it automatically benefits.

### Data flow invariant

The flow is:

```
raw_html
  → extract_jsonld_jobposting(raw_html) → JsonLdExtraction | None
  → Sonnet JD extractor (sees the JsonLdExtraction as ground-truth hint)
  → ExtractedJobDescription (authoritative)
```

`JsonLdExtraction` is an internal intermediate. It is NOT stored in `Session.phase1_output`, NOT passed to the verdict agent, NOT cited. The Sonnet extractor's `ExtractedJobDescription` remains the only JD representation in the bundle. This keeps the schema stable.

## Hard constraints

1. **Pure function, no I/O.** `extract_jsonld_jobposting` takes `raw_html` and returns. No HTTP calls, no DB writes, no logging at INFO level (DEBUG-only).
2. **Never raise.** Malformed input → return None. Crashing the scraper would be worse than missing a hint.
3. **BeautifulSoup is already a dependency.** Use it for the HTML parse. Do not add a new parser.
4. **No JSON Schema validation of the raw JSON-LD.** Sites ship non-conformant Schema.org all the time. Do field-by-field best-effort extraction; any field that doesn't parse stays null.
5. **Do not modify `ExtractedJobDescription`.** The `JsonLdExtraction` is a parallel type, not a modification of the existing schema.
6. **Do not cite JSON-LD fields.** Citations in the verdict must still resolve to scraped URL + snippet or gov_data or career_entry. JSON-LD is an input hint to the Sonnet extractor, not a citable source.
7. **Handle the ghost-job consequence.** If `jsonld.date_posted` exists and is > 30 days ago, `ghost_job_detector._stale_signal` now has a real citation. Check that the `Citation(kind="url_snippet", url=job_url, verbatim_snippet=f"Posted {jd.posted_date.isoformat()}")` still resolves — the snippet must appear verbatim in the scraped page text. If JSON-LD's `datePosted` doesn't match any text in the page body (e.g. the page only renders "3 weeks ago" and the date is only in `application/ld+json`), the citation will fail. If you encounter this, the signal's citation format needs to change — use `Citation(kind="url_snippet", url=job_url, verbatim_snippet="datePosted")` and include the JSON-LD block's raw text as one of the scraped_pages. Document this decision in code comments and PROCESS.md.

## Implementation plan

### Step 1 — Write and unit-test the extractor in isolation

Before touching `company_scraper.py`:

1. Create `src/trajectory/sub_agents/jsonld_extractor.py` with `extract_jsonld_jobposting`.
2. Create `tests/test_jsonld_extractor.py` with fixture HTML for each of the 7 known-good sites. Hardcode representative JSON-LD blocks as Python strings; don't fetch live (tests must be deterministic and offline).
3. Test cases:
   - LinkedIn: full JobPosting, GBP salary, annual period → all fields populated
   - Workday: nested under `@graph`, employment type as array → first element picked
   - Ashby: no salary, no valid_through → null salary, null valid_through
   - Greenhouse: datetime for datePosted → date only
   - Civil Service: salary in daily units → `salary_period = "daily"`
   - Indeed: currency = USD → salary fields null, DEBUG log emitted
   - Malformed JSON: partial brace → returns None, no raise
   - No JSON-LD block at all → returns None
   - Two JobPosting blocks → warns, returns first
4. Run tests. Iterate until all pass.

### Step 2 — Integrate into `company_scraper.run()`

1. After `_fetch_html(job_url)` produces `jd_text`, call the same URL's raw HTML separately — the current `_fetch_html` returns cleaned text via trafilatura, which has already stripped the `<script>` blocks. You need to fetch raw HTML *without* trafilatura cleaning for the JSON-LD pass.

   The cleanest way: extract `_fetch_html` into two functions — `_fetch_raw_html` (returns raw HTML) and `_html_to_text` (existing). `_fetch_html` becomes the compose of the two, preserving the current cache shape.

2. Call `extract_jsonld_jobposting(raw_html)` on the raw HTML. Store the result as `jsonld: Optional[JsonLdExtraction]`.

3. Pass `jsonld` to `_extract_jd` as a new optional parameter. `_extract_jd` prepends the ground-truth block to user_input when populated.

4. No change to the caching logic. `scraped_pages` still stores cleaned text only. JSON-LD extraction runs on raw HTML ephemerally.

### Step 3 — Tests

Add to `tests/test_jsonld_extractor.py` one integration test that exercises `_extract_jd` with a fake `jsonld` and asserts the user_input contains the ground-truth block in the expected format. Mock the Anthropic SDK for this — don't spend tokens testing string concat.

### Step 4 — Smoke test

Add `scripts/smoke_tests/jsonld_extractor.py`. Use one stable public URL (suggest Civil Service Jobs or a specific GitHub listing known to have JSON-LD). Assert the extractor returns a non-None `JsonLdExtraction` with a plausible `date_posted`. Register in `run_all.py` with `cheap=True` (no LLM call).

### Step 5 — PROCESS.md entry

Append:

**Entry N — JSON-LD Tier 0 extractor.**

Document:
- Trigger: ghost-job detector's `STALE_POSTING` signal relies on `jd.posted_date`, which was inferred by Sonnet from body text and often missing or wrong. Schema.org ships an authoritative `datePosted` in JSON-LD on major ATS providers.
- Decision: add a pre-LLM Tier 0 extractor that parses JSON-LD before Sonnet runs. Ground-truth fields prepended to the extractor's user_input; Sonnet defers to them.
- Architecture: pure function, no I/O, never raises. Output type `JsonLdExtraction` is an internal intermediate — not stored in the bundle, not cited.
- What it improves: `posted_date` accuracy on the 7 known-good ATS sites, `salary_band` on sites that ship structured but natural-language-absent salary. Indirectly, ghost-job detection becomes more accurate for legitimate postings (fewer false positives on fresh jobs mis-aged) and more decisive on real ghosts (more accurate age → cleaner HARD vs SOFT signal).
- What it doesn't do: citation source change, schema change, model change, currency conversion.
- Forward-looking: extend to Organization schema for `hiringOrganization` details (size, founded date, logo URL).

## Acceptance criteria

- [ ] `src/trajectory/sub_agents/jsonld_extractor.py` exists with one pure function.
- [ ] `schemas.py` has `JsonLdExtraction` added.
- [ ] `sub_agents/company_scraper.py::_extract_jd` accepts optional `jsonld` and prepends ground-truth block when populated.
- [ ] `_fetch_html` refactored into raw + clean if needed. Existing behaviour preserved.
- [ ] `tests/test_jsonld_extractor.py` exists with ≥ 8 test cases covering all Schema.org shapes listed.
- [ ] `scripts/smoke_tests/jsonld_extractor.py` runs against a real URL and asserts a non-None result.
- [ ] `PROCESS.md` has the new entry.
- [ ] `pytest tests/` all green. `ruff check` no new warnings.
- [ ] Trajectory's behaviour on URLs WITHOUT JSON-LD is identical to before (the optional arg is None, no prepended block).

## What NOT to do

- Do not modify `ExtractedJobDescription`.
- Do not cite JSON-LD fields in any verdict or generator output.
- Do not convert non-GBP salaries.
- Do not normalise hourly-to-annual in this module.
- Do not make the extractor async — it's pure and fast.
- Do not emit INFO-level logs for every parse (DEBUG only; scraper already logs at INFO for fetches).

## If you're unsure

Stop. Ask. The Schema.org shape varies by site and the docs are descriptive, not prescriptive. If the shape you encounter doesn't match what's documented here, surface the mismatch rather than guessing.
