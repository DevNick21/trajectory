"""Agent Skills packaging (PROCESS Entry 43, Workstream G).

Three skills bundled for the platform's Agent Skills runtime:
  - uk_cv_skill         — cv_tailor + render_cv_docx + render_cv_pdf + render_latex_pdf
  - uk_cover_letter_skill — cover_letter + render_cover_letter_docx + render_cover_letter_pdf
  - interview_prep_skill — question_designer + star_polisher + likely_questions

Each subdirectory contains a `SKILL.yaml` manifest declaring scripts +
instructions; progressive disclosure means the renderer subscript only
loads when the agent invokes it.

Trajectory's orchestrator registers these at startup. Until the
platform-side Skills runtime is wired, the skills are documentation-only;
the existing direct sub-agent dispatch in `orchestrator.py` continues
to work.
"""
