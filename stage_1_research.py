"""Stage 1 — Research (SPEC.md Section 5).

``run(form_params, file_ids, client, ...) -> research_dossier`` drives a medium-depth
(10–20 search) outside-in research pass with the Anthropic ``web_search_20250305`` tool,
optionally grounded on user-uploaded files (attached via the Files API), and returns a
structured dossier dict matching the named fields in the spec.
"""

from __future__ import annotations

import json
import os
from typing import Callable

import anthropic

import prompts
from api_retry import with_retries
from usage_tracker import check_budget

MODEL = "claude-sonnet-4-6"  # SPEC.md Section 6: Sonnet for Stage 1 research
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 20}
FILES_BETA = "files-api-2025-04-14"
MAX_CONTINUATIONS = 12  # server-tool pause_turn re-sends

# Per-stage cost ceiling. The pause_turn loop re-sends the growing message history
# (accumulated web-search results) on every continuation, so input cost compounds;
# this cap stops a pathological research run cold. Configurable via .env.
STAGE_1_BUDGET_USD = float(os.environ.get("STAGE_1_BUDGET_USD", "2.0"))


# --------------------------------------------------------------------------------- #
# File upload (Files API) — uploaded once at intake, ids reused through the run
# --------------------------------------------------------------------------------- #
def upload_user_files(client: anthropic.Anthropic, uploaded_files: list | None) -> list[str]:
    """Upload Streamlit ``UploadedFile`` objects via the Files API. Returns file ids.

    PDFs (and text) attach cleanly as document blocks downstream. DOCX is uploaded too;
    if the model can't read a given type it simply won't cite it — research still proceeds.
    """
    file_ids: list[str] = []
    for uf in uploaded_files or []:
        data = uf.getvalue() if hasattr(uf, "getvalue") else uf.read()
        mime = getattr(uf, "type", None) or "application/octet-stream"
        name = getattr(uf, "name", "upload")
        uploaded = client.beta.files.upload(
            file=(name, data, mime),
            betas=[FILES_BETA],
        )
        file_ids.append(uploaded.id)
    return file_ids


# --------------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------------- #
def _text_of(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model response that may carry prose or fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1] if cleaned.count("```") >= 2 else cleaned
        cleaned = cleaned.lstrip("json").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in research response.")
    return json.loads(cleaned[start : end + 1])


# --------------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------------- #
def run(
    form_params: dict,
    file_ids: list[str] | None,
    client: anthropic.Anthropic,
    today: str,
    progress: Callable[[str], None] | None = None,
    tracker=None,
) -> dict:
    file_ids = file_ids or []
    say = progress or (lambda _msg: None)

    prompt = prompts.research_prompt(form_params, today)

    # Build the user content: uploaded documents first (canonical), then the prompt.
    content: list = []
    for fid in file_ids:
        content.append({"type": "document", "source": {"type": "file", "file_id": fid}})
    content.append({"type": "text", "text": prompt})

    messages = [{"role": "user", "content": content}]

    use_beta = bool(file_ids)
    say("Researching company — running web searches…")

    final = None
    for _ in range(MAX_CONTINUATIONS):
        kwargs = dict(
            model=MODEL,
            max_tokens=16000,
            system=prompts.SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        )
        if use_beta:
            kwargs["betas"] = [FILES_BETA]
            _open_stream = lambda: client.beta.messages.stream(**kwargs)
        else:
            _open_stream = lambda: client.messages.stream(**kwargs)

        def _do_stream():
            with _open_stream() as stream:
                return stream.get_final_message()

        final = with_retries(_do_stream)

        if tracker is not None and getattr(final, "usage", None) is not None:
            tracker.record("stage_1", MODEL, final.usage)
            check_budget(tracker, "stage_1", STAGE_1_BUDGET_USD)

        if final.stop_reason == "pause_turn":
            # Server-tool loop hit its per-request cap; re-send to resume.
            messages.append({"role": "assistant", "content": final.content})
            continue
        break

    if final is None:
        raise RuntimeError("Stage 1 research produced no response.")
    if final.stop_reason == "refusal":
        raise RuntimeError("Stage 1 research was refused by the model.")

    text = _text_of(final)
    try:
        dossier = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # One stricter retry: ask the model to re-emit just the JSON it already produced.
        say("Researching company — tightening dossier format…")
        messages.append({"role": "assistant", "content": final.content})
        messages.append(
            {
                "role": "user",
                "content": "Return the research dossier as ONE valid JSON object only — "
                "no prose, no markdown fences. Use the exact keys specified.",
            }
        )
        retry = with_retries(lambda: client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=prompts.SYSTEM_PROMPT,
            messages=messages,
        ))
        if tracker is not None and getattr(retry, "usage", None) is not None:
            tracker.record("stage_1", MODEL, retry.usage)
            check_budget(tracker, "stage_1", STAGE_1_BUDGET_USD)
        dossier = extract_json(_text_of(retry))

    dossier.setdefault("source_index", [])
    say(f"Research complete — {len(dossier.get('source_index', []))} sources gathered.")
    return dossier


