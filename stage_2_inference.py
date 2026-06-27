"""Stage 2 — Inference and storylining (SPEC.md Section 5).

Runs the seven sequential prompts (thesis-v1 step A/B, Sections 1–4, thesis-v2 +
synthesis) using the model mix from SPEC.md Section 6 — Opus for thesis + synthesis,
Sonnet for the sections. The shared system prompt, capability catalogue, and brand JSON
are sent as cached system blocks on every call. Inline ``assumptions[]`` and
``validation_flags[]`` are captured from each call's JSON output (no post-hoc extraction).

``run(...)`` returns a dict:
    {
      "deck_spec": {...},                 # page-wise spec for Stage 3
      "sources_by_section": {...},        # grouped, for Stage 4
      "assumptions_by_section": {...},    # grouped, for Stage 4
      "validation_flags": [...],          # prioritised single list, for Stage 4
      "slide_count": int,
    }
"""

from __future__ import annotations

import json
import os
from typing import Callable

import anthropic

import prompts
from api_retry import with_retries
from stage_1_research import _text_of, extract_json
from usage_tracker import check_budget

OPUS = "claude-opus-4-7"      # SPEC.md Section 6: thesis + synthesis
SONNET = "claude-sonnet-4-6"  # SPEC.md Section 6: section drafting

# Per-stage cost ceiling. All of Stage 2 (candidates + regenerations + sections +
# synthesis) records under the single "stage_2" key, so this cap also bounds runaway
# regeneration cost. Configurable via .env.
STAGE_2_BUDGET_USD = float(os.environ.get("STAGE_2_BUDGET_USD", "5.0"))

_SECTION_LABELS = {
    "section_1": "Section 1 — Company context",
    "section_2": "Section 2 — Opportunity buckets",
    "section_3": "Section 3 — Deep-dives",
    "section_4": "Section 4 — Engagement",
}


