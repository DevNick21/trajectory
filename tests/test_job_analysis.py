from askpicky.parsers import analyse_job_description


def test_local_jd_analysis_detects_skills_and_filters() -> None:
    analysis = analyse_job_description(
        """
        Senior Software Engineer

        Build Python and TypeScript services with FastAPI, React, PostgreSQL,
        Docker, and AWS. Candidates need 4+ years of production experience.
        Applicants must have the right to work in the UK.
        """
    )

    assert analysis.role_title == "Senior Software Engineer"
    assert "python" in analysis.required_skills
    assert "typescript" in analysis.required_skills
    assert "right to work" in {item.label for item in analysis.hard_filters}
    assert analysis.application_priority == "maybe_apply_after_checking_filters"
    assert analysis.role_breakdown
    assert analysis.evidence_checkpoints
    assert any("python" in item.requirement for item in analysis.evidence_checkpoints)
    assert analysis.missing_evidence_prompts
    assert analysis.unsupported_claim_warnings
