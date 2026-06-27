# Aistra v1 Prototype — Build Spec

This document is the single source of truth for the Aistra deck-generation prototype. Claude Code reads this before any build step.

---

## 1. Project Overview

A single-shot pitch deck generator. User picks a project type, fills a form about a target company, and receives:

- A PowerPoint deck (~12–15 slides) identifying AI opportunities for that company
- An inline audit trail: sources cited, assumptions made, claims requiring validation

Outside-in approach — research uses publicly available data plus any user-uploaded materials. Quality bar is "strong first draft, ~60% of a Baby Bunting / V-Line grade deck" — strategist edits the last mile.

V1 supports one active project type (Aistra opportunity pitch). Five others are visible-but-disabled on Page 1 for future releases.

---

## 2. Tech Stack

- Python 3.14
- Streamlit (front-end)
- Anthropic Python SDK (`anthropic`)
- `python-dotenv` for env vars
- Deck creation: Claude API + code execution tool + pptx skill (no direct python-pptx in our code — Claude handles assembly)

---

## 3. File Structure

```
aistra-deck-prototype/
├── .env.example
├── .env (gitignored)
├── .gitignore
├── README.md
├── requirements.txt
├── streamlit_app.py
├── orchestrator.py
├── prompts.py
├── stage_1_research.py
├── stage_2_inference.py
├── stage_3_deck_creation.py
├── stage_4_outputs.py
├── data/
│   ├── aistra_capability_catalogue.json   (provided)
│   ├── brand.json                          (provided)
│   ├── reference_decks/
│   │   ├── baby_bunting_reference.pptx    (user adds)
│   │   └── vline_reference.pptx           (user adds)
│   └── logo.png                            (user adds)
└── outputs/                                (generated decks go here)
```

---

## 4. Front-end Spec

Multi-page Streamlit app, navigation via `st.session_state`.

### Page 1 — Project Type Selection

- Title: "Aistra Pack Generator"
- Subtitle: "Pick a project type"
- Six cards in a 3×2 grid. Each card: name, one-line description, indicative output shape.
- Only **Aistra opportunity pitch** is clickable. The other five show a "Coming soon" badge and are disabled.
- Cards (in order):
  1. **Corporate strategy** — 3–5 year outside-in strategy pack (~50 slides). DISABLED.
  2. **AI & Digital strategy** — AI adoption roadmap across operations, product, business model. DISABLED.
  3. **Market entry strategy** — Sizing, mode of entry, partner landscape. DISABLED.
  4. **Competitive strategy** — Peer scan, moat assessment, response options. DISABLED.
  5. **Growth strategy** — Organic + inorganic growth levers, adjacencies. DISABLED.
  6. **Aistra opportunity pitch** — AI opportunity assessment for a target client (~15 slides). ACTIVE.

Clicking the active card → advance to Page 2 (set session_state.page = "form").

### Page 2 — Input Form (Aistra opportunity pitch)

Fields in this order:

| Field | Streamlit widget | Required | Notes |
|---|---|---|---|
| Company name | `st.text_input` | Yes | |
| HQ / domicile | `st.text_input` | Yes | |
| Ticker + exchange | `st.text_input` | No | Blank if private |
| Key countries | `st.text_input` | No | Free-form text |
| Target audience role | `st.selectbox` | Yes | Options: CIO, CFO, CEO, COO, Other |
| Other role (conditional) | `st.text_input` | If "Other" selected | Shown only if audience = "Other" |
| Intelligence pillars | `st.multiselect` | Yes (≥1) | Options: Customer Intelligence, Financial Intelligence |
| File uploads | `st.file_uploader` | No | Accept PDF + DOCX, multi-file |
| Additional context / notes | `st.text_area` | No | |

Bottom: **Generate** button. On click:
- Validate required fields
- Show a progress indicator ("Researching company..." / "Drafting sections..." / "Assembling deck...")
- Call `orchestrator.generate_deck(form_params, uploaded_files)`
- On success, advance to Output page

### Output Page

Top:
- H1: "Pitch deck for [Company Name]"
- Subtitle: "Generated [timestamp] · [duration]"

