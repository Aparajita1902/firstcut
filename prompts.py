"""Prompt templates for the Aistra deck-generation pipeline.

This module holds:

- ``SYSTEM_PROMPT`` — the shared system prompt (Aistra positioning, voice/tone,
  output-schema rules, inline-tagging rules). Marked as cached in every Stage 2
  call alongside the capability catalogue and brand JSON.
- One function per Stage 2 prompt (SPEC.md Section 5, Stage 2). Each takes the
  relevant context and returns a prompt string.
- ``research_prompt`` for Stage 1.

Every Stage 2 prompt asks the model for a single JSON object that carries the
section's content plus inline ``assumptions[]`` and ``validation_flags[]`` arrays
(SPEC.md Section 5: "No separate post-hoc extraction"). The static JSON-schema
examples live in non-f-string constants so we never have to brace-escape them;
the dynamic context is prepended as a separate f-string header.
"""

from __future__ import annotations

import json

# --------------------------------------------------------------------------------- #
# Shared system prompt (cached)
# --------------------------------------------------------------------------------- #
SYSTEM_PROMPT = """\
You are Aistra's senior AI strategy consultant. You draft outside-in AI-opportunity \
pitch decks for prospective client companies. Your output is a strong first draft \
(~60% of a final consulting-grade deck) that an Aistra strategist edits the last mile.

# Who Aistra is
Aistra is an applied-AI consultancy. Tagline: "Better with AI". Aistra helps large
companies find and capture AI opportunities across five capability pillars:
- Revenue Intelligence — customer-facing growth (acquisition, conversion, retention, expansion).
- Customer Intelligence — service experience, conversational support, churn and retention signals.
- Operational Intelligence — cost-to-serve, document and process automation, orchestration.
- Financial Intelligence — the finance operating model (close, payables, receivables, collections, CFO analytics).
- Workforce Intelligence — capacity planning, rostering, and knowledge enablement.

The intake form sets the deck's SCOPE, which determines the lead pillars (the deck's emphasis):
- "Customer Service" leads on Customer, Revenue and Operational Intelligence.
- "Finance & Accounting" leads on Financial Intelligence.
- "All AI opportunities" leads across all five pillars.
Scope sets emphasis only. Research always draws on the full capability catalogue and the
company's whole economics — not just the lead pillars.

A capability catalogue (provided below in the system context as JSON) lists Aistra's proven
opportunities under each pillar, each with a `use_when` signal, a `problem_statement`, and
`typical_roi_metrics`. Two sourcing rules, kept distinct:
- Catalogue opportunities: select by matching `use_when` signals against the research —
  never fabricate a catalogue opportunity that is not in the JSON.
- Company-specific (generated) opportunities: where the company's economics warrant a play
  the catalogue does not cover, surface it through the generated/industry path. It must be
  grounded in sourced facts and tagged as generated. Discovery is expected here; fabrication
  is not.

# Approach
Outside-in: you reason from publicly available data plus any client-supplied materials. \
You never fabricate financials or facts. Where a number is not disclosed, you make an \
explicit, reasoned assumption and tag it. Where a material claim rests on an unverified \
assumption, you raise a validation flag so the strategist can confirm it with the client.

# Voice and tone (non-negotiable)
- Register: MBB management-consulting. Direct, declarative, senior.
- Numbers where defensible; ranges otherwise. Never a false-precision point estimate for ROI.
- Prose-leaning, not bullet-stuffed. Slides read like a partner wrote them.
- NO AI hype. Banned words/phrases: "revolutionary", "transformative", "world-class", \
"cutting-edge", "game-changing", "unlock", "supercharge", "seamless", "leverage" (as a verb), \
and any vague benefit claim with no number behind it.
- Do not stack buzzwords. Every sentence earns its place.

# Output rules (non-negotiable)
- Respond with EXACTLY ONE JSON object and nothing else. No prose before or after. \
No markdown code fences. No commentary.
- Use the exact keys named in the prompt. Do not add or rename top-level keys.
- All strings must be valid JSON (escape quotes and newlines).

# Inline-tagging rules
Every prompt's JSON output includes two arrays for that section:
- `assumptions`: each item is {"assumption": <the assumption stated plainly>, \
"basis": <why you made it — the evidence or comparable you reasoned from>}. \
Create an assumption whenever you assert or rely on a fact that is not directly \
disclosed in the dossier or uploaded files (e.g. an inferred volume, a sector-benchmark margin).
- `validation_flags`: each item is {"claim": <the material claim that needs confirming>, \
"slide_ref": <which slide/section it appears on>, "basis": <what it currently rests on>, \
"suggested_action": <the concrete validation step for the client team>, \
"impact": "high"|"medium"|"low", "uncertainty": "high"|"medium"|"low"}. \
Raise a flag for any material claim — especially ROI drivers and competitive-position \
claims — that rests on an assumption rather than disclosed fact. Every material ROI \
driver uncertainty becomes a validation flag.
If a section genuinely has no assumptions or flags, return an empty array for it — \
but most sections will have several."""


# --------------------------------------------------------------------------------- #
# Audience-shaping (SPEC.md Section 5, thesis step A)
# --------------------------------------------------------------------------------- #
_AUDIENCE_FRAMING = {
    "CIO": "Frame around capability, architecture, and delivery — how the AI gets built and run.",
    "CFO": "Frame around P&L mechanics, capital efficiency, and financial visibility.",
    "CEO": "Frame around strategic positioning, market dynamics, and competitive shape.",
    "COO": "Frame around the operating model, cost-to-serve curves, and process.",
}


def _audience_framing(form_params: dict) -> str:
    role = form_params.get("audience_role", "CIO")
    if role == "Other":
        other = form_params.get("other_role", "").strip() or "an unspecified executive"
        return (
            f"The audience role is '{other}'. Infer the closest archetype from "
            "{CIO: capability/architecture/delivery, CFO: P&L/capital efficiency/financial "
            "visibility, CEO: strategic positioning/market/competitive shape, COO: operating "
            "model/cost-to-serve/process} and frame the thesis accordingly."
        )
    return _AUDIENCE_FRAMING.get(role, _AUDIENCE_FRAMING["CIO"])


def _form_summary(form_params: dict) -> str:
    role = form_params.get("audience_role", "")
    if role == "Other" and form_params.get("other_role"):
        role = f"Other — {form_params['other_role']}"
    pillars = ", ".join(form_params.get("intelligence_pillars", [])) or "(none selected)"
    return (
        f"Company: {form_params.get('company_name', '')}\n"
        f"HQ / domicile: {form_params.get('hq', '') or 'unknown'}\n"
        f"Ticker + exchange: {form_params.get('ticker', '') or 'private / not given'}\n"
        f"Key countries: {form_params.get('key_countries', '') or 'not specified'}\n"
        f"Target audience role: {role}\n"
        f"Intelligence pillars selected: {pillars}\n"
        f"Additional context / notes: {form_params.get('additional_notes', '') or 'none'}"
    )


