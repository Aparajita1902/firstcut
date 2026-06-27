"""Stage-0 — research scaffold (deterministic).

Pure code. Turns the intake form into the ``ResearchScaffold`` (Contract 0) that Stage 1
researches against. No model call. Stage 1 owns company-specific query tailoring; this just
resolves scope -> pillars -> buckets, attaches the in-scope catalogue, and carries the
toggles (generated path, talent-gap).
"""

from __future__ import annotations

from selection import PILLARS, PILLAR_BUCKETS

# Form scope choice -> pillars to research.
SCOPE_TO_PILLARS = {
    "Customer Service":     ["customer", "revenue", "operational"],
    "Finance & Accounting": ["financial"],
    "All AI opportunities": PILLARS[:],     # all five, plus generated path
}

DEFAULT_BUDGET_USD = 4.0


def _pillar_catalogue(catalogue: dict, pillars: list[str]) -> dict:
    """Best-effort slice of the capability catalogue for the in-scope pillars.

    The catalogue schema varies; we try a few common shapes and fall back to passing the
    whole thing through (Stage 1 can still use it). Keyed by pillar for the prompt.
    """
    out: dict[str, list] = {}
    if not isinstance(catalogue, dict):
        return out
    # shape A: {pillar_name: [entries]}
    alias = {
        "revenue": ["revenue", "revenue_intelligence", "Revenue Intelligence"],
        "customer": ["customer", "customer_intelligence", "Customer Intelligence", "Customer Service"],
        "operational": ["operational", "operational_intelligence", "Operational Intelligence"],
        "financial": ["financial", "financial_intelligence", "Financial Intelligence", "Finance & Accounting"],
        "workforce": ["workforce", "workforce_intelligence", "Workforce Intelligence", "Talent"],
    }
    for pillar in pillars:
        for key in alias.get(pillar, [pillar]):
            if key in catalogue:
                out[pillar] = catalogue[key]
                break
    return out


def build_scaffold(form_params: dict, catalogue: dict | None = None) -> dict:
    """Build the ResearchScaffold from form params + capability catalogue.

    Scope may arrive as ``scope_choices`` (a list, from the multi-select front-end) or
    as a single ``scope_choice`` string (legacy / direct callers). 'All AI opportunities'
    means all five pillars plus the generated industry path; otherwise pillars are the
    union of the selected catalogue areas.
    """
    catalogue = catalogue or {}

    choices = form_params.get("scope_choices")
    if not choices:
        single = form_params.get("scope_choice") or "All AI opportunities"
        choices = [single]

    if "All AI opportunities" in choices:
        pillars = PILLARS[:]
        scope_label = "All AI opportunities"
    else:
        pillars = []
        for c in choices:
            for p in SCOPE_TO_PILLARS.get(c, []):
                if p not in pillars:
                    pillars.append(p)
        if not pillars:                      # nothing valid selected -> broadest
            pillars = PILLARS[:]
            scope_label = "All AI opportunities"
        else:
            scope_label = " + ".join(choices)

    in_scope_buckets = []
    for p in pillars:
        in_scope_buckets.extend(PILLAR_BUCKETS.get(p, []))

    # Research always draws on the FULL capability catalogue (every pillar) and the
    # generated/industry path, regardless of the deck's scope. Scope still drives what
    # the deck leads with (in_scope_pillars / buckets above and AOTP filler downstream);
    # it no longer narrows what research is allowed to look at.
    full_catalogue = _pillar_catalogue(catalogue, PILLARS)
    generated_path = True

    role = form_params.get("audience_role", "CEO")
    if role == "Other" and form_params.get("other_role"):
        role = form_params["other_role"]

    materials = []
    for m in form_params.get("uploaded_meta", []) or []:
        materials.append({"filename": m.get("name", "upload"), "kind": m.get("kind", "pdf")})

    return {
        "company": form_params.get("company_name", ""),
        "hq": form_params.get("hq", ""),
        "ticker": form_params.get("ticker", ""),
        "key_countries": form_params.get("key_countries", ""),
        "audience_role": role,
        "scope_choice": scope_label,
        "scope_choices": choices,
        "in_scope_pillars": pillars,
        "in_scope_buckets": in_scope_buckets,
        "generated_path": generated_path,
        "include_talent_gap": bool(form_params.get("include_talent_gap", False)),
        "bucket_catalogue": full_catalogue,
        "canonical_materials": materials,
        "additional_notes": form_params.get("additional_notes", ""),
        "budget_usd": float(form_params.get("budget_usd", DEFAULT_BUDGET_USD)),
        "depth": form_params.get("depth", "standard"),
    }


if __name__ == "__main__":
    import json
    fp = {"company_name": "Their Care Pty Ltd", "hq": "Melbourne, Australia",
          "audience_role": "CFO", "scope_choice": "All AI opportunities",
          "include_talent_gap": True, "key_countries": "VIC, NSW, QLD, WA",
          "additional_notes": "Board mandate to lift EBITDA margin."}
    cat = {"Customer Service": [{"id": "x"}], "Finance & Accounting": [{"id": "y"}]}
    s = build_scaffold(fp, cat)
    print(json.dumps({k: v for k, v in s.items() if k != "bucket_catalogue"}, indent=2))
    print("bucket_catalogue keys:", list(s["bucket_catalogue"].keys()))