Hero card:
- Deck filename (e.g. `Aistra_Pitch_Baby_Bunting_20260612_1432.pptx`)
- Slide count, file size
- Primary **Download deck** button (`st.download_button`)

Below hero: `st.tabs(["Sources", "Assumptions", "To validate"])`

- **Sources tab**: numbered list grouped by deck section. Each item: title, URL (clickable link), accessed date.
- **Assumptions tab**: bulleted list grouped by deck section. Each item: assumption + basis.
- **To validate tab**: prioritised numbered list (single list, no grouping). Each item: claim + slide reference + basis + suggested validation action.

All lists shown inline, no truncation, no separate downloads.

---

## 5. Back-end Spec

Pipeline = 4 stages, called sequentially by `orchestrator.generate_deck()`.

### Stage 1 — Research

`stage_1_research.run(form_params, uploaded_file_ids) → research_dossier`

- Medium depth: 10–20 web searches per run
- Sources (priority order): official filings → company website → news (last 12 mo) → industry reports → broker notes → LinkedIn
- Uploaded files are canonical; web fills gaps and adds context
- Output: structured JSON with named fields:
  - `company_overview`, `financials`, `segments_and_geographies`, `strategic_moves`, `leadership`, `industry_context`, `peer_set`, `recent_news`, `pillar_focus`, `source_index`
- Every fact tagged with source URL + accessed date
- If research returns thin (private company, low-disclosure market), flag prominently in assumptions and proceed
- Pillar-scoped: dig deeper on the intelligence pillars the user selected

### Stage 2 — Inference and Storylining

`stage_2_inference.run(dossier, form_params, capability_catalogue) → deck_spec, assumptions, validation_flags`

Sequential drafting, 6 prompts:

| # | Prompt | Model | Description |
|---|---|---|---|
| 1 | Thesis-v1 step A | Opus | Generate 3 thesis candidates (company-focused, audience-shaped, picks one of 3 archetypes: recasting / diagnostic / re-positioning). 15-word max per line. |
| 2 | Thesis-v1 step B | Opus | Pick best of 3 candidates + return full output schema (storyline, assumptions, validation flags). Document why others rejected. |
| 3 | Section 1 — Company context | Sonnet | 1–2 slides. Selective public facts that set up Sections 2–4. Prose-leaning. |
| 4 | Section 2 — Opportunity buckets | Sonnet | 1 slide per intelligence pillar (2 max). Bucket thesis + 3–5 opportunity headlines selected from catalogue using `use_when` signals matched to dossier. |
| 5 | Section 3 — Deep-dives | Sonnet | 4–6 slides. One opportunity per slide. Each slide: what / why for this company / how Aistra delivers / expected signals / ROI range (Low/Mid/High, with named drivers and math shown). |
| 6 | Section 4 — Engagement | Sonnet | 2–3 slides. Discovery → Prototype → Managed Service stages. Workshop scope. Concrete next steps (include commercial close slide for CFO/CEO audiences, skip for CIO/COO). |
| 7 | Thesis-v2 + synthesis | Opus | Refine thesis from drafted sections. Update title slide subtitle and any thesis references in deck. Prioritise validation flags across all sections (impact × uncertainty). |

Audience-shaping rules for thesis (step A):
- CIO → frame around capability / architecture / delivery
- CFO → frame around P&L mechanics, capital efficiency, financial visibility
- CEO → frame around strategic positioning, market dynamic, competitive shape
- COO → frame around operating model, cost-to-serve curves, process
- Other → infer closest archetype from the role string

ROI rules for Section 3:
- Always range (Low/Mid/High), never point estimate
- Three named drivers minimum (volume × improvement % × unit cost or equivalent)
- Math shown inline on the slide, not just in assumption log
- Catalogue's `typical_roi_metric` is the default; can deviate if it doesn't fit (flagged)
- Each driver becomes an entry in the assumptions log
- Material driver uncertainties become validation flags

Inline tagging: every prompt's output JSON includes `assumptions[]` and `validation_flags[]` for that section. No separate post-hoc extraction.

### Stage 3 — Deck Creation

`stage_3_deck_creation.run(deck_spec, brand_json, reference_deck_file_ids, logo_path) → deck_pptx_path`

