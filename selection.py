"""Stage-2 step 3 — archetype + hypothesis-cluster selection (deterministic).

Pure code. No model call. Consumes the LLM-tagged ``HypothesisSet`` (Contract 2) and the
audience role, scores every (archetype + its supporting hypotheses) pair, and returns the
``Selection`` (Contract 3): the chosen archetype, the core/adjacent/out classification, the
scope-driven Art-of-the-Possible cards, and the deep-dive count.

Because all judgement already happened in step 2 (the LLM assigned evidence_strength, the
candidate archetypes, and the bucket/pillar), step 3 is arithmetic over those tags — cheap,
reproducible, auditable, and guaranteed to keep archetype and hypotheses in sync.
"""

from __future__ import annotations

# --------------------------------------------------------------------------------- #
# Constants (the locked decisions)
# --------------------------------------------------------------------------------- #
PILLARS = ["revenue", "customer", "operational", "financial", "workforce"]

PILLAR_BUCKETS = {
    "revenue":     ["revenue_pricing", "revenue_crosssell"],
    "customer":    ["customer_conversational", "customer_churn"],
    "operational": ["operational_docs", "operational_orchestration"],
    "financial":   ["financial_collections", "financial_fraud"],
    "workforce":   ["workforce_planning", "workforce_knowledge"],
}

# Representative icon per pillar (cards repeat the pillar icon — confirmed).
PILLAR_ICON = {
    "revenue": "revenue_crosssell",
    "customer": "customer_conversational",
    "operational": "operational_docs",
    "financial": "financial_collections",
    "workforce": "workforce_planning",
}

ARCHETYPES = [
    "numbers_led", "competitive_position_led", "risk_urgency_led", "operating_leverage_led",
    "capability_asymmetry_led", "quality_discipline_led", "re_rating_led",
    "defense_protection_led", "customer_evolution_led", "growth_acceleration_led",
    "sequencing_led", "pivot_refocus_led",
]

# Approved audience-fit matrix (0-3). "Other" inherits the closest role's column.
AUDIENCE_FIT = {
    "CFO":            {"numbers_led": 3, "operating_leverage_led": 3, "competitive_position_led": 1,
                       "risk_urgency_led": 2, "capability_asymmetry_led": 1, "quality_discipline_led": 2,
                       "re_rating_led": 3, "defense_protection_led": 2, "customer_evolution_led": 1,
                       "growth_acceleration_led": 2, "sequencing_led": 1, "pivot_refocus_led": 2},
    "CIO":            {"numbers_led": 1, "operating_leverage_led": 2, "competitive_position_led": 1,
                       "risk_urgency_led": 1, "capability_asymmetry_led": 3, "quality_discipline_led": 3,
                       "re_rating_led": 0, "defense_protection_led": 2, "customer_evolution_led": 1,
                       "growth_acceleration_led": 1, "sequencing_led": 2, "pivot_refocus_led": 1},
    "CEO":            {"numbers_led": 2, "operating_leverage_led": 2, "competitive_position_led": 3,
                       "risk_urgency_led": 2, "capability_asymmetry_led": 2, "quality_discipline_led": 1,
                       "re_rating_led": 3, "defense_protection_led": 2, "customer_evolution_led": 3,
                       "growth_acceleration_led": 3, "sequencing_led": 2, "pivot_refocus_led": 3},
    "COO":            {"numbers_led": 2, "operating_leverage_led": 3, "competitive_position_led": 1,
                       "risk_urgency_led": 1, "capability_asymmetry_led": 1, "quality_discipline_led": 3,
                       "re_rating_led": 0, "defense_protection_led": 2, "customer_evolution_led": 1,
                       "growth_acceleration_led": 1, "sequencing_led": 3, "pivot_refocus_led": 2},
    "Promoter / Owner": {"numbers_led": 3, "operating_leverage_led": 3, "competitive_position_led": 2,
                       "risk_urgency_led": 3, "capability_asymmetry_led": 2, "quality_discipline_led": 1,
                       "re_rating_led": 3, "defense_protection_led": 2, "customer_evolution_led": 1,
                       "growth_acceleration_led": 3, "sequencing_led": 1, "pivot_refocus_led": 2},
}
# "Other" resolves to the closest role; default to CEO (broadest).
_ROLE_ALIASES = {"Promoter": "Promoter / Owner", "Owner": "Promoter / Owner", "Founder": "Promoter / Owner"}

EVIDENCE_FLOOR_DEEPDIVE = 3      # 1-5; below this cannot anchor a deep-dive
DEEPDIVE_MIN, DEEPDIVE_MAX = 4, 6
GENERATED_ALIGNMENT = 0.5        # fixed-medium for non-catalogue opportunities
AOTP_CARD_COUNT = 10


