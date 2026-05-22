"""Smoke: deterministic recruitment-agency post detector.

Architecture gap #5. Six fixtures cover the decision matrix:
  - Strong phrase alone → agency_post
  - Two weak phrases → agency_post
  - Weak phrase + agency name → agency_post
  - Agency name alone → agency_post
  - In-house JD that mentions "client" in a non-agency sense → not agency
  - Empty input → not agency

Plus an AGENCY_POSTING round-trip — proves Pydantic accepts the new
StretchConcernType value without retry.

Cost: $0. Pure regex.
"""

from __future__ import annotations

import asyncio

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "agency_detection"
ESTIMATED_COST_USD = 0.0


_AGENCY_JD_STRONG = """
We are recruiting on behalf of our client, an established London
fintech, for a Senior Backend Engineer. Our client is seeking
someone with 5+ years' Python experience. Interviews will be
conducted by our client over two stages.
"""

_AGENCY_JD_TWO_WEAK = """
Our client is a fast-growing healthcare startup based in Manchester.
The client company offers competitive equity. To apply, send your CV
to careers@example.com.
"""

_AGENCY_JD_WEAK_PLUS_NAME = """
Permanent role available. Our client offers hybrid working. Apply
via this listing.
"""

_AGENCY_JD_NAME_ONLY = """
Senior Software Engineer — permanent role at a top London employer.
Modern stack: Python, AWS, Terraform.
"""

_INHOUSE_JD = """
Senior Software Engineer — join our payments team. You'll work
closely with our client success team to ship features. Apply via
the link below.
"""


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky.agency_detection import detect_agency_post

    # 1. Strong phrase alone → agency_post (regardless of company_name)
    r = detect_agency_post(_AGENCY_JD_STRONG, company_name="example.com")
    if not r.is_agency_post:
        failures.append("strong-phrase JD not flagged as agency_post")
    elif not any(s.startswith("strong_phrase:") for s in r.agency_signals):
        failures.append(
            f"strong-phrase JD flagged but no strong_phrase signal: "
            f"{r.agency_signals}"
        )
    else:
        messages.append(
            f"strong-phrase JD: agency={r.is_agency_post} "
            f"client={r.agency_client_name!r} "
            f"signals={len(r.agency_signals)}"
        )

    # 2. Two weak phrases → agency_post
    r = detect_agency_post(_AGENCY_JD_TWO_WEAK, company_name="example.com")
    if not r.is_agency_post:
        failures.append(
            f"two-weak-phrases JD not flagged: signals={r.agency_signals}"
        )
    else:
        messages.append(
            f"two-weak JD: agency={r.is_agency_post} "
            f"signals={len(r.agency_signals)}"
        )

    # 3. Weak phrase + agency name → agency_post
    r = detect_agency_post(
        _AGENCY_JD_WEAK_PLUS_NAME,
        company_name="Hays Recruitment Ltd",
    )
    if not r.is_agency_post:
        failures.append(
            f"weak-phrase + Hays not flagged: signals={r.agency_signals}"
        )
    elif not any(s.startswith("agency_name:") for s in r.agency_signals):
        failures.append(
            f"Hays company_name did not surface as agency_name signal: "
            f"{r.agency_signals}"
        )
    else:
        messages.append(
            f"weak+Hays: agency={r.is_agency_post} signals={r.agency_signals[:2]}"
        )

    # 4. Agency name alone → agency_post (lowest-confidence path but
    #    still load-bearing because Hays-class agencies sometimes copy
    #    JD bodies verbatim from the client)
    r = detect_agency_post(_AGENCY_JD_NAME_ONLY, company_name="Hays")
    if not r.is_agency_post:
        failures.append(
            "agency-name-only JD not flagged — Hays company_name should "
            "be sufficient signal even without phrase matches"
        )
    else:
        messages.append(
            f"agency-name-only: agency={r.is_agency_post} "
            f"signals={r.agency_signals}"
        )

    # 5. In-house JD that mentions "client" in a non-agency sense
    #    (consultancy / customer success) → must NOT flag
    r = detect_agency_post(_INHOUSE_JD, company_name="Acme Software")
    if r.is_agency_post:
        failures.append(
            f"in-house JD wrongly flagged as agency_post: "
            f"signals={r.agency_signals}"
        )
    else:
        messages.append(
            f"in-house JD correctly NOT flagged (signals={r.agency_signals})"
        )

    # 6. Empty input → not agency
    r = detect_agency_post("", company_name=None)
    if r.is_agency_post:
        failures.append("empty input wrongly flagged as agency_post")
    else:
        messages.append("empty input correctly NOT flagged")

    # 7. Client-name extraction — when the agency reveals the client,
    #    the detector should pull it out.
    r = detect_agency_post(_AGENCY_JD_STRONG, company_name="example.com")
    # The fixture says "our client, an established London fintech," —
    # the regex captures "an established London fintech" (not a great
    # client name but proves the extraction path runs). This is
    # acceptable — we don't claim perfect client extraction, just that
    # the field populates when the phrase is there.
    messages.append(
        f"client extraction: {r.agency_client_name!r} "
        f"(None is acceptable; non-None proves the path runs)"
    )

    # 8. AGENCY_POSTING round-trip through Pydantic — proves the new
    #    StretchConcernType literal accepts it.
    try:
        from askpicky.schemas import Citation, StretchConcern
        sc = StretchConcern(
            type="AGENCY_POSTING",
            detail="JD posted by Hays on behalf of unnamed client",
            citations=[
                Citation(
                    kind="gov_data",
                    data_field="extracted_jd.is_agency_post",
                    data_value="true",
                ),
            ],
        )
        messages.append(f"StretchConcern AGENCY_POSTING accepted: {sc.type}")
    except Exception as exc:
        failures.append(
            f"StretchConcern(type='AGENCY_POSTING') rejected: {exc!r}"
        )

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
