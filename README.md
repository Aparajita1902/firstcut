# Aistra Pack Generator

A single-shot pitch deck generator. Pick a project type, fill in a short form about a
target company, and receive:

- A PowerPoint deck (~12–15 slides) identifying AI opportunities for that company
- An inline **audit trail**: sources cited, assumptions made, and claims that require
  validation — the credibility move that differentiates this from a generic deck-maker

The approach is outside-in: research uses publicly available data plus any materials you
upload. The quality bar is a *strong first draft* (~60% of a finished, strategist-grade
deck) — the strategist edits the last mile.

V1 ships **one** active project type (Aistra opportunity pitch). Five others are visible
but disabled on the landing page for future releases.

---

## Project status

This repo is being built in three phases:

- **Phase 1 (current):** Project scaffolding + Streamlit front-end with all three pages
  working end-to-end. The **Generate** button returns mock data from a stubbed
  `orchestrator.generate_deck()` — no API calls yet.
- **Phase 2:** Wire the real back-end (Stages 1–4: research, inference, deck creation,
  outputs) per `SPEC.md`.
- **Phase 3:** Hardening, polish, and the remaining items.

See `SPEC.md` for the full source-of-truth specification.

---

## Tech stack

- Python 3.14
- Streamlit (front-end)
- Anthropic Python SDK (`anthropic`)
- `python-dotenv` for environment variables

---

## Setup

From the project root (`aistra-deck-prototype/`):

```powershell
# 1. Create a Python 3.14 virtual environment
py -3.14 -m venv .venv

# 2. Activate it (PowerShell)
.\.venv\Scripts\Activate.ps1
#    If activation is blocked by execution policy, run this once for your user:
#    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env from the template and add your key
copy .env.example .env
#    then edit .env and set ANTHROPIC_API_KEY=<your key>
```

> The Anthropic API key is **not** required for Phase 1 — the orchestrator returns mock
> data. It is needed once the real back-end is wired in Phase 2.

---

## Running

```powershell
streamlit run streamlit_app.py
```

Streamlit will open the app in your browser (default http://localhost:8501).

### Walkthrough

1. **Page 1 — Project type:** six cards in a 3×2 grid. Only *Aistra opportunity pitch*
   is active; the other five show a "Coming soon" badge. Click the active card.
2. **Page 2 — Input form:** enter the target company details, pick a target audience
   role and at least one intelligence pillar, optionally upload PDFs/DOCX, then click
   **Generate**.
3. **Output page:** the generated deck's metadata, a download button, and three audit
   tabs — **Sources**, **Assumptions**, **To validate**.

---

## Project structure

```
aistra-deck-prototype/
├── .env.example            # template for environment variables
├── .env                    # your local secrets (gitignored)
├── .gitignore
├── README.md
├── requirements.txt
├── SPEC.md                 # full build specification (source of truth)
├── streamlit_app.py        # 3-page Streamlit front-end
├── orchestrator.py         # generate_deck() — stubbed in Phase 1
├── data/
│   ├── aistra_capability_catalogue.json   (provided)
│   └── brand.json                          (provided)
└── outputs/                # generated decks (created on first run, gitignored)
```

The back-end stage modules (`stage_1_research.py` … `stage_4_outputs.py`, `prompts.py`)
described in `SPEC.md` are added in Phase 2.

---

## V1 limitations

- 1 active project type (5 disabled with "Coming soon")
- No deck preview (download only)
- No regenerate / tweak-and-rerun
- No persistence between sessions
- No login / user accounts
- No save / load of past runs
- Validation list is non-interactive (numbered list only)
- Geographic scope: India, US, UK, Australia, UAE, KSA, Sri Lanka, Singapore
  (web-search dependent)