# --------------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------------- #
def normalize_role(role: str | None) -> str:
    if not role:
        return "CEO"
    role = role.strip()
    if role in AUDIENCE_FIT:
        return role
    if role in _ROLE_ALIASES:
        return _ROLE_ALIASES[role]
    return "CEO"  # "Other" / unknown -> broadest column


def _alignment(h: dict, catalogue_coverage: dict) -> float:
    """1.0 if the catalogue covers this opportunity; GENERATED_ALIGNMENT for generated."""
    if h.get("opportunity_source") == "generated":
        return GENERATED_ALIGNMENT
    ref = h.get("opportunity_ref")
    return 1.0 if catalogue_coverage.get(ref, False) else 0.4  # in catalogue list but uncovered


def _fit(role: str, arch: str) -> float:
    return AUDIENCE_FIT.get(role, AUDIENCE_FIT["CEO"]).get(arch, 0) / 3.0


# --------------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------------- #
def select(
    hypotheses: list[dict],
    audience_role: str,
    in_scope_pillars: list[str],
    catalogue_coverage: dict | None = None,
    catalogue_opportunities: dict | None = None,
) -> dict:
    """Return the Selection (Contract 3).

    catalogue_coverage:     {opportunity_ref: bool}  — does Aistra deliver it.
    catalogue_opportunities:{pillar: [{"id","label"}]} — for muted AOTP filler.
    """
    catalogue_coverage = catalogue_coverage or {}
    catalogue_opportunities = catalogue_opportunities or {}
    role = normalize_role(audience_role)

    # ---- score each (archetype + its cluster) ---------------------------------- #
    scores: dict[str, float] = {}
    clusters: dict[str, list[dict]] = {}
    for arch in ARCHETYPES:
        cluster = [h for h in hypotheses if arch in (h.get("candidate_archetypes") or [])]
        clusters[arch] = cluster
        body = sum(h.get("evidence_strength", 0) * _alignment(h, catalogue_coverage) for h in cluster)
        scores[arch] = round(_fit(role, arch) * body, 3)

    if not any(scores.values()):
        # no hypothesis tagged any archetype — degenerate; fall back to most-evidenced
        chosen = "operating_leverage_led"
    else:
        chosen = max(ARCHETYPES, key=lambda a: scores[a])

    # ---- classify hypotheses --------------------------------------------------- #
    def _hscore(h):
        return h.get("evidence_strength", 0) * _alignment(h, catalogue_coverage)

    chosen_cluster = sorted(clusters[chosen], key=_hscore, reverse=True)

    core, overflow = [], []
    for h in chosen_cluster:
        if h.get("evidence_strength", 0) >= EVIDENCE_FLOOR_DEEPDIVE and len(core) < DEEPDIVE_MAX:
            core.append(h)
        else:
            overflow.append(h)

    core_ids = {h["id"] for h in core}
    # adjacent: in-cluster but not core, OR strong (>=floor) but off the chosen archetype
    adjacent = list(overflow)
    for h in hypotheses:
        if h["id"] in core_ids:
            continue
        if h in adjacent:
            continue
        if chosen not in (h.get("candidate_archetypes") or []) and h.get("evidence_strength", 0) >= EVIDENCE_FLOOR_DEEPDIVE:
            adjacent.append(h)
    adjacent_ids = {h["id"] for h in adjacent}
    out = [h for h in hypotheses if h["id"] not in core_ids and h["id"] not in adjacent_ids]

    thin_deck = len(core) < DEEPDIVE_MIN

    # ---- Art-of-the-Possible cards (scope-driven, up to 10) -------------------- #
    aotp_cards = _build_aotp_cards(core, adjacent, out, in_scope_pillars, catalogue_opportunities)

    return {
        "chosen_archetype": chosen,
        "scores": scores,
        "rationale": _rationale(chosen, role, core, scores),
        "core_hypotheses": [h["id"] for h in core],
        "adjacent_hypotheses": [h["id"] for h in adjacent],
        "out_hypotheses": [h["id"] for h in out],
        "aotp_cards": aotp_cards,
        "deep_dive_count": len(core),
        "thin_deck": thin_deck,
    }


