"""Streamlit session history dashboard.

Run: streamlit run src/trajectory/dashboard/app.py
"""

from __future__ import annotations

import asyncio
import json

import streamlit as st

from ..config import settings
from ..storage import Storage


@st.cache_resource
def get_storage() -> Storage:
    storage = Storage()
    # asyncio.get_event_loop() is deprecated in 3.10 and raises RuntimeError
    # in 3.12+ when no loop is running. asyncio.run() creates, manages,
    # and closes a loop cleanly — correct for a synchronous Streamlit
    # caller that just needs a one-shot coroutine.
    asyncio.run(storage.initialise())
    return storage


def _run(coro):
    """Run an async coroutine from synchronous Streamlit context."""
    return asyncio.run(coro)


def main() -> None:
    st.set_page_config(page_title="Trajectory — History", page_icon="🗂️", layout="wide")
    st.title("Trajectory — Session History")

    storage = get_storage()

    # ── Sidebar controls ──────────────────────────────────────────────────
    with st.sidebar:
        st.header("Controls")
        user_id = st.text_input("User ID", value="")
        limit = st.slider("Sessions to show", 5, 50, 10)
        refresh = st.button("Refresh")

    if not user_id:
        st.info("Enter your Telegram user ID in the sidebar.")
        return

    sessions = _run(storage.get_recent_sessions(user_id, limit=limit))

    if not sessions:
        st.warning("No sessions found.")
        return

    st.subheader(f"{len(sessions)} recent sessions")

    for s in sessions:
        verdict_decision = "—"
        verdict_confidence = None
        # Session.verdict is always a Verdict model (storage coerces on save)
        if s.verdict:
            verdict_decision = s.verdict.decision
            verdict_confidence = s.verdict.confidence_pct

        icon = "✅" if verdict_decision == "GO" else ("🚫" if verdict_decision == "NO_GO" else "⏳")
        label = f"{icon} {s.intent} — {s.job_url or '(no URL)'}"
        conf_str = f"  ({verdict_confidence}% confidence)" if verdict_confidence else ""

        with st.expander(label + conf_str, expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Session ID:** `{s.session_id}`")
                st.write(f"**Intent:** {s.intent}")
                st.write(f"**Created:** {s.created_at.strftime('%Y-%m-%d %H:%M')}")
                if s.job_url:
                    st.write(f"**Job URL:** {s.job_url}")

            with col2:
                st.write(f"**Verdict:** {verdict_decision}")
                if verdict_confidence:
                    st.metric("Confidence", f"{verdict_confidence}%")

            if s.verdict:
                st.subheader("Verdict detail")
                verdict = s.verdict
                if verdict.headline:
                    st.write(f"**Headline:** {verdict.headline}")
                if verdict.hard_blockers:
                    st.error("Hard blockers")
                    for b in verdict.hard_blockers:
                        st.write(f"• **{b.type}** — {b.detail}")
                if verdict.stretch_concerns:
                    st.warning("Stretch concerns")
                    for c in verdict.stretch_concerns:
                        st.write(f"• {c.type}: {c.detail}")
                if verdict.reasoning:
                    st.subheader("Reasoning")
                    for r in verdict.reasoning:
                        st.write(f"• {r.claim}")

            if s.phase1_output:
                with st.expander("Phase 1 raw output"):
                    st.json(s.phase1_output)

            if s.generated_components:
                with st.expander("Generated components"):
                    st.json(s.generated_components)

    # ── Summary stats ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("Summary")
    go_count = sum(
        1 for s in sessions if s.verdict and s.verdict.decision == "GO"
    )
    st.metric("GO verdicts", go_count, delta=f"out of {len(sessions)}")


if __name__ == "__main__":
    main()
