"""Orchestrator for the Aistra deck-generation pipeline (Phase 2).

``generate_deck`` runs the real pipeline:
    Stage 1 — research        (stage_1_research.run)      — Anthropic + web search
    Stage 2 — inference       (stage_2_inference.run)     — Anthropic (Opus + Sonnet)
    Stage 3 — deck creation   (MOCKED in Phase 2)         — placeholder .pptx written
    Stage 4 — outputs         (stage_4_outputs.run)       — pure Python markdown

Stage 3 is wired for real in Phase 3; for now a placeholder file is written to
``outputs/`` so the download button works end-to-end. A ``progress`` callback lets the
Streamlit UI surface step-by-step status.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from time import perf_counter
from typing import Callable

import anthropic
from dotenv import load_dotenv

import stage_1_research
import stage_2_inference
import stage_3_deck_creation
import stage_4_outputs
import research_scaffold
import selection as _selection
from usage_tracker import UsageTracker

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(_BASE_DIR, "outputs")
DATA_DIR = os.path.join(_BASE_DIR, "data")

# Hard per-deck cost ceiling across all stages. The per-stage caps are secondary
# guards; this is the binding limit (their sum exceeds it). Env-overridable.
TOTAL_BUDGET_USD = float(os.environ.get("TOTAL_BUDGET_USD", "8.0"))


def _sanitize_company_name(name: str) -> str:
    """"Baby Bunting Group Ltd." -> "Baby_Bunting_Group_Ltd"."""
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", name.strip())
    return cleaned.strip("_") or "Company"


def _load_json(filename: str) -> dict:
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as fh:
        return json.load(fh)


def generate_candidates(
    form_params: dict,
    uploaded_files: list | None = None,
    excluded_archetypes: list | None = None,
    progress: Callable[[str], None] | None = None,
    prior_state: dict | None = None,
) -> dict:
    """Phase 1 of the pipeline. Run Stage 1 research + Stage 2A storyline candidates.

    Returns a state dict the Streamlit UI persists in ``st.session_state``. After the
    user picks one (or regenerates), call ``generate_deck_from_storyline(state, ...)``.

    If ``prior_state`` is supplied (regeneration path), Stage 1 is SKIPPED and only
    Stage 2A is re-run with ``excluded_archetypes`` so the candidates differ from
    those already shown.
    """
    say = progress or (lambda _msg: None)
    uploaded_files = uploaded_files or []

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example)."
        )

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if prior_state is not None:
        # Regeneration: reuse dossier, tracker, catalogue, brand, client.
        client = prior_state["client"]
        catalogue = prior_state["catalogue"]
        brand = prior_state["brand"]
        dossier = prior_state["dossier"]
        tracker = prior_state["tracker"]
        started = prior_state["started"]
    else:
        client = anthropic.Anthropic()
        catalogue = _load_json("aistra_capability_catalogue.json")
        brand = _load_json("brand.json")
        tracker = UsageTracker(total_budget_usd=TOTAL_BUDGET_USD)
        started = perf_counter()

        say("Researching company…")
        file_ids = stage_1_research.upload_user_files(client, uploaded_files)
        dossier = stage_1_research.run(
            form_params, file_ids, client, today, progress=say, tracker=tracker
        )

    say("Generating storyline candidates…")
    cand = stage_2_inference.run_candidates(
        dossier, form_params, catalogue, brand, client,
        excluded_archetypes=excluded_archetypes or [],
        progress=say, tracker=tracker,
    )

    return {
        "stage": "candidates_ready",
        "candidates": cand["candidates"],
        "candidate_assumptions": cand["assumptions"],
        "candidate_flags": cand["validation_flags"],
        "dossier": dossier,
        "form_params": form_params,
        "catalogue": catalogue,
        "brand": brand,
        "tracker": tracker,
        "client": client,
        "today": today,
        "now": now,
        "started": started,
    }


def generate_deck_from_storyline(
    state: dict,
    chosen_candidate: dict,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Phase 2 of the pipeline. Given the candidate state from ``generate_candidates``
    and the user's choice, finish Stage 2 (sections + thesis_v2), run Stage 3 (deck
    assembly), run Stage 4 (audit trail), and return the output package."""
    say = progress or (lambda _msg: None)

    dossier = state["dossier"]
    form_params = state["form_params"]
    catalogue = state["catalogue"]
    brand = state["brand"]
    tracker = state["tracker"]
    client = state["client"]
    today = state["today"]
    now = state["now"]
    started = state["started"]

    say("Finalising storyline and drafting sections…")
    s2 = stage_2_inference.run_finalize(
        dossier, form_params, chosen_candidate,
        state.get("candidate_assumptions") or [],
        state.get("candidate_flags") or [],
        catalogue, brand, client,
        progress=say, tracker=tracker,
    )

    # Inject audience role + date into the deck spec so the title slide renders them.
    _audience = form_params.get("audience_role", "")
    if _audience == "Other":
        _audience = form_params.get("other_role", "") or "Other"
    s2["deck_spec"].setdefault("title_slide", {})
    s2["deck_spec"]["title_slide"]["audience_role"] = _audience
    s2["deck_spec"]["title_slide"]["date"] = today

    say("Assembling deck…")
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    timestamp = now.strftime("%Y%m%d_%H%M")
    company = form_params.get("company_name", "Target Company")
    deck_filename = f"Aistra_Pitch_{_sanitize_company_name(company)}_{timestamp}.pptx"
    deck_path = os.path.join(OUTPUTS_DIR, deck_filename)
    stage_3_deck_creation.run(
        s2["deck_spec"], brand, deck_path, client, progress=say, tracker=tracker,
    )

    say("Rendering audit trail…")
    duration_sec = perf_counter() - started
    package = stage_4_outputs.run(
        deck_path=deck_path,
        slide_count=s2["slide_count"],
        sources_by_section=s2["sources_by_section"],
        assumptions_by_section=s2["assumptions_by_section"],
        validation_flags=s2["validation_flags"],
        duration_sec=duration_sec,
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        usage_summary=tracker.summary(),
    )
    return package