def _system_blocks(catalogue: dict, brand: dict, dossier: dict) -> list[dict]:
    """System prefix cached on every Stage 2 call: prompt + catalogue + brand + dossier.

    The cache breakpoint sits on the LAST block (the dossier), so the whole prefix is
    cached. The dossier is the largest per-run payload and was previously re-sent in the
    user message on every section call; putting it here means the six back-to-back calls
    in ``run_finalize`` pay a single cache-write then cache-reads, instead of full input
    each time. (The cache will be cold across the storyline pause — ephemeral TTL is ~5
    min vs unbounded human time — so the win is intra-finalize, by design.)"""
    return [
        {"type": "text", "text": prompts.SYSTEM_PROMPT},
        {
            "type": "text",
            "text": "# CAPABILITY CATALOGUE (JSON)\n"
            + json.dumps(catalogue, ensure_ascii=False),
        },
        {
            "type": "text",
            "text": "# BRAND (JSON)\n" + json.dumps(brand, ensure_ascii=False),
        },
        {
            "type": "text",
            "text": "# RESEARCH DOSSIER (JSON)\n"
            "This is the Stage-1 research dossier for the target company. Use it as the "
            "factual base for every section; cite its source ids where the schema asks.\n"
            + json.dumps(dossier, ensure_ascii=False),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _call_json(
    client: anthropic.Anthropic,
    model: str,
    system_blocks: list[dict],
    prompt: str,
    thinking: dict,
    tracker=None,
) -> dict:
    """Single JSON-returning call with one stricter retry on parse failure
    (SPEC.md Section 6: "Invalid output JSON ... retry once with stricter formatting")."""
    messages = [{"role": "user", "content": prompt}]
    resp = with_retries(lambda: client.messages.create(
        model=model,
        max_tokens=16000,
        system=system_blocks,
        thinking=thinking,
        messages=messages,
    ))
    if tracker is not None and getattr(resp, "usage", None) is not None:
        tracker.record("stage_2", model, resp.usage)
        check_budget(tracker, "stage_2", STAGE_2_BUDGET_USD)
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Stage 2 call ({model}) was refused by the model.")
    try:
        return extract_json(_text_of(resp))
    except (ValueError, json.JSONDecodeError):
        messages.append({"role": "assistant", "content": resp.content})
        messages.append(
            {
                "role": "user",
                "content": "Your previous reply was not parseable. Return ONLY the single "
                "JSON object specified — no prose, no markdown fences, exact keys.",
            }
        )
        retry = with_retries(lambda: client.messages.create(
            model=model,
            max_tokens=16000,
            system=system_blocks,
            thinking=thinking,
            messages=messages,
        ))
        if tracker is not None and getattr(retry, "usage", None) is not None:
            tracker.record("stage_2", model, retry.usage)
            check_budget(tracker, "stage_2", STAGE_2_BUDGET_USD)
        return extract_json(_text_of(retry))


def _collect_flags(*outputs: dict) -> list[dict]:
    flags: list[dict] = []
    for out in outputs:
        flags.extend(out.get("validation_flags") or [])
    return flags


def run_candidates(
    dossier: dict,
    form_params: dict,
    catalogue: dict,
    brand: dict,
    client: anthropic.Anthropic,
    excluded_archetypes: list | None = None,
    progress: Callable[[str], None] | None = None,
    tracker=None,
) -> dict:
    """Phase 2A — generate 3 storyline candidates only. Cheap call to expose to
    the user for selection before committing the rest of the pipeline."""
    say = progress or (lambda _msg: None)
    system_blocks = _system_blocks(catalogue, brand, dossier)
    opus_thinking = {"type": "adaptive"}

    say("Drafting storyline candidates…")
    candidates = _call_json(
        client, OPUS, system_blocks,
        prompts.thesis_v1_step_a(dossier, form_params, excluded_archetypes or []),
        opus_thinking, tracker=tracker,
    )
    return {
        "candidates": candidates.get("candidates") or [],
        "assumptions": candidates.get("assumptions") or [],
        "validation_flags": candidates.get("validation_flags") or [],
    }


def run_finalize(
    dossier: dict,
    form_params: dict,
    chosen_candidate: dict,
    candidate_assumptions: list,
    candidate_flags: list,
    catalogue: dict,
    brand: dict,
    client: anthropic.Anthropic,
    progress: Callable[[str], None] | None = None,
    tracker=None,
) -> dict:
    """Phase 2B — given the user-chosen storyline candidate, run step_b + the four
    section prompts + thesis_v2 synthesis. Returns the same dict shape ``run()`` used
    to so that downstream stages don't change."""
    say = progress or (lambda _msg: None)
    system_blocks = _system_blocks(catalogue, brand, dossier)
    opus_thinking = {"type": "adaptive"}
    sonnet_thinking = {"type": "disabled"}

    # --- Step B: elaborate the chosen candidate into thesis_v1 ----------------- #
    say("Elaborating chosen storyline…")
    thesis_v1 = _call_json(
        client, OPUS, system_blocks,
        prompts.thesis_v1_step_b(dossier, form_params, chosen_candidate),
        opus_thinking, tracker=tracker,
    )

    # --- Sections (Sonnet) ----------------------------------------------------- #
    say("Drafting Section 1 — company context…")
    s1 = _call_json(client, SONNET, system_blocks,
                    prompts.section_1(dossier, form_params, thesis_v1),
                    sonnet_thinking, tracker=tracker)
    say("Drafting Section 2 — opportunity buckets…")
    s2 = _call_json(client, SONNET, system_blocks,
                    prompts.section_2(dossier, form_params, thesis_v1),
                    sonnet_thinking, tracker=tracker)
    say("Drafting Section 3 — opportunity deep-dives…")
    s3 = _call_json(client, SONNET, system_blocks,
                    prompts.section_3(dossier, form_params, thesis_v1, s2),
                    sonnet_thinking, tracker=tracker)
    say("Drafting Section 4 — engagement…")
    s4 = _call_json(client, SONNET, system_blocks,
                    prompts.section_4(dossier, form_params, thesis_v1),
                    sonnet_thinking, tracker=tracker)

    sections = {"section_1": s1, "section_2": s2, "section_3": s3, "section_4": s4}
    candidate_envelope = {"assumptions": candidate_assumptions, "validation_flags": candidate_flags}
    all_flags = _collect_flags(candidate_envelope, thesis_v1, s1, s2, s3, s4)

    # --- Thesis-v2 + synthesis (Opus) ------------------------------------------ #
    say("Refining thesis and prioritising validation flags…")
    v2 = _call_json(client, OPUS, system_blocks,
                    prompts.thesis_v2_synthesis(dossier, form_params, thesis_v1, sections, all_flags),
                    opus_thinking, tracker=tracker)

    # --- Assemble outputs ------------------------------------------------------ #
    company = form_params.get("company_name", "Target company")
    subtitle = v2.get("title_subtitle") or thesis_v1.get("subtitle", "")
    thesis_line = v2.get("refined_thesis_line") or thesis_v1.get("thesis_line", "")

    deck_spec = {
        "title_slide": {"title": company, "subtitle": subtitle},
        "thesis": {
            "line": thesis_line,
            "subtitle": subtitle,
            "archetype": thesis_v1.get("chosen_archetype"),
            "storyline": thesis_v1.get("storyline"),
            "synthesis_rationale": v2.get("rationale"),
        },
        "sections": sections,
    }

    sources_by_section = {}
    assumptions_by_section = {}
    for key, label in _SECTION_LABELS.items():
        src = sections[key].get("sources_used") or []
        if src:
            sources_by_section[label] = src
        assum = sections[key].get("assumptions") or []
        if assum:
            assumptions_by_section[label] = assum

    thesis_assumptions = (
        (candidate_assumptions or [])
        + (thesis_v1.get("assumptions") or [])
        + (v2.get("assumptions") or [])
    )
    if thesis_assumptions:
        assumptions_by_section = {"Thesis & positioning": thesis_assumptions, **assumptions_by_section}

    validation_flags = v2.get("prioritized_validation_flags") or all_flags
    slide_count = 1 + sum(len(sections[k].get("slides") or []) for k in _SECTION_LABELS)

    return {
        "deck_spec": deck_spec,
        "sources_by_section": sources_by_section,
        "assumptions_by_section": assumptions_by_section,
        "validation_flags": validation_flags,
        "slide_count": slide_count,
    }


# Backwards-compatible single-call entrypoint — kept for any direct callers.
# Picks the first candidate automatically (no UI pause). New flow uses
# run_candidates + run_finalize instead.
def run(
    dossier: dict,
    form_params: dict,
    catalogue: dict,
    brand: dict,
    client: anthropic.Anthropic,
    progress: Callable[[str], None] | None = None,
    tracker=None,
) -> dict:
    cand = run_candidates(dossier, form_params, catalogue, brand, client,
                          progress=progress, tracker=tracker)
    if not cand["candidates"]:
        raise RuntimeError("Stage 2 produced no storyline candidates.")
    return run_finalize(
        dossier, form_params, cand["candidates"][0],
        cand["assumptions"], cand["validation_flags"],
        catalogue, brand, client, progress=progress, tracker=tracker,
    )


# =================================================================================== #
# v2 pipeline — hypotheses -> (code selection) -> storyline. Coexists with legacy run().
# =================================================================================== #
import selection as _selection


def _system_blocks_v2(catalogue: dict, brand: dict, fact_pack: dict) -> list[dict]:
    """Cached system prefix for v2 calls: prompt + catalogue + brand + fact pack."""
    return [
        {"type": "text", "text": prompts.SYSTEM_PROMPT},
        {"type": "text", "text": "# CAPABILITY CATALOGUE (JSON)\n" + json.dumps(catalogue, ensure_ascii=False)},
        {"type": "text", "text": "# BRAND (JSON)\n" + json.dumps(brand, ensure_ascii=False)},
        {"type": "text",
         "text": "# FACT PACK (JSON)\nThe Stage-1 fact pack for the target company. Cite its "
                 "fact ids where the schema asks.\n" + json.dumps(fact_pack, ensure_ascii=False),
         "cache_control": {"type": "ephemeral"}},
    ]


def run_hypotheses(
    fact_pack: dict, scaffold: dict, catalogue: dict, brand: dict,
    client: anthropic.Anthropic, progress=None, tracker=None,
) -> dict:
    """Step 2 — derive the hypothesis set from the fact pack."""
    say = progress or (lambda _m: None)
    say("Formulating hypotheses…")
    sysblocks = _system_blocks_v2(catalogue, brand, fact_pack)
    out = _call_json(client, OPUS, sysblocks,
                     prompts.hypotheses_prompt(fact_pack, scaffold),
                     {"type": "adaptive"}, tracker=tracker)
    return {
        "hypotheses": out.get("hypotheses") or [],
        "assumptions": out.get("assumptions") or [],
        "validation_flags": out.get("validation_flags") or [],
    }


def run_storyline(
    selection_obj: dict, fact_pack: dict, scaffold: dict, hypotheses: list,
    catalogue: dict, brand: dict, client: anthropic.Anthropic,
    progress=None, tracker=None,
) -> dict:
    """Step 4 — write the storyline from the chosen archetype + core hypotheses, then
    assemble the complete Storyline (Contract 4) by stitching in the code-selected AOTP
    cards, fixed delivery roles, and meta. Returns a dict ready for Stage 3 assembly."""
    say = progress or (lambda _m: None)
    by_id = {h.get("id"): h for h in hypotheses}
    core = [by_id[i] for i in selection_obj.get("core_hypotheses", []) if i in by_id]
    adjacent = [by_id[i] for i in selection_obj.get("adjacent_hypotheses", []) if i in by_id]

    say("Writing storyline…")
    sysblocks = _system_blocks_v2(catalogue, brand, fact_pack)
    sl = _call_json(client, OPUS, sysblocks,
                    prompts.storyline_prompt(selection_obj, fact_pack, scaffold, core, adjacent),
                    {"type": "adaptive"}, tracker=tracker)

    company = scaffold.get("company", "")
    meta_in = sl.get("meta") or {}
    storyline = {
        "meta": {
            "company": company,
            "audience_role": scaffold.get("audience_role"),
            "chosen_archetype": selection_obj.get("chosen_archetype"),
            "lens_label": meta_in.get("lens_label", ""),
            "thesis_line": meta_in.get("thesis_line", ""),
            "subtitle": meta_in.get("subtitle", ""),
        },
        "title": {"title": company},
        "strategic_context": sl.get("strategic_context", {}),
        "art_of_the_possible": {
            "company": company,
            "subtitle": "Capabilities across our intelligence pillars \u2014 the full art of the possible, not only the deep-dives.",
            "cards": selection_obj.get("aotp_cards", []),
        },
        "opportunity_areas": sl.get("opportunity_areas", {}),
        "deep_dives": sl.get("deep_dives", []),
    }

    if scaffold.get("include_talent_gap"):
        wr = sl.get("workforce_readiness") or {}
        wr["roles"] = ["FDC", "FDE", "Data Engineer", "FDO"]   # fixed
        wr.setdefault("columns", [d.get("title", "") for d in storyline["deep_dives"]])
        wr.setdefault("method_note",
                      "Inferred from public hiring signals, leadership scan, and tech-stack "
                      "disclosures. Confirmed via Aistra Sprints.")
        wr.setdefault("recommendations", [])
        wr.setdefault("heatmap", [])
        storyline["workforce_readiness"] = wr

    storyline["_audit"] = {
        "chosen_archetype": selection_obj.get("chosen_archetype"),
        "rationale": selection_obj.get("rationale"),
        "scores": selection_obj.get("scores"),
        "core_hypotheses": selection_obj.get("core_hypotheses"),
        "adjacent_hypotheses": selection_obj.get("adjacent_hypotheses"),
        "out_hypotheses": selection_obj.get("out_hypotheses"),
        "thin_deck": selection_obj.get("thin_deck"),
        "assumptions": (sl.get("assumptions") or []),
        "validation_flags": (sl.get("validation_flags") or []),
    }
    return storyline


def run_v2(
    fact_pack: dict, scaffold: dict, catalogue: dict, brand: dict,
    client: anthropic.Anthropic, catalogue_coverage: dict | None = None,
    catalogue_opportunities: dict | None = None, progress=None, tracker=None,
) -> dict:
    """Full Stage 2 v2: hypotheses (LLM) -> selection (code) -> storyline (LLM)."""
    say = progress or (lambda _m: None)
    hyp = run_hypotheses(fact_pack, scaffold, catalogue, brand, client, progress, tracker)
    hypotheses = hyp["hypotheses"]
    if not hypotheses:
        raise RuntimeError("Stage 2 produced no hypotheses.")

    say("Selecting archetype and prioritising hypotheses…")
    sel = _selection.select(
        hypotheses,
        scaffold.get("audience_role", "CEO"),
        scaffold.get("in_scope_pillars", _selection.PILLARS),
        catalogue_coverage or {},
        catalogue_opportunities or {},
    )

    storyline = run_storyline(sel, fact_pack, scaffold, hypotheses,
                              catalogue, brand, client, progress, tracker)
    return {"storyline": storyline, "selection": sel, "hypotheses": hypotheses,
            "hypothesis_assumptions": hyp["assumptions"], "hypothesis_flags": hyp["validation_flags"]}