Single Anthropic API call:
- Model: claude-opus-4-7
- Tools: `code_execution_20250522`, `pptx` skill
- Context: the page-wise JSON spec from Stage 2 + brand.json + reference decks (uploaded via Files API) + logo

Claude writes python-pptx code, executes it in the sandbox, produces the .pptx file. The pptx file is returned as a tool result; we save it to `/outputs/`.

Filename convention: `Aistra_Pitch_{CompanyName_sanitized}_{YYYYMMDD_HHMM}.pptx`

Retry policy: on failure, retry once with a slightly tightened prompt. Second failure → raise an exception, surface to user.

### Stage 4 — Outputs Produced

`stage_4_outputs.run(deck_path, sources, assumptions, validation_flags) → output_package_dict`

Pure Python, no LLM. Renders the three audit artifacts as markdown strings ready for `st.markdown()`:
- Sources: grouped by section consumed (Section 1 sources, Section 2 sources, etc.)
- Assumptions: grouped by deck section
- Validation: prioritised single list (no grouping), highest-priority flags first

Returns:
```python
{
  "deck_path": "/outputs/Aistra_Pitch_...",
  "deck_filename": "...",
  "slide_count": int,
  "file_size_kb": int,
  "duration_sec": float,
  "sources_markdown": "...",
  "assumptions_markdown": "...",
  "validation_markdown": "..."
}
```

---

## 6. Anthropic API Integration Details

### Models
- `claude-sonnet-4-6` — Stage 1 research, Stage 2 prompts 3-6
- `claude-opus-4-7` — Stage 2 prompts 1, 2, 7 (thesis + synthesis), Stage 3 (deck creation)

### Caching strategy
Mark these as cached in every Stage 2 call:
- The shared system prompt (Aistra positioning, voice/tone, output schema rules, inline-tagging rules)
- The capability catalogue JSON (~15KB)
- The brand JSON

Cache TTL: ephemeral (default 5 min) is fine since all 6 prompts run in sequence within ~5 min.

### Tools
- `web_search_20250305` — Stage 1
- `code_execution_20250522` — Stage 3 only
- `pptx` skill — Stage 3 only

### Files API
- User-uploaded files (annual reports, prior decks): uploaded once at Stage 1 intake. File IDs reused throughout the run.
- Reference decks (`/data/reference_decks/*.pptx`): uploaded at Stage 3.

### Error handling
- API rate limits: exponential backoff, max 3 retries
- API errors: surface error to user, don't half-deliver
- Invalid output JSON from any prompt: log + retry once with stricter formatting instructions

---

## 7. Data Files

### `data/aistra_capability_catalogue.json`
Provided. 23 opportunities across Customer Intelligence (19) and Financial Intelligence (4). Schema documented in the file itself.

### `data/brand.json`
Provided. Brand colors, fonts, layout constants.

### `data/reference_decks/`
User adds 1–2 reference decks (Baby Bunting CIO discussion deck + V/Line pitch). Used by Stage 3 for visual style cues.

### `data/logo.png`
User adds Aistra logo as PNG with transparent background.

---

## 8. V1 Limitations (Document in README)

- 1 active project type (5 disabled with "Coming soon")
- No deck preview (download only)
- No regenerate / tweak-and-rerun
- No persistence between sessions
- No login / user accounts
- No save / load past runs
- Validation list non-interactive (numbered list only)
- Geographic scope: India, US, UK, Australia, UAE, KSA, Sri Lanka, Singapore (web search dependent)

---

## 9. Quality Bar

- "Strong first draft," not final-quality
- ~60% of the way to a Baby Bunting/V-Line grade deck
- Strategist edits the last 40%
- Audit trail (sources, assumptions, validations) is the credibility move that differentiates this from a generic deck-maker

---

## 10. Cost Budget (Reference)

Per deck generation, with caching:
- Stage 1 (Research): ~$0.30–0.70
- Stage 2 (6 prompts incl. 3 Opus calls): ~$0.50–1.00
- Stage 3 (Deck creation): ~$0.30–0.60
- Total: ~$1.10–2.30 per deck

---

End of spec.