def _build_aotp_cards(core, adjacent, out, in_scope_pillars, catalogue_opportunities):
    """Up to 10 cards: core (deep-dive marked) -> adjacent -> muted catalogue filler."""
    cards, seen = [], set()

    def _add(h, relevance, deep_dive):
        ref = h.get("opportunity_ref") or h.get("ai_opportunity", {}).get("title")
        if ref in seen:
            return
        seen.add(ref)
        pillar = h.get("pillar") or "customer"
        cards.append({
            "opportunity_ref": ref,
            "pillar": pillar,
            "label": h.get("ai_opportunity", {}).get("title") or ref,
            "icon": PILLAR_ICON.get(pillar, "customer_conversational"),
            "relevance": relevance,
            "deep_dive": deep_dive,
        })

    for h in core:
        if len(cards) >= AOTP_CARD_COUNT:
            break
        _add(h, "core", True)
    for h in adjacent:
        if len(cards) >= AOTP_CARD_COUNT:
            break
        _add(h, "adjacent", False)
    for h in out:
        if len(cards) >= AOTP_CARD_COUNT:
            break
        _add(h, "out", False)

    # muted catalogue filler within in-scope pillars, round-robin, until 10
    if len(cards) < AOTP_CARD_COUNT:
        pools = {p: list(catalogue_opportunities.get(p, [])) for p in in_scope_pillars}
        while len(cards) < AOTP_CARD_COUNT and any(pools.values()):
            for p in in_scope_pillars:
                if not pools.get(p):
                    continue
                opp = pools[p].pop(0)
                ref = opp.get("id")
                if ref in seen:
                    continue
                seen.add(ref)
                cards.append({
                    "opportunity_ref": ref, "pillar": p, "label": opp.get("label", ref),
                    "icon": PILLAR_ICON.get(p, "customer_conversational"),
                    "relevance": "out", "deep_dive": False,
                })
                if len(cards) >= AOTP_CARD_COUNT:
                    break
    return cards[:AOTP_CARD_COUNT]


def _rationale(chosen, role, core, scores):
    n = len(core)
    return (f"Highest cluster score for {role}: {chosen} ({scores.get(chosen, 0)}), "
            f"carried by {n} well-evidenced hypothes{'is' if n == 1 else 'es'}.")


# --------------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------------- #
if __name__ == "__main__":
    hyps = [
        {"id": "H1", "pillar": "workforce", "opportunity_ref": "workforce_planning",
         "opportunity_source": "catalogue", "candidate_archetypes": ["operating_leverage_led", "numbers_led"],
         "evidence_strength": 4, "ai_opportunity": {"title": "Demand-matched rostering"}},
        {"id": "H2", "pillar": "operational", "opportunity_ref": "operational_docs",
         "opportunity_source": "catalogue", "candidate_archetypes": ["operating_leverage_led", "quality_discipline_led"],
         "evidence_strength": 5, "ai_opportunity": {"title": "Document automation"}},
        {"id": "H3", "pillar": "financial", "opportunity_ref": "financial_collections",
         "opportunity_source": "catalogue", "candidate_archetypes": ["numbers_led", "operating_leverage_led"],
         "evidence_strength": 3, "ai_opportunity": {"title": "Collections optimisation"}},
        {"id": "H4", "pillar": "customer", "opportunity_ref": "customer_churn",
         "opportunity_source": "catalogue", "candidate_archetypes": ["defense_protection_led"],
         "evidence_strength": 2, "ai_opportunity": {"title": "Churn signals"}},
        {"id": "H5", "pillar": "revenue", "opportunity_ref": "rev_dynamic_pricing",
         "opportunity_source": "generated", "candidate_archetypes": ["growth_acceleration_led", "numbers_led"],
         "evidence_strength": 4, "ai_opportunity": {"title": "Dynamic pricing"}},
    ]
    cov = {"workforce_planning": True, "operational_docs": True, "financial_collections": True, "customer_churn": True}
    cat = {"customer": [{"id": "customer_conversational", "label": "Conversational service"}],
           "revenue": [{"id": "revenue_crosssell", "label": "Cross-sell"}],
           "operational": [{"id": "operational_orchestration", "label": "Orchestration"}]}
    import json
    for role in ["CFO", "CIO", "CEO"]:
        sel = select(hyps, role, ["workforce", "operational", "financial", "customer", "revenue"], cov, cat)
        print(f"\n=== {role} ===")
        print("chosen:", sel["chosen_archetype"], "| core:", sel["core_hypotheses"],
              "| adjacent:", sel["adjacent_hypotheses"], "| out:", sel["out_hypotheses"])
        print("deep_dive_count:", sel["deep_dive_count"], "thin:", sel["thin_deck"],
              "| aotp cards:", len(sel["aotp_cards"]))
        print("top scores:", dict(sorted(sel["scores"].items(), key=lambda x: -x[1])[:3]))