# --------------------------------------------------------------------------------- #
# v2 — Fact pack (research scaffold -> FactPack). Mirrors run() but uses the v2 prompt
# and returns the FactPack shape (Contract 1).
# --------------------------------------------------------------------------------- #
def run_factpack(
    scaffold: dict,
    file_ids: list[str] | None,
    client: anthropic.Anthropic,
    today: str,
    progress: Callable[[str], None] | None = None,
    tracker=None,
) -> dict:
    file_ids = file_ids or []
    say = progress or (lambda _msg: None)

    prompt = prompts.research_prompt_v2(scaffold, today)
    content: list = []
    for fid in file_ids:
        content.append({"type": "document", "source": {"type": "file", "file_id": fid}})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    use_beta = bool(file_ids)
    say("Building fact pack — running web searches…")

    final = None
    for _ in range(MAX_CONTINUATIONS):
        kwargs = dict(model=MODEL, max_tokens=16000, system=prompts.SYSTEM_PROMPT,
                      tools=[WEB_SEARCH_TOOL], messages=messages)
        if use_beta:
            kwargs["betas"] = [FILES_BETA]
            _open = lambda: client.beta.messages.stream(**kwargs)
        else:
            _open = lambda: client.messages.stream(**kwargs)

        def _do():
            with _open() as stream:
                return stream.get_final_message()

        final = with_retries(_do)
        if tracker is not None and getattr(final, "usage", None) is not None:
            tracker.record("stage_1", MODEL, final.usage)
            check_budget(tracker, "stage_1", STAGE_1_BUDGET_USD)
        if final.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": final.content})
            continue
        break

    if final is None:
        raise RuntimeError("Stage 1 fact pack produced no response.")
    if final.stop_reason == "refusal":
        raise RuntimeError("Stage 1 fact pack was refused by the model.")

    try:
        fp = extract_json(_text_of(final))
    except (ValueError, json.JSONDecodeError):
        messages.append({"role": "assistant", "content": final.content})
        messages.append({"role": "user", "content":
                         "Return the fact pack as ONE valid JSON object only — no prose, no fences."})
        retry = with_retries(lambda: client.messages.create(
            model=MODEL, max_tokens=16000, system=prompts.SYSTEM_PROMPT, messages=messages))
        if tracker is not None and getattr(retry, "usage", None) is not None:
            tracker.record("stage_1", MODEL, retry.usage)
            check_budget(tracker, "stage_1", STAGE_1_BUDGET_USD)
        fp = extract_json(_text_of(retry))

    fp.setdefault("facts", [])
    fp.setdefault("company", scaffold.get("company", ""))
    fp.setdefault("industry_opportunities", [])
    fp.setdefault("delivery_capability_facts", [])
    say(f"Fact pack complete — {len(fp.get('facts', []))} facts, "
        f"{len(fp.get('industry_opportunities', []))} industry opportunities.")
    return fp