def _ctx_header(title: str, **blocks) -> str:
    """Build a dynamic context header. ``blocks`` values that are dict/list are
    JSON-dumped; strings are used verbatim."""
    parts = [f"# {title}"]
    for label, value in blocks.items():
        nice = label.replace("_", " ").upper()
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        parts.append(f"## {nice}\n{value}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------------- #
# Stage 1 — Research
# --------------------------------------------------------------------------------- #
_RESEARCH_INSTRUCTIONS = """\
You are building a research dossier on the target company described above, for an \
Aistra AI-opportunity pitch. Work outside-in from public sources, plus any uploaded \
files (treat uploaded files as canonical; the web fills gaps and adds context).

# Search plan
Run 10–20 web searches (medium depth). Prioritise sources in this order:
1. Official filings (annual report, investor presentations, regulatory disclosures)
2. Company website
3. News from the last 12 months
4. Industry / sector reports
5. Broker / analyst notes
6. LinkedIn (for leadership and headcount signals)
Dig deeper on the intelligence pillars the user selected — find the operational and \
financial signals that the `use_when` triggers in Aistra's catalogue key off (e.g. DSO, \
contact-centre scale, churn pressure, close-cycle pain, marketing spend).

# Grounding rules
- Every fact you record must carry a source: cite the source by its `id` in `source_index`.
- Do NOT fabricate financials. If a figure is not disclosed, omit it or mark it null and \
note the gap — do not guess inside the dossier (the inference stage handles assumptions).
- If research returns thin (private company, low-disclosure market), say so prominently in \
`research_quality` and proceed with what you have.

# Output
Respond with EXACTLY ONE JSON object, no prose, no markdown fences, with these keys:
{
  "company_overview": "string — what the company is, scale, business model",
  "financials": "string — disclosed revenue, margins, growth, relevant line items (with source ids)",
  "segments_and_geographies": "string — operating segments and key geographies",
  "strategic_moves": "string — recent strategy, M&A, transformation, stated priorities",
  "leadership": "string — relevant executives (esp. the target audience role) and any public AI/digital stance",
  "industry_context": "string — sector dynamics, regulation, structural pressures",
  "peer_set": ["string — named comparable companies"],
  "recent_news": "string — material news in the last 12 months",
  "pillar_focus": {
    "<pillar name>": "string — pillar-specific signals found (the operational/financial evidence that maps to Aistra opportunities)"
  },
  "research_quality": "string — how thin or rich the public disclosure is; any major data gaps",
  "source_index": [
    {"id": "S1", "title": "string", "url": "string", "accessed": "<today's date>", "type": "filing|website|news|industry|broker|linkedin"}
  ]
}
Use sequential ids S1, S2, … in `source_index`. Today's date (use as the accessed date) is provided in the context above."""


def research_prompt(form_params: dict, today: str) -> str:
    header = _ctx_header(
        "Target company",
        target=_form_summary(form_params),
        todays_date=today,
    )
    return header + "\n\n" + _RESEARCH_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 1: Thesis-v1 step A (Opus) — generate 3 storyline candidates
# --------------------------------------------------------------------------------- #
_ARCHETYPE_TAXONOMY = """\
12 STORYLINE ARCHETYPES (organizing principles, not topics):

★★★ HIGH-FIT FOR AISTRA PITCH CONTEXT — at least one of the three candidates MUST be from this tier:
- numbers_led: "Fix this specific commercial mechanic." Anchor on NRR/GRR, CAC payback, revenue per rep, cohort retention, unit economics.
- competitive_position_led: "Win against named competitors by doing X." Displacement, share-shift, moat-building.
- risk_urgency_led: "Do this before [window] closes." IPO window, regulatory deadline, capital cycle, competitive timing.
- operating_leverage_led: "Compound an underutilized asset." Existing customer base, existing data, existing distribution.
- capability_asymmetry_led: "You have a unique capability — productize / monetize / use yourself on it." Practice what you preach.
- quality_discipline_led: "The metric exists but the rigor doesn't." Instrument what's ad hoc.

★★☆ FITS SOME SITUATIONS:
- re_rating_led: "Change how the market values you." Multiple expansion, comp-set repositioning, narrative shift.
- defense_protection_led: "You're at risk of losing X — protect it." Customer base under attack, churn risk.
- customer_evolution_led: "Your customers are changing — change with them." Buyer persona / motion / product mix shift.
- growth_acceleration_led: "Grow faster by doing X." New segments, geographies, channels.

★☆☆ RARE / SITUATION-SPECIFIC:
- sequencing_led: "Many right moves; here's the order that unlocks the next ones."
- pivot_refocus_led: "You're spread thin — concentrate on Y." Strategic narrowing.
"""


_THESIS_A_INSTRUCTIONS = """\
Generate THREE storyline candidates for this pitch. A storyline is the organizing \
principle the entire deck argues from — not just a thesis line but the full strategic \
frame.

# THESIS QUALITY BAR (read this carefully before generating)

A STRONG thesis is SPECIFIC, GROUNDED, and ACTIONABLE:
- SPECIFIC: contains a number, named entity, or concrete artifact ("1,100 logos", "Workday", \
"the IPO window", "$180M Series E").
- GROUNDED: ties to a real business mechanic that affects enterprise value (NRR, CAC payback, \
revenue per rep, cohort retention, cost-to-serve, working-capital cycle, etc.).
- ACTIONABLE: implies what to do, not just what is ("compound the base", "displace the incumbent", \
"build the cohort track record"). A verb prescribing action is usually present.

A WEAK thesis is one or more of:
- GENERIC ("Embed AI to drive transformation") — applies to any company.
- META ("Win the displacement narrative", "Reframe the AI story") — about narrative, not action.
- JARGON-LED ("Leverage agentic AI for ecosystem orchestration") — buzzwords doing the work.
- REMOVABLE: if you can swap the company name and the thesis still makes sense, it's too generic.

# STRONG VS WEAK — examples across sectors

STRONG theses share three traits: a specific anchor, a real value mechanic, and a \
prescribed action. The examples below span different sectors deliberately — match the \
FORM (anchor + mechanic + action), not the content. Do NOT default to a SaaS/IPO framing \
unless the target company's actual situation calls for it.

- SaaS: "1,100 logos, no disclosed NRR — compound the base before the raise."
    → anchor: logo count. mechanic: NRR. action: compound.
- Lending / NBFC: "12% of the book rolls to 90+ DPD — move collections upstream of write-off."
    → anchor: DPD bucket. mechanic: net recovery rate. action: intervene earlier.
- Retail / consumer: "40% of revenue sits in 8% of customers — defend the high-LTV cohort first."
    → anchor: revenue concentration. mechanic: cohort LTV. action: prioritise defence.

WEAK: "Run their GTM on the AI they sell — and win the displacement narrative."
  → Clever-sounding but no specific anchor, no mechanic, "narrative" is meta. Marketing line, \
not a partner thesis.

# HARD CONSTRAINTS

1. The three candidates MUST come from THREE DIFFERENT archetypes (no two from the same).
2. AT LEAST ONE candidate must be from the ★★★ tier (numbers_led, competitive_position_led, \
risk_urgency_led, operating_leverage_led, capability_asymmetry_led, or quality_discipline_led).
3. If the EXCLUDED ARCHETYPES block above contains any archetypes, do NOT use any of them.
4. Candidates must be GENUINELY DISTINCT — different organizing principles, not three phrasings \
of the same idea. Same evidence base; the LENS differs.
5. All candidates speak to the audience persona per the framing note above.

# FAILURE MODES TO AVOID

- Two candidates that share the same underlying claim with different wording.
- Candidates that survive removing the company name (i.e., not company-specific).
- Marketing language: "unlock", "elevate", "future-ready", "transformation", "synergy", \
"leverage" as a verb, "ecosystem".
- Generic AI-strategy theses ("Embed AI across operations").
- More than 20 words in thesis_line.

# FIELD DEFINITIONS

For each candidate provide:

- archetype: one of the 12 taxonomy keys (snake_case).

- lens_label: short ALL-CAPS label naming the lens (≤30 chars, e.g., "CAPITAL-ALLOCATION LENS", \
"DISPLACEMENT LENS", "IPO-WINDOW LENS"). One line; no period.

- thesis_line: the single sentence the deck argues (≤20 words). Apply the quality bar above.

- why_for_persona: ONE sentence explaining why a [persona role] specifically — given their KPIs \
and accountability — would lean into this thesis. Must be NON-INTERCHANGEABLE: if you could swap \
"CFO" for "CEO" without changing the sentence's meaning, it's too generic. Reference the \
persona's actual concerns (CFO: cash, margin, leverage, IPO readiness; CEO: growth, \
narrative, board, valuation; COO: cost-to-serve, throughput, quality, ops risk; CIO: tech debt, \
integration burden, security).

- storyline_beats: an array of EXACTLY 4 strings, one per section, ordered:
    [Section 1 framing, Section 2 opportunity framing, Section 3 deep-dive thrust, Section 4 close]
  Each beat is a CLAIM that section will make — not a description of what the section is about.
  STRONG beat: "Cross-sell intelligence converts 8–18% of the installed base into ARR uplift over 12 months."
  WEAK beat: "Section 3 covers the cross-sell deep-dive." (description, not claim)
  WEAK beat: "Discuss the AI-driven retention model." (table-of-contents entry, not argument)
  Each beat is 1 sentence, ≤25 words.

- quantified_anchor: optional one-line estimated outcome (e.g., "≈$15–30m NRR uplift over 18 months"). \
Empty string if no defensible quantification is available from the dossier.

# OUTPUT

Respond with EXACTLY ONE JSON object, no prose, no markdown fences:
{
  "candidates": [
    {
      "archetype": "string (one of 12 taxonomy keys)",
      "lens_label": "string (ALL-CAPS, ≤30 chars)",
      "thesis_line": "string (≤20 words)",
      "why_for_persona": "string (one sentence, persona-specific)",
      "storyline_beats": ["beat 1", "beat 2", "beat 3", "beat 4"],
      "quantified_anchor": "string or empty"
    }
  ],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "Title / thesis", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}"""


def thesis_v1_step_a(dossier: dict, form_params: dict,
                     excluded_archetypes: list | None = None) -> str:
    """Storyline-candidates prompt. Accepts excluded_archetypes for regeneration paths
    so the user-rejected options aren't re-shown."""
    excluded = excluded_archetypes or []
    # NOTE: the research dossier is supplied as a cached system block (see
    # stage_2_inference._system_blocks); it is intentionally NOT embedded here.
    blocks = dict(
        target=_form_summary(form_params),
        audience_framing=_audience_framing(form_params),
        archetype_taxonomy=_ARCHETYPE_TAXONOMY,
    )
    # Only include the EXCLUDED ARCHETYPES block when there's something to exclude —
    # avoids an empty `[]` block confusing the model on the first pass.
    if excluded:
        blocks["excluded_archetypes"] = excluded
    header = _ctx_header(
        "Thesis-v1 step A — generate 3 storyline candidates",
        **blocks,
    )
    return header + "\n\n" + _THESIS_A_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 2: Thesis-v1 step B (Opus) — elaborate user-chosen storyline
# --------------------------------------------------------------------------------- #
_THESIS_B_INSTRUCTIONS = """\
The CHOSEN STORYLINE block above is the user's selection from three candidates. Your job \
is to elaborate it into the full deck thesis_v1 structure — NOT to pick again, not to \
pivot, not to introduce a different organizing principle.

# How to stay faithful to the chosen storyline (non-negotiable)

- chosen_archetype: copy verbatim from chosen_candidate.archetype.
- thesis_line: copy chosen_candidate.thesis_line. Light edits allowed only for grammar, \
cadence, or terminology consistency with the dossier — no semantic change, no archetype shift.
- subtitle: derive from the thesis_line and the chosen lens. ≤15 words, declarative, \
audience-shaped. This sits below the company name on the title slide as italic display text.
- storyline arguments: each section's "argument" field is derived DIRECTLY from the \
corresponding chosen_candidate.storyline_beats[i] entry:
    - storyline_beats[0] → Section 1 argument ("Company context")
    - storyline_beats[1] → Section 2 argument ("Opportunity buckets")
    - storyline_beats[2] → Section 3 argument ("Deep-dives")
    - storyline_beats[3] → Section 4 argument ("Engagement / Next Steps")
  Same claim, more deck-ready phrasing. 1–2 sentences each. Do NOT invent new claims or \
substitute a different framing.

# Quality bar for arguments

Each section argument is a CLAIM that section will establish — what proposition the slides \
must defend. Not a description of what's "covered". 
STRONG: "Section 2 must show that five concrete opportunities exist inside Customer Intelligence, \
each tied to a public-market mechanic the IPO comps price on."
WEAK: "Section 2 will describe the opportunity buckets." (description, not claim)

# Deck structure (informational only — does not change the four sections)

- Section 1 — Company context (1–2 slides)
- Section 2 — Opportunity buckets (1 slide per selected intelligence pillar, max 2)
- Section 3 — Deep-dives (4–6 slides, one opportunity per slide)
- Section 4 — Engagement (one slide — Next Steps)

# Output

Respond with EXACTLY ONE JSON object, no prose, no markdown fences:
{
  "chosen_archetype": "string — copied verbatim from chosen_candidate.archetype",
  "thesis_line": "string (≤20 words) — copied or lightly polished",
  "subtitle": "string (≤15 words) — italic title-slide subtitle, audience-shaped",
  "storyline": [
    {"section": "Section 1 — Company context", "argument": "string — derived from beats[0]"},
    {"section": "Section 2 — Opportunity buckets", "argument": "string — derived from beats[1]"},
    {"section": "Section 3 — Deep-dives", "argument": "string — derived from beats[2]"},
    {"section": "Section 4 — Engagement", "argument": "string — derived from beats[3]"}
  ],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "string", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}"""


def thesis_v1_step_b(dossier: dict, form_params: dict, chosen_candidate: dict) -> str:
    """Elaborate a user-chosen storyline into the full thesis_v1 schema.

    Unlike the old step_b that selected from candidates, this takes the locked
    candidate and only fills in the surrounding scaffolding (subtitle, per-section
    arguments).
    """
    header = _ctx_header(
        "Thesis-v1 step B — elaborate chosen storyline",
        target=_form_summary(form_params),
        audience_framing=_audience_framing(form_params),
        chosen_storyline=chosen_candidate,
    )
    return header + "\n\n" + _THESIS_B_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 3: Section 1 — Company context (Sonnet)
# --------------------------------------------------------------------------------- #
_SECTION_1_INSTRUCTIONS = """\
Draft Section 1 — Company context (1–2 slides). Use selective public facts that set up \
Sections 2–4 and the thesis. Prose-leaning, not a fact dump — choose the few facts that \
matter to the argument. Cite the dossier source ids you used.

Respond with EXACTLY ONE JSON object, no prose, no fences:
{
  "slides": [
    {"title": "string", "body": "string — prose, MBB register, 60–120 words"}
  ],
  "sources_used": [{"title": "string", "url": "string", "accessed": "string"}],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "Section 1", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}
Populate `sources_used` from the dossier `source_index` entries you actually relied on \
(copy their title/url/accessed)."""


def section_1(dossier: dict, form_params: dict, thesis: dict) -> str:
    header = _ctx_header(
        "Section 1 — Company context",
        target=_form_summary(form_params),
        thesis=thesis,
    )
    return header + "\n\n" + _SECTION_1_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 4: Section 2 — Opportunity buckets (Sonnet)
# --------------------------------------------------------------------------------- #
_SECTION_2_INSTRUCTIONS = """\
Draft Section 2 — Opportunity buckets. Produce ONE slide per selected intelligence pillar \
(maximum 2 slides). For each pillar slide:
- A bucket thesis: one sentence on where the value sits for this company under that pillar.
- 3–5 opportunity headlines SELECTED FROM THE CAPABILITY CATALOGUE (in the system context). \
Select by matching each opportunity's `use_when` signal against the dossier. Only pick \
opportunities whose `form_pillar` matches the selected pillar (Customer Intelligence = \
customer_intelligence; Financial Intelligence = financial_intelligence). Use the catalogue \
opportunity `id` and `name` verbatim; write a company-specific one-line headline for each.

Respond with EXACTLY ONE JSON object, no prose, no fences:
{
  "slides": [
    {
      "pillar": "string — the selected pillar name",
      "bucket_thesis": "string — one sentence",
      "opportunities": [
        {"id": "catalogue id", "name": "catalogue name", "headline": "string — company-specific, <=15 words", "why_relevant": "string — the use_when signal you matched in the dossier"}
      ]
    }
  ],
  "sources_used": [{"title": "string", "url": "string", "accessed": "string"}],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "Section 2", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}"""


def section_2(dossier: dict, form_params: dict, thesis: dict) -> str:
    header = _ctx_header(
        "Section 2 — Opportunity buckets",
        target=_form_summary(form_params),
        selected_pillars=form_params.get("intelligence_pillars", []),
        thesis=thesis,
    )
    return header + "\n\n" + _SECTION_2_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 5: Section 3 — Deep-dives (Sonnet)
# --------------------------------------------------------------------------------- #
_SECTION_3_INSTRUCTIONS = """\
Draft Section 3 — Deep-dives. Pick the 4–6 strongest opportunities from Section 2 \
(one opportunity per slide). For each slide cover, in this order:
- area: the intelligence pillar this opportunity sits under (e.g. "Customer Intelligence" or "Financial Intelligence"). Rendered as the slide eyebrow.
- title: a DESCRIPTIVE opportunity name, not the pillar (e.g. "Demand-matched rostering", "Proactive churn interception").
- subtitle: ONE descriptive line (<=16 words) saying what the opportunity is / does.
- context_points: 2-3 short, declarative statements — the company-specific problem / current state (THE CONTEXT). Tie each to dossier evidence.
- opportunity_levers: EXACTLY 3 short statements — the AI opportunity itself (THE OPPORTUNITY): what gets built and what it does. Capability-led ("A session-level demand forecast from booking data..."), never "Aistra will...".
- roi: an ROI range, never a point estimate.

ROI rules (strict):
- Always a range: Low / Mid / High. Never a single point estimate.
- At least THREE named drivers (e.g. volume x improvement % x unit value, or equivalent).
- Compute the math (the arithmetic that produces Low/Mid/High) and put it in the `roi.math` \
field for the audit trail. The DECK SLIDE shows the Low\u2013High range and the named driver \
baselines in the Indicative Impact ribbon — the arithmetic itself is never rendered on the \
slide, only carried in the To-validate audit.
- Default to the catalogue opportunity's `typical_roi_metrics`; if one does not fit, deviate \
and flag it.
- Each driver becomes an entry in `assumptions` (its value + basis).
- For EACH deep-dive, emit ONE `validation_flags` entry whose `claim` is the ROI range, \
`basis` is the inline math plus the driver values it rests on, and `suggested_action` is the \
concrete step for the client team to validate those drivers. This is what surfaces the \
calculation in the "To validate" tab. Additional per-driver flags are fine for material \
uncertainties, but the per-deep-dive ROI flag is required.

Respond with EXACTLY ONE JSON object, no prose, no fences:
{
  "slides": [
    {
      "opportunity_id": "catalogue id",
      "area": "Customer Intelligence | Financial Intelligence",
      "title": "string — descriptive opportunity name",
      "subtitle": "string — <=16 words, what the opportunity is",
      "context_points": ["string", "string", "string"],
      "opportunity_levers": ["string", "string", "string"],
      "roi": {
        "metric": "string — the ROI metric used",
        "drivers": [{"name": "string", "value": "string — the assumed value/range", "basis": "string"}],
        "math": "string — the arithmetic shown inline, e.g. '4.2M txns x 1.5–3.0% uplift x $3.10 = $0.2M–0.4M'",
        "low": "string", "mid": "string", "high": "string"
      }
    }
  ],
  "sources_used": [{"title": "string", "url": "string", "accessed": "string"}],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "Section 3", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}"""


def section_3(dossier: dict, form_params: dict, thesis: dict, section_2_output: dict) -> str:
    header = _ctx_header(
        "Section 3 — Deep-dives",
        target=_form_summary(form_params),
        thesis=thesis,
        section_2_buckets=section_2_output,
    )
    return header + "\n\n" + _SECTION_3_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 6: Section 4 — Engagement (Sonnet)
# --------------------------------------------------------------------------------- #
_SECTION_4_INSTRUCTIONS = """\
Draft Section 4 — Engagement. Produce ONE slide: a concrete, company-specific Next Steps \
close that tells the audience what to do after this meeting. Do NOT produce a generic \
engagement-model overview, a workshop scope slide, or a commercial-close slide — those are \
handled elsewhere or omitted by design. Section 4 is a single action-oriented close.

# Quality bar for Next Steps content

Actions must be SPECIFIC to this company. Avoid generic phrases like "identify a sponsor" \
or "confirm data access." Name the role (e.g., "Identify the head of RevOps and the CFO \
counterpart for Discovery scoping"), name the data system or KPI ("Confirm access to the \
NetSuite cohort tables and the Salesforce renewal pipeline view"), or name the decision \
("Decide whether the prototype targets US enterprise or APAC mid-market first"). \
Reference the company's actual situation, KPIs, or named systems from the dossier where \
possible.

# Structure

The slide is a two-column layout: "WITH {COMPANY}" on the left, "WITH AISTRA" on the right. \
The deck renderer expects this shape verbatim.

- with_company: EXACTLY 3 concrete, company-specific actions the client should take.
- with_aistra: EXACTLY 2 concrete commitments from Aistra (e.g., circulate Discovery scope \
within 5 business days, share Prototype design for the lead opportunity at kickoff).

Each item is 1 sentence. No bullet symbols inside the strings.

# Output

Respond with EXACTLY ONE JSON object, no prose, no markdown fences:
{
  "slides": [
    {
      "slide_type": "next_steps",
      "title": "Next steps",
      "subtitle": "string — italic subtitle, ≤15 words, e.g. 'Three with {company}, two with Aistra.'",
      "with_company": ["action 1", "action 2", "action 3"],
      "with_aistra": ["action 1", "action 2"]
    }
  ],
  "sources_used": [{"title": "string", "url": "string", "accessed": "string"}],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": [{"claim": "string", "slide_ref": "Section 4", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low"}]
}"""


def section_4(dossier: dict, form_params: dict, thesis: dict) -> str:
    header = _ctx_header(
        "Section 4 — Engagement",
        target=_form_summary(form_params),
        audience_role=form_params.get("audience_role", ""),
        thesis=thesis,
    )
    return header + "\n\n" + _SECTION_4_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 2 — Prompt 7: Thesis-v2 + synthesis (Opus)
# --------------------------------------------------------------------------------- #
_THESIS_V2_INSTRUCTIONS = """\
You have now drafted all four sections. Do two things:
1. Refine the thesis in light of what the sections actually argue. Keep it <=15 words. \
Update the title-slide subtitle to match.
2. Prioritise EVERY validation flag raised across all sections into a single ranked list, \
highest priority first. Rank by impact x uncertainty (a high-impact, high-uncertainty claim \
ranks above a low-impact or low-uncertainty one). Do not drop any flag; merge exact duplicates.

Respond with EXACTLY ONE JSON object, no prose, no fences:
{
  "refined_thesis_line": "string (<=15 words)",
  "title_subtitle": "string",
  "rationale": "string — what changed and why, vs the v1 thesis",
  "prioritized_validation_flags": [
    {"claim": "string", "slide_ref": "string", "basis": "string", "suggested_action": "string", "impact": "high|medium|low", "uncertainty": "high|medium|low", "priority_rank": 1}
  ],
  "assumptions": [{"assumption": "string", "basis": "string"}],
  "validation_flags": []
}
`priority_rank` is 1-based and strictly increasing. Put the full merged list in \
`prioritized_validation_flags`; leave the top-level `validation_flags` empty (this prompt \
produces no new section-level flags)."""


def thesis_v2_synthesis(
    dossier: dict,
    form_params: dict,
    thesis_v1: dict,
    sections: dict,
    all_validation_flags: list,
) -> str:
    header = _ctx_header(
        "Thesis-v2 + synthesis",
        target=_form_summary(form_params),
        audience_framing=_audience_framing(form_params),
        thesis_v1=thesis_v1,
        drafted_sections=sections,
        all_validation_flags_raised=all_validation_flags,
    )
    return header + "\n\n" + _THESIS_V2_INSTRUCTIONS


# --------------------------------------------------------------------------------- #
# Stage 3 — Deck creation (Opus + code execution + pptx skill)
# --------------------------------------------------------------------------------- #
DECK_SYSTEM_PROMPT = """\
You are a senior presentation designer for Aistra, an applied-AI consultancy. You \
assemble client-ready pitch decks using python-pptx and the pptx skill inside the \
code execution sandbox. You produce a single valid .pptx that opens cleanly in \
Microsoft PowerPoint (16:9).

# Design philosophy
The reference decks uploaded into the sandbox ARE the visual language you must match. \
They are not optional inspiration — they are the standard. Mimic their layout \
discipline, whitespace, typography hierarchy, and use of brand accents. Aistra's \
decks read like an MBB partner wrote them: prose-leaning, restrained, confident.

# Theme — strict white only
Every slide uses a white background. There are NO dark-theme slides anywhere in the \
deck — not the title slide, not the section dividers, not any panels within content \
slides. Brand colours (primary_purple, accent_cyan, accent_pink, accent_teal) are \
used as ACCENTS only: thin separator bars, small label text, section numbers, italic \
subtitles. Never as block fills behind body content. Never as dark side-panels.

# Copy discipline
You use the supplied slide content verbatim. You are doing design and layout, not \
rewriting copy. If a body block is too long to fit cleanly on one slide, TIGHTEN it \
(drop redundant clauses, shorten driver labels, cut a sentence) rather than overflow — \
but never invent new content.

No AI hype, no marketing language on the slides."""

_DECK_INSTRUCTIONS = """\
Build a client-ready Aistra pitch deck as a single PowerPoint file, then save it.

# Working files (in the sandbox working directory)
Run `ls` to see them. They were uploaded for you:
- Reference decks (.pptx): these define the visual language. Spend 2–3 tool calls \
inspecting them carefully — colours used, typography hierarchy, layout grids, how the \
brand accents are deployed, slide title style, footer style. Read these BEFORE writing \
slide-assembly code. The BRAND JSON above gives you the constants (colours, fonts, \
sizes); the reference decks show you the COMPOSITION. Do NOT copy their text content.
- Logo (.png), if present: place it top-left on every slide per the brand `logo_position`.

# Theme — strict white only (non-negotiable)
- Every slide has a white background. No exceptions — not the title slide, not the \
section dividers, not any sub-panel within a content slide.
- Brand colours are used as ACCENTS only: thin separator bars (2–4pt), small accent \
text, section numbers in colour, italic subtitle lines, page-number rules. Brand \
colours are NEVER used as block fills behind body text or as dark side-panels.
- ROI blocks and side-cards on content slides are LIGHT cards — white or near-white \
fill (#FAFAFA), thin border (1pt) or a 3pt left purple accent bar, dark text.

# Internal IDs — strictly never on slides (non-negotiable)
The deck spec includes catalogue ids (e.g. ci_rev_05, fi_03) and internal tags (e.g. \
"bespoke") on opportunities. These are INTERNAL ORGANISING METADATA. They must NEVER \
appear on any slide — no pills, no labels, no badges, nowhere. The audience reading \
this deck must never see them. Use them only inside your code to map content; do not \
render them as visible elements.

# Slide titles
- Two-line maximum. If a title doesn't fit, shorten it — don't let it spill into a \
third line.
- Never hyphenate mid-word at a line break. If a natural wrap creates an awkward \
break (e.g. "fin-tech"), rewrite the title to break at a word boundary.
- The title occupies the full width of the slide's content area. No badges, pills, \
labels, or numbers in the title row.

# Text fitting — non-negotiable
- Every text box is sized to its content with at least 0.2" vertical clearance from \
the next element below it.
- If body content would overflow its container, TIGHTEN the content (shorten phrases, \
drop a redundant sentence) rather than overflow. Never let body text run into a \
subsequent section header. Never let any content extend into the footer zone.
- Side panels (ROI, OUTPUTS, PARTICIPANTS) must show ALL their content fully. If a \
panel has 5 items, the panel must be sized for 5 items — or the items must be \
tightened to fit the panel.

# Footer (uniform across all slides)
- Reserve the bottom 0.45" of every slide as a footer zone. No body content extends \
into it.
- Footer left: "Aistra × {Company} · {Section name}".
- Footer right: page number in the form "{N} / {Total}".
- Use the SAME "{N} / {Total}" format on EVERY slide — title slide, section dividers, \
and content slides. No mixed numbering formats.

# Brand application (authoritative)
- Use the exact hex colours, fonts, and typography sizes from the BRAND JSON above.
- Slide size: 16:9 using `slide_width_inches` × `slide_height_inches`.
- Display font (e.g. Georgia from BRAND JSON) for slide titles and large numerical \
accents. Body font (e.g. Calibri) elsewhere.
- Italics for subtitles, problem statements, and basis-of-claim lines — never for \
body content.
- Whitespace is part of the design. Aim for roughly 30–40% of every slide to be \
whitespace. Crowded slides are a design failure.

# Deck structure (build slides in THIS order, from the DECK SPEC above)

1. **Title slide** — WHITE background. Company name in large display font (72–96pt). \
Italic thesis subtitle below in body font. Thin purple separator bar between title \
and subtitle. Small "CONFIDENTIAL · {COMPANY} × AISTRA" line at top. Audience role \
and date at bottom-left. Logo top-left.

2. **Section dividers** (one per section) — WHITE background. Large section number \
("01", "02", "03", "04") in purple display font on the left. Section name in display \
font to the right of the number. Single transitional sentence below in italic body \
font. No dark treatment.

3. **Section 1 — Company context** — one slide per entry in `sections.section_1.slides`. \
Title at top, prose body (60–120 words) below. Optional small metrics card on the right \
(light fill, thin border, key numbers in display font). Plenty of whitespace.

4. **Section 2 — Opportunity buckets** — one slide per entry in `sections.section_2.slides`. \
Title (pillar name) at top. Bucket thesis in italic subtitle below the title. Then a list \
of opportunities, each as a horizontal row: opportunity NAME (display font) on the left, \
company-specific headline (body font) on the right, thin separator line between rows. \
NO opportunity-id pills. NO bespoke tags. NO internal codes anywhere on the slide.

5. **Section 3 — Deep-dives** — one slide per entry in `sections.section_3.slides`. \
Two-column layout:
  - Left column (~60% width): four small-caps labels in purple — WHAT / WHY THIS \
COMPANY / HOW AISTRA DELIVERS / EXPECTED SIGNALS — each followed by tight prose \
(1–2 sentences per label). No long paragraphs.
  - Right column (~40% width): ROI card with white fill, 3pt left purple accent bar, \
thin 1pt border. The ROI card MUST show: metric label, Low / Mid / High range, named \
drivers with values, and the inline math arithmetic — all fully visible within the \
card boundary.
  - If content doesn't fit: tighten the LEFT column first (cut WHAT/WHY/HOW/SIGNALS \
to 1 sentence each). NEVER sacrifice the ROI math — the math is the credibility of \
this slide.

6. **Section 4 — Engagement** — one slide per entry in `sections.section_4.slides`. \
The three-stage engagement slide is a three-card layout: Discovery / Prototype / \
Managed Service. Each is a WHITE card with a thin coloured top bar (purple, cyan, pink \
respectively) — not a dark card. The next-steps slide is a two-column layout: \
"WITH {COMPANY}" on the left, "WITH AISTRA" on the right — both columns are LIGHT \
cards, no dark side. The discovery-workshop slide (if present) shows numbered \
questions on the left and participants + outputs as LIGHT side-cards on the right \
(never dark panels). Include a commercial-close slide only if the spec's section_4 \
`include_commercial_close` is true.

Aim for 12–16 slides total. Quality over quantity. Better fewer slides that breathe \
than crammed slides that overflow.

# Output (required)
Save the finished deck to EXACTLY this absolute path: /tmp/aistra_deck.pptx — a single \
file, overwriting if it exists. After saving, re-open it with python-pptx to confirm \
it loads, then print this exact line: SAVED /tmp/aistra_deck.pptx
If you hit an error, fix it and re-run until /tmp/aistra_deck.pptx is saved and \
verified. Leave the file in place at /tmp/aistra_deck.pptx; do not delete or move it."""


def deck_creation_prompt(
    deck_spec: dict,
    brand: dict,
    reference_filenames: list[str],
    logo_filename: str | None,
) -> str:
    header = _ctx_header(
        "Deck creation",
        brand_json=brand,
        reference_deck_files=reference_filenames or ["(none uploaded)"],
        logo_file=logo_filename or "(none uploaded)",
        deck_spec=deck_spec,
    )
    return header + "\n\n" + _DECK_INSTRUCTIONS


# ================================================================================= #
# Per-slide rendering prompt (used by stage_3 in local-execution mode)
# ================================================================================= #
SLIDE_RENDER_SYSTEM_PROMPT = """\
You are a python-pptx engineer. You receive content for ONE slide and a brand spec, \
and you output python-pptx code that adds exactly one slide to the existing \
Presentation object `prs` (already in scope).

You output ONLY a single ```python ... ``` code block. No preamble, no explanation, \
no trailing commentary. Just the code.

# Strict rules (non-negotiable)
- WHITE backgrounds only. No dark theme anywhere. Force white explicitly:
  slide.background.fill.solid(); slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
- Brand colours are accents only — thin separator bars, section numbers, small accent
  labels, italic subtitles. NEVER as block fills behind body content. NEVER as dark side-panels.
- Internal IDs (catalogue ids like ci_rev_*, fi_*, internal tags like "bespoke") must
  NEVER appear on the slide. They are organising metadata only.
- Slide titles: 2-line maximum. No mid-word hyphenation at line breaks. No badges, pills,
  or labels in the title row — the title gets the full content width.
- Title and separator: if the title might wrap to 2 lines, place the separator bar
  at least 0.3" BELOW where the title text-box ends, not at a fixed Y. Compute the
  title height from font size × line count (≈ 1.3 × font_pt for line spacing) and
  position the separator below that. NEVER let the title text overlap the purple bar.
- All text must fit within its container with at least 0.2" vertical clearance from the
  next element. If content does not fit, SHORTEN it — do not overflow.
- Reserve the bottom 0.45" of every slide as a footer zone. Do NOT place any content
  there; the footer is added separately after all slides are built. CONCRETELY: with
  slide height 7.5", do not place any text-box or shape whose bottom edge extends below
  Inches(7.05). Build content within the top 7.05" only. If body content would extend
  past 7.05", SHORTEN it.
- ROI / side cards are LIGHT cards: white or near-white fill (#FAFAFA), optional 1pt
  border in #E5E7EB, optional 3pt left purple accent bar. NEVER dark cards.

# Variables available in scope
prs, brand, slide_spec, Presentation, Inches, Pt, Emu, RGBColor, PP_ALIGN, MSO_ANCHOR, MSO_SHAPE

# Boilerplate to start every slide
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
slide.background.fill.solid()
slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
"""


_LAYOUT_GUIDANCE = {
    "opportunity_bucket": """\
Section 2 — Opportunity bucket slide.

Layout:
- Title at top: pillar name (e.g. "Customer Intelligence" / "Financial Intelligence"),
  display font ~30pt, ink colour (#111827).
- Thin 3pt purple separator bar below the title (~0.6" wide).
- Italic bucket_thesis below the bar, body font ~14pt, muted colour (#64748B).
- Then a list of opportunities. Each opportunity is one row, ~85% of slide width.
  Each row has THREE columns:
    1. Number indicator on the far left — display font 14pt purple, two digits
       ("01", "02", "03", "04", "05"). Provides visual rhythm down the slide.
       Width ~0.5".
    2. Opportunity name in display font ~16pt ink colour, ~3.5" wide.
    3. Company-specific headline in body font ~12pt ink colour, ~7" wide.
  Thin 0.5pt rule line in #E5E7EB between rows.
- 3–5 opportunities expected. Distribute them evenly down the slide. The first row
  starts at ~2.3" from the top, and the LAST row's bottom must stay above ~6.6" — the
  footer zone (below ~6.7") is OFF LIMITS. If five rows would crowd the footer, tighten
  the inter-row spacing rather than letting the last row run into it.
- DO NOT show any opportunity_id, sub_pillar code, or tag like "bespoke".""",
}


def slide_render_prompt(slide_spec: dict, brand: dict, section_key: str, slide_type: str) -> str:
    """Build the per-slide user prompt for Sonnet's code generation."""
    # Only opportunity_bucket reaches Sonnet now (company_context, deep_dive and
    # next_steps are all templated). Fall back to opportunity_bucket defensively.
    layout = _LAYOUT_GUIDANCE.get(slide_type, _LAYOUT_GUIDANCE["opportunity_bucket"])
    return (
        f"# Render ONE slide and add it to `prs`\n\n"
        f"## Section\n{section_key}\n\n"
        f"## Slide type\n{slide_type}\n\n"
        f"## Layout guidance\n{layout}\n\n"
        f"## Slide content (JSON)\n```json\n"
        f"{json.dumps(slide_spec, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## Brand (JSON)\n```json\n"
        f"{json.dumps(brand, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Write ONE python-pptx code block that adds exactly one slide to `prs`. "
        f"Follow every rule in the system prompt. Output the code block only — no prose."
    )


# =================================================================================== #
# v2 pipeline — hypothesis-led prompts (research scaffold -> fact pack -> hypotheses ->
# code selection -> storyline). These coexist with the legacy thesis/section prompts.
# =================================================================================== #
def _scaffold_summary(scaffold: dict) -> str:
    return (
        f"Company: {scaffold.get('company','')}\n"
        f"HQ / domicile: {scaffold.get('hq','') or 'unknown'}\n"
        f"Ticker + exchange: {scaffold.get('ticker','') or 'private / not given'}\n"
        f"Key countries: {scaffold.get('key_countries','') or 'not specified'}\n"
        f"Audience role: {scaffold.get('audience_role','')}\n"
        f"Scope choice: {scaffold.get('scope_choice','')}\n"
        f"Lead pillars (deck emphasis): {', '.join(scaffold.get('in_scope_pillars', []))}\n"
        f"Lead buckets (deck emphasis): {', '.join(scaffold.get('in_scope_buckets', []))}\n"
        f"Research breadth: full capability catalogue + industry discovery (all pillars)\n"
        f"Include Talent Gap assessment: {scaffold.get('include_talent_gap', False)}\n"
        f"Client brief / stated priorities: {scaffold.get('additional_notes','') or 'none given'}"
    )


# --------------------------------------------------------------------------------- #
# Step 1 — Fact pack
# --------------------------------------------------------------------------------- #
_FACTPACK_SCHEMA = """\
Return EXACTLY ONE JSON object with these keys:
{
  "company": "string",
  "generated_at": "ISO-8601 string",
  "facts": [
    {"id": "F001", "bucket": "<any pillar's bucket id, or 'unmapped'>",
     "statement": "one-sentence fact, specific and quantified where possible",
     "value": "the headline number/metric if any, else ''",
     "source": {"title": "string", "url": "string", "kind": "web|upload", "confidence": "high|med|low"}}
  ],
  "company_profile": {
    "what_they_do": "string",
    "scale_markers": ["string", ...],
    "financials": {"revenue": "", "margin": "", "...": ""}
  },
  "industry_opportunities": [
    {"id": "G1", "pillar": "<one of revenue|customer|operational|financial|workforce>",
     "label": "short opportunity name", "rationale": "why it fits this industry/company",
     "source": {"title": "", "url": "", "kind": "web", "confidence": "high|med|low"}}
  ],
  "delivery_capability_facts": [
    {"id": "D1", "statement": "fact about current team/roles/hiring/tech-stack", "source": {...}}
  ],
  "unmapped_facts": [],
  "assumptions": [],
  "validation_flags": []
}
RULES:
- Every fact carries a source. Never fabricate a number; if undisclosed, omit or mark an assumption.
- `bucket` is the catalogue bucket the fact best evidences (any pillar's bucket, or 'unmapped').
- `industry_opportunities`: ALWAYS populate. Discover sector/company-specific AI opportunities
  (e.g. fare-rule reissue automation for travel, predictive maintenance for manufacturing), each
  tagged to its best-fit pillar, framed for THIS company rather than as generic AI features.
- `delivery_capability_facts`: ONLY when Talent Gap is on; gather current team shape, AI/data roles
  present, hiring signals, leadership scan, tech-stack disclosures. Omit (empty) otherwise.
- Tailor your web searches to THIS company, industry, and audience role. Research across the FULL
  capability catalogue and discover industry opportunities; weight depth toward the lead pillars,
  but do not exclude strong cross-pillar plays the company's economics clearly warrant."""


def research_prompt_v2(scaffold: dict, today: str) -> str:
    header = _ctx_header(
        f"RESEARCH BRIEF — {scaffold.get('company','')} (as of {today})",
        scaffold=_scaffold_summary(scaffold),
        full_catalogue=scaffold.get("bucket_catalogue", {}),
    )
    return (
        header
        + "\n\nYou are running an outside-in research pass to build a FACT PACK for an "
        "Aistra AI-opportunity pitch. Use web search (and any attached canonical materials) to "
        "gather specific, sourced facts about this company across the full capability catalogue "
        "above, and discover the industry-specific AI opportunities its economics warrant. Weight "
        "depth toward the lead pillars, but reason from the company's actual P&L and operations — "
        "not a generic AI checklist. If the client brief names specific focus areas, gather the "
        "facts needed to reframe each one as a cost, revenue, margin, or working-capital lever. "
        "Reason from public data; never fabricate.\n\n"
        + _FACTPACK_SCHEMA
    )


# --------------------------------------------------------------------------------- #
# Step 2 — Hypotheses
# --------------------------------------------------------------------------------- #
_HYPOTHESES_SCHEMA = """\
Return EXACTLY ONE JSON object:
{
  "hypotheses": [
    {
      "id": "H1",
      "claim": "business-grain claim about THIS company (not a tactic, not a platitude)",
      "supporting_facts": ["F001", "F004"],
      "opportunity_ref": "<catalogue bucket id OR a generated id like G1>",
      "opportunity_source": "catalogue|generated",
      "pillar": "revenue|customer|operational|financial|workforce",
      "candidate_archetypes": ["<one or more of the 12 archetype keys>"],
      "evidence_strength": 1,
      "ai_opportunity": {"title": "short opportunity name", "one_line": "what the AI play does"},
      "indicative_impact": {"low": "$X", "high": "$Y",
        "drivers": [{"name": "Base", "value": "..."}, {"name": "Gain", "value": "..."}]}
    }
  ],
  "assumptions": [],
  "validation_flags": []
}
RULES:
- A hypothesis is BUSINESS-GRAIN: "split-shift rostering inflates cost-to-serve", NOT
  "use model X" and NOT "AI helps". It must tie to a value mechanic and imply an action.
- NAME THE P&L LEVER each hypothesis moves — cost-to-serve, revenue leakage, margin mix,
  working capital, distribution cost, etc. — and reason from the company's actual unit
  economics (the numbers in the fact pack), not from a generic AI capability list.
- PREFER THE DOMAIN-SPECIFIC PLAY over the generic-AI default. Where a generic option exists
  (dynamic pricing, fraud scoring, a chatbot), only lead with it if the economics demand it;
  otherwise reach for the operations-deep play and name the manual, error-prone, headcount-heavy
  task it removes (e.g. fare-rule reissue/refund computation, not "automation").
- ANSWER THE BRIEF: if the client brief names focus areas, each must be covered by at least one
  hypothesis, reframed as a P&L lever — so the brief is answered completely, not sidestepped.
- `supporting_facts` must reference fact ids from the fact pack. No hypothesis without facts.
- `opportunity_ref`: a catalogue bucket id when grounded in the catalogue; a generated id
  (from industry_opportunities) when from the generated path. Set `opportunity_source` to match.
- `candidate_archetypes`: which of the 12 storyline angles this claim can support (a claim may
  serve several). Use the archetype keys exactly.
- `evidence_strength` 1-5: how well the supporting_facts back the claim (5 = hard disclosed
  numbers; 1 = thin inference).
- `indicative_impact`: a quantified range with named drivers and the arithmetic implied. If a
  play is genuinely unquantifiable from public data, raise a validation_flag — do NOT write
  "qualitative" as the value.
- Produce 8-15 hypotheses, weighted to the lead pillars but allowing strong cross-pillar plays.
  Quality over quantity; each must be specific to this company and sourced."""


def hypotheses_prompt(fact_pack: dict, scaffold: dict) -> str:
    header = _ctx_header(
        f"HYPOTHESIS FORMULATION — {scaffold.get('company','')}",
        scaffold=_scaffold_summary(scaffold),
        fact_pack=fact_pack,
        archetype_taxonomy=_ARCHETYPE_TAXONOMY,
    )
    return (
        header
        + "\n\nFrom the FACT PACK above, derive a set of grounded, business-grain hypotheses "
        "for an Aistra AI-opportunity pitch. Reason from the company's actual unit economics: "
        "where does cost leak, where does revenue leak, where does margin compress. Each "
        "hypothesis links facts to a single AI opportunity, names the P&L lever it moves, tags "
        "the archetype angles it can support, and rates its evidence. If the client brief names "
        "focus areas, make sure each is answered. These hypotheses are the single source of "
        "truth the deck is built from.\n\n"
        + _HYPOTHESES_SCHEMA
    )


# --------------------------------------------------------------------------------- #
# Step 4 — Storyline (post code-selection)
# --------------------------------------------------------------------------------- #
_STORYLINE_SCHEMA = """\
Return EXACTLY ONE JSON object carrying every field below (do not omit keys; use empty
arrays/strings where a part genuinely has no content):
{
  "meta": {"thesis_line": "specific, grounded, actionable one-liner",
           "lens_label": "ALL-CAPS lens label, <=30 chars",
           "subtitle": "<=15 words, declarative"},
  "strategic_context": {
    "layout": "cards|compare",
    "title_parts": [["dark part ", "ink"], ["purple emphasis.", "purple"]],
    "subtitle": "one line",
    "cards": [{"tag": "short label", "metric": "~80%", "desc": "what it is",
               "body": "1-2 sentences", "fact_refs": ["F001"]}],
    "left":  {"header": "string", "items": ["...", "..."]},
    "right": {"header": "string", "items": ["...", "..."]},
    "sources": "Sources: ..."
  },
  "opportunity_areas": {
    "title_parts": [["The opportunities we'd ", "ink"], ["prioritise.", "purple"]],
    "subtitle": "one line",
    "opportunities": [{"pillar": "...", "title": "...", "body": "one line", "hypothesis_id": "H1"}]
  },
  "deep_dives": [
    {"hypothesis_id": "H1", "area": "<Pillar> Intelligence", "title": "opportunity name",
     "subtitle": "italic one-liner",
     "context_points": ["2-5 grounded points from supporting facts"],
     "opportunity_levers": ["3-4 levers — what the AI play actually does"],
     "roi": {"low": "$X", "high": "$Y", "drivers": [{"name": "short lever label (<=22 chars)", "value": "baseline detail (not shown on strip)"}]}}
  ],
  "workforce_readiness": {
    "columns": ["very short label, <=2 words / <=14 chars (match deep_dive order)"],
    "heatmap": [["low|mod|high", ...], ...],
    "recommendations": [{"role": "FDC|FDE|Data Engineer|FDO (+ short specialisation)", "contribution": "one line",
                         "helps": ["opportunity short labels"]}],
    "method_note": "Inferred from public hiring signals, leadership scan, and tech-stack disclosures. Confirmed via Aistra Sprints."
  },
  "assumptions": [],
  "validation_flags": []
}
RULES:
- Write from the CHOSEN ARCHETYPE and its CORE HYPOTHESES. Stay on the chosen lens.
- `thesis_line` is ONE committed argument the whole deck hangs off — not a list of risks. Where
  the company's economics support it, give it a "not X, but Y" spine (e.g. "the next margin point
  comes not from more discounting but from intelligence in the operations layer"). Strategic
  context must set up and evidence THAT thesis, not enumerate unconnected problems.
- COUNT CONSISTENCY: if any title or subtitle names a number ("four risks", "three plays"), the
  cards/items rendered must match it exactly. Never claim a count the slide does not show.
- `strategic_context.layout`: use "cards" for <=3 punchy metrics; "compare" for a
  two-column "data they have vs what tooling ignores" contrast. Fill the matching keys only.
- `opportunity_areas.opportunities`: ONE per core hypothesis, in the given order. `pillar` must
  be the lowercase pillar id (revenue|customer|operational|financial|workforce). `body` is ONE
  line — keep it short enough to render on a card without wrapping past two lines.
- `deep_dives`: ONE per core hypothesis, same order; context_points from that hypothesis's
  supporting facts; roi from its indicative_impact. `roi` is a quantified range with named
  drivers — never the string "qualitative"; if a play is genuinely unquantifiable, give a
  directional range and raise a validation_flag instead. `roi.low` and `roi.high` are CLEAN
  figures only — currency + number + unit (e.g. "₹1.6 Cr", "₹75 cr", "$4m"). Do NOT append
  descriptors like "annual NIM" or "funding cost saved / yr" to the figure; the strip header
  already says INDICATIVE IMPACT · ANNUAL, and a long figure renders small. Put any such
  qualifier in the deep-dive subtitle. The deep-dive impact strip displays
  ONLY each driver's `name`, so make every `name` a short lever label — at most 3 words / ~22
  characters (e.g. "Cost-of-funds reduction", "Approval-rate lift"). Keep the quantification in
  `value` (used in the audit trail, not shown on the strip).
- `workforce_readiness`: include ONLY if the Talent Gap toggle is on. `columns` are the
  prioritised opportunities in deep_dive order, each as a VERY SHORT label — at most two words
  and ~14 characters, with no single word longer than 12 characters (abbreviate: "Encyclopaedia
  Layer" -> "Knowledge Layer", "Clinical Decision Support" -> "Clinical CDS"). These sit in
  narrow heatmap columns and must not wrap mid-word. The four delivery roles are
  fixed (FDC, FDE, Data Engineer, FDO) and supplied by the renderer — provide the heatmap
  rows in THAT role order. Cells are dependency intensity: low|mod|high. Up to 3 recommendations.
  Each recommendation's `role` MUST be named in the Aistra delivery taxonomy — it begins with one
  of FDC, FDE, Data Engineer, or FDO, optionally followed by a short specialisation in
  parentheses (e.g. "FDE (Model Risk & Governance)", "Data Engineer (AA / GST / bureau)",
  "FDC (AI/Data strategy)"). Do not invent external job titles like "Head of AI".
- title_parts colour tags are exactly "ink" or "purple". Keep titles declarative and specific."""


def storyline_prompt(selection: dict, fact_pack: dict, scaffold: dict,
                     core_hypotheses: list, adjacent_hypotheses: list) -> str:
    header = _ctx_header(
        f"STORYLINE — {scaffold.get('company','')}",
        scaffold=_scaffold_summary(scaffold),
        chosen_archetype=selection.get("chosen_archetype"),
        selection_rationale=selection.get("rationale"),
        core_hypotheses=core_hypotheses,
        adjacent_hypotheses=adjacent_hypotheses,
        fact_pack=fact_pack,
    )
    talent = ("The Talent Gap toggle is ON — include the workforce_readiness object."
              if scaffold.get("include_talent_gap")
              else "The Talent Gap toggle is OFF — set workforce_readiness to null.")
    return (
        header
        + "\n\nWrite the deck storyline from the chosen archetype and its core hypotheses. "
        "Commit to one thesis and make every section earn it. Where the client brief named focus "
        "areas, the storyline must visibly answer each, reframed as a P&L lever. Every field maps "
        "directly onto a deck slide, so populate them all precisely and in the house voice (MBB, "
        "declarative, numbers where defensible, no hype). "
        + talent + "\n\n"
        + _STORYLINE_SCHEMA
    )
