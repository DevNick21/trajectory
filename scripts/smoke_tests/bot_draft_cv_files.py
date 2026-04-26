"""Smoke test — bot draft_cv handler delivers BOTH .docx and .pdf.

CLAUDE.md Rule 9 makes this an architectural promise, not a polish item:
the bot MUST send both a .docx and a .pdf via `send_document` so the user
can attach a real file to a real application. Today, only `phase4_cv`
exercises the orchestrator's `handle_draft_cv` end-to-end; nothing
verifies the *bot wrapper* (`_handle_draft_cv` in bot/handlers.py:519)
actually calls `context.bot.send_document` twice with the rendered files.

This test:
  - renders a synthetic CV through the real cv_docx + cv_pdf renderers,
    so we hit the actual file-on-disk path used in production,
  - patches `bot.handlers.handle_draft_cv` to return those pre-rendered
    paths (avoids the live LLM CV-tailoring path),
  - drives `_handle_draft_cv` with mocked `update` + `context`,
  - asserts `context.bot.send_document` was awaited twice with file paths
    matching the rendered docx + pdf.

Cost: $0 (no live LLM calls).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from ._common import (
    SmokeResult,
    build_synthetic_cv_output,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "bot_draft_cv_files"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


def _make_update(*, user_id: int, chat_id: int, text: str):
    """Mocked Update with the bits `_handle_draft_cv` actually touches.

    `reply_text` returns an AsyncMock with `.delete()` also AsyncMock so
    the handler's "Tailoring your CV…" placeholder can be deleted.
    """
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.document = None  # force chitchat path

    placeholder = MagicMock()
    placeholder.delete = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=placeholder)
    update.message.reply_html = AsyncMock()
    return update


def _make_context(storage):
    ctx = MagicMock()
    ctx.bot_data = {"storage": storage}
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


async def _body() -> tuple[list[str], list[str], float]:
    tmp = prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    from trajectory.bot import handlers as bot_handlers
    from trajectory.renderers.cv_docx import render_cv_docx
    from trajectory.renderers.cv_pdf import render_cv_pdf
    from trajectory.storage import Storage

    out_dir = tmp / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    cv = build_synthetic_cv_output(name="Smoke Test")
    docx_path = render_cv_docx(cv, out_dir, company="Acme")
    pdf_path = render_cv_pdf(cv, out_dir, company="Acme")

    if not docx_path.exists() or docx_path.stat().st_size == 0:
        failures.append(f"renderer produced empty docx at {docx_path}")
        return messages, failures, ESTIMATED_COST_USD
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        failures.append(f"renderer produced empty pdf at {pdf_path}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"rendered docx ({docx_path.stat().st_size}B) + pdf "
        f"({pdf_path.stat().st_size}B) into {out_dir}"
    )

    user = build_test_user("uk_resident")
    session = build_test_session(user.user_id, intent="draft_cv")

    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)
    await storage.save_session(session)

    # Patch the orchestrator's handle_draft_cv (re-exported into
    # bot.handlers as `handle_draft_cv`) to return our pre-rendered
    # files instead of running the live CV-tailoring pipeline.
    original_handle = bot_handlers.handle_draft_cv

    async def _fake_handle_draft_cv(sess, usr, stor):
        # Match the orchestrator's 4-tuple shape: (cv, docx, pdf, latex).
        # latex_pdf_path=None means the bot loop only sends docx + pdf
        # (the production no-pdflatex case).
        return cv, docx_path, pdf_path, None

    bot_handlers.handle_draft_cv = _fake_handle_draft_cv

    update = _make_update(user_id=42, chat_id=999_900_002, text="draft my cv")
    update.effective_user.id = user.user_id
    ctx = _make_context(storage)

    try:
        try:
            await bot_handlers._handle_draft_cv(
                update, ctx, user, storage, last_session=session,
            )
        except Exception as exc:
            failures.append(f"_handle_draft_cv raised: {exc!r}")
            return messages, failures, ESTIMATED_COST_USD

        send_doc = ctx.bot.send_document
        if send_doc.await_count != 2:
            failures.append(
                f"context.bot.send_document was awaited {send_doc.await_count} "
                "time(s); Rule 9 requires exactly 2 (.docx + .pdf) when no "
                "LaTeX render is present."
            )
        else:
            messages.append("context.bot.send_document awaited 2 times (docx + pdf)")

        # Inspect each call: chat_id is positional, document= is keyword.
        sent_paths: list[Path] = []
        for call in send_doc.await_args_list:
            args, kwargs = call
            doc = kwargs.get("document")
            if isinstance(doc, Path):
                sent_paths.append(doc)
            elif doc is not None:
                # Path subclass or duck-typed; record for diagnostics.
                sent_paths.append(Path(str(doc)))

        if docx_path not in sent_paths:
            failures.append(
                f"send_document was not called with the rendered docx: "
                f"sent={sent_paths}, expected={docx_path}"
            )
        if pdf_path not in sent_paths:
            failures.append(
                f"send_document was not called with the rendered pdf: "
                f"sent={sent_paths}, expected={pdf_path}"
            )

        if not failures:
            messages.append(
                f"both files delivered: {docx_path.name}, {pdf_path.name}"
            )

        # Sanity: the chat-bubble preview path should also have fired.
        if update.message.reply_html.await_count == 0:
            failures.append(
                "_handle_draft_cv did not call reply_html — preview chunks "
                "missing alongside the file delivery."
            )
    finally:
        bot_handlers.handle_draft_cv = original_handle
        await storage.close()

    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