# ---------------------------------------------------------------------------------- #
# Backwards-compatible single-call entrypoint — runs the whole pipeline end-to-end
# auto-picking the first candidate. Kept so any direct (non-UI) callers still work.
# The Streamlit app uses generate_candidates + generate_deck_from_storyline so the
# user can choose between candidates.
# ---------------------------------------------------------------------------------- #
def generate_deck(
    form_params: dict,
    uploaded_files: list | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    state = generate_candidates(form_params, uploaded_files, progress=progress)
    if not state["candidates"]:
        raise RuntimeError("Stage 2 produced no storyline candidates.")
    return generate_deck_from_storyline(state, state["candidates"][0], progress=progress)


# ---------------------------------------------------------------------------------- #
# v2 pipeline — hypothesis-led, straight-through (no manual storyline pick).
#   code scaffold -> Stage 1 fact pack -> Stage 2 hypotheses -> code selection
#   -> Stage 2 storyline -> Stage 3 assembly -> Stage 4 audit.
# ---------------------------------------------------------------------------------- #
def _catalogue_lookups(catalogue: dict, in_scope_pillars: list[str]) -> tuple[dict, dict]:
    """Derive (coverage, opportunities) for the selection step from the catalogue.

    coverage:      {opportunity_ref: True}  — Aistra delivers it (it's in the catalogue).
    opportunities: {pillar: [{"id","label"}]} — for muted AOTP filler.
    Best-effort over the catalogue's pillar slices; degrades gracefully if shapes differ.
    """
    coverage: dict = {}
    opportunities: dict = {}
    sliced = research_scaffold._pillar_catalogue(catalogue, in_scope_pillars)
    for pillar, entries in sliced.items():
        bucket_list = []
        for e in entries if isinstance(entries, list) else []:
            oid = e.get("id") or e.get("opportunity_id") or e.get("name")
            label = e.get("label") or e.get("title") or e.get("name") or oid
            if not oid:
                continue
            coverage[oid] = True
            bucket_list.append({"id": oid, "label": label})
        # also mark the fixed bucket ids for this pillar as covered (catalogue-backed)
        for b in _selection.PILLAR_BUCKETS.get(pillar, []):
            coverage.setdefault(b, True)
        opportunities[pillar] = bucket_list
    return coverage, opportunities


def generate_deck_v2(
    form_params: dict,
    uploaded_files: list | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    say = progress or (lambda _msg: None)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example).")

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    client = anthropic.Anthropic()
    catalogue = _load_json("aistra_capability_catalogue.json")
    brand = _load_json("brand.json")
    tracker = UsageTracker(total_budget_usd=TOTAL_BUDGET_USD)
    started = perf_counter()

    # Step 0 — research scaffold (code)
    scaffold = research_scaffold.build_scaffold(form_params, catalogue)

    # Step 1 — fact pack (LLM + search)
    file_ids = stage_1_research.upload_user_files(client, uploaded_files)
    fact_pack = stage_1_research.run_factpack(scaffold, file_ids, client, today,
                                              progress=say, tracker=tracker)

    # Steps 2-4 — hypotheses (LLM) -> selection (code) -> storyline (LLM)
    coverage, cat_opps = _catalogue_lookups(catalogue, scaffold["in_scope_pillars"])
    res = stage_2_inference.run_v2(fact_pack, scaffold, catalogue, brand, client,
                                   catalogue_coverage=coverage, catalogue_opportunities=cat_opps,
                                   progress=say, tracker=tracker)
    storyline = res["storyline"]
    storyline["meta"]["date"] = today

    # Step 5 — assemble (code)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    ts = now.strftime("%Y%m%d_%H%M")
    company = form_params.get("company_name", "Target Company")
    deck_path = os.path.join(OUTPUTS_DIR, f"Aistra_Pitch_{_sanitize_company_name(company)}_{ts}.pptx")
    asm = stage_3_deck_creation.run_v2(storyline, brand, deck_path, progress=say)

    # Stage 4 — audit pack
    say("Rendering audit trail…")
    audit = storyline.get("_audit", {})
    src_seen, sources = set(), []
    for f in fact_pack.get("facts", []):
        s = (f.get("source") or {})
        key = s.get("url") or s.get("title")
        if key and key not in src_seen:
            src_seen.add(key); sources.append(s)
    sources_by_section = {"Research fact pack": sources} if sources else {}
    assumptions_by_section = {}
    _assum = (res.get("hypothesis_assumptions") or []) + (audit.get("assumptions") or [])
    if _assum:
        assumptions_by_section = {"Hypotheses & storyline": _assum}
    validation_flags = (res.get("hypothesis_flags") or []) + (audit.get("validation_flags") or [])

    duration_sec = perf_counter() - started
    package = stage_4_outputs.run(
        deck_path=deck_path,
        slide_count=asm["slide_count"],
        sources_by_section=sources_by_section,
        assumptions_by_section=assumptions_by_section,
        validation_flags=validation_flags,
        duration_sec=duration_sec,
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        usage_summary=tracker.summary(),
    )
    package["selection_audit"] = audit
    return package
