"""First Cut — Streamlit front-end (a tool by Aistra).

Flow, driven by ``st.session_state.page``:
    "select" -> Choose: pack type (Corporate Strategy [soon] / AI Strategy)
    "form"   -> Brief: target company + audience role + scope + Talent-gap toggle
    "output" -> Output: deck download + audit-trail tabs

The v2 pipeline runs straight through (no manual storyline pick) via ``orchestrator``:
    generate_deck_v2(...)  — code scaffold -> Stage 1 fact pack -> Stage 2 hypotheses
                             -> code selection -> Stage 2 storyline -> Stage 3 assembly
                             -> Stage 4 audit.

Scope is a single choice: Customer Service / Finance & Accounting / All AI opportunities
("All" includes CS + F&A and turns on the generated industry path). The Talent Gap toggle
adds the Delivery-capability (role-gap) slide. The backend resolves scope -> pillars in
``research_scaffold.build_scaffold``.
"""

from __future__ import annotations

import base64
import functools
import os

import streamlit as st
from dotenv import load_dotenv

import orchestrator

load_dotenv()

st.set_page_config(page_title="First Cut", page_icon="📐", layout="wide")


# --------------------------------------------------------------------------------- #
# Brand constants
# --------------------------------------------------------------------------------- #
PURPLE = "#6C48F2"
CYAN = "#00D9FF"

PACK_TYPES = [
    {
        "key": "corporate_strategy",
        "eyebrow": "Outside-in",
        "name": "Corporate Strategy",
        "description": "A 3–5 year outside-in strategy pack — market shape, where-to-play, and the moves that follow.",
        "shape": "~50 slides",
        "active": False,
    },
    {
        "key": "ai_strategy",
        "eyebrow": "Opportunity assessment",
        "name": "AI Strategy",
        "description": "Where AI moves the P&L for a target company — opportunity buckets, deep-dives, and an engagement path.",
        "shape": "~15 slides",
        "active": True,
    },
]

AUDIENCE_ROLES = ["CEO", "CFO", "COO", "CIO", "Other"]

# Scope is a single choice. "All AI opportunities" includes Customer Service + Finance &
# Accounting and turns on the generated (industry-specific) research path. Talent is a
# separate toggle (adds the Delivery-capability slide), not a scope.
SCOPE_OPTIONS = ["Customer Service", "Finance & Accounting", "All AI opportunities"]

STEPS = ["Choose", "Brief", "Output"]


# --------------------------------------------------------------------------------- #
# Styling — dark Aistra shell, First Cut logo, step rail (best-effort; the base dark
# theme + purple primary should also be set in .streamlit/config.toml)
# --------------------------------------------------------------------------------- #
def inject_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@600;700;800&display=swap');
@font-face{font-family:"FCPoppins";src:url(data:font/ttf;base64,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) format("truetype");font-weight:600;font-style:normal;font-display:block}
:root{
  --fc-purple:#6C48F2; --fc-purple-br:#8B6CFF; --fc-cyan:#00D9FF;
  --fc-muted:#A1A4B0; --fc-dim:#6B7186; --fc-border:#252B3D; --fc-card:#141927;
}
.block-container{padding-top:3.4rem; max-width:1120px;}
header[data-testid="stHeader"]{background:transparent;}
.fc-bar img.aistra{height:30px; display:block;}

/* Brand bar */
.fc-bar{display:flex; align-items:center; justify-content:space-between;
  padding:2px 0 14px; border-bottom:1px solid var(--fc-border); margin-bottom:8px;}
.fc-logo{font-family:'FCPoppins','Poppins',sans-serif; font-weight:600; font-size:22px;
  letter-spacing:-.01em; line-height:1; color:#fff;}
.fc-logo .b{display:inline-block; width:.085em; height:.70em; background:var(--fc-cyan);
  border-radius:1px; transform:translateY(.06em) rotate(11deg); margin:0 .15em;}
.fc-logo .c{color:var(--fc-purple-br);}
.fc-byline{font-family:'FCPoppins','Poppins',sans-serif; font-weight:600; font-size:8.5px;
  letter-spacing:.2em; text-transform:uppercase; color:var(--fc-dim); margin-top:4px;}
.fc-who{color:var(--fc-muted); font-size:12.5px; font-weight:600;}
.fc-who .dot{display:inline-block; width:7px; height:7px; border-radius:50%;
  background:var(--fc-cyan); margin-right:7px; vertical-align:middle;
  box-shadow:0 0 10px var(--fc-cyan);}

/* Step rail */
.fc-steps{display:flex; gap:14px; align-items:center; justify-content:center;
  margin:18px 0 26px; flex-wrap:wrap;}
.fc-step{display:flex; align-items:center; gap:8px; color:var(--fc-dim); font-size:12px;
  font-weight:700; letter-spacing:.04em; text-transform:uppercase;
  font-family:'Poppins',sans-serif;}
.fc-step .n{width:22px; height:22px; border-radius:50%; display:inline-grid;
  place-items:center; font-size:11px; border:1px solid var(--fc-border);}
.fc-step.on{color:#fff;}
.fc-step.on .n{background:var(--fc-purple); border-color:var(--fc-purple); color:#fff;}
.fc-bar2{width:26px; height:1px; background:var(--fc-border);}

/* Text accents */
.fc-eyebrow{font-family:'Poppins',sans-serif; font-weight:800; font-size:11px;
  letter-spacing:.26em; text-transform:uppercase; color:var(--fc-purple-br); margin-bottom:2px;}
.fc-kicker{font-family:'Poppins',sans-serif; font-weight:800; font-size:11px;
  letter-spacing:.14em; text-transform:uppercase; color:var(--fc-dim);}
.fc-tag{display:inline-block; font-family:'Poppins',sans-serif; font-weight:800;
  font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--fc-purple-br);
  background:rgba(108,72,242,.15); border:1px solid var(--fc-border); padding:4px 11px;
  border-radius:999px;}
.fc-anchor-k{font-family:'Poppins',sans-serif; font-size:10px; font-weight:700;
  letter-spacing:.1em; text-transform:uppercase; color:var(--fc-dim);}
.fc-anchor-v{color:var(--fc-cyan); font-weight:800; font-size:14px;}
.fc-chip{display:inline-block; color:var(--fc-muted); font-size:12.5px; font-weight:600;
  background:rgba(0,217,255,.06); border:1px solid rgba(0,217,255,.22); border-radius:999px;
  padding:6px 13px;}
.fc-chip b{color:var(--fc-cyan); font-weight:700;}
.fc-beat-l{font-family:'Poppins',sans-serif; font-weight:800; font-size:9.5px;
  letter-spacing:.08em; text-transform:uppercase; color:var(--fc-dim);}
.fc-shape{color:var(--fc-dim); font-size:12.5px; font-weight:600;}

/* Card polish */
[data-testid="stVerticalBlockBorderWrapper"]{background:var(--fc-card);
  border:1px solid var(--fc-border) !important; border-radius:14px;}

/* Choose-page pack cards — pure-CSS flex row, guaranteed equal height */
.fc-cards{display:flex; gap:1rem; margin-bottom:12px;}
.fc-card{flex:1 1 0; min-width:0; background:var(--fc-card); border:1px solid var(--fc-border);
  border-radius:14px; padding:26px 26px 22px; display:flex; flex-direction:column;}
.fc-card.fc-soon{opacity:.6;}
.fc-cardtitle{font-family:Georgia,'Times New Roman',serif; font-weight:400; font-size:26px;
  color:#fff; margin:12px 0 10px; line-height:1.12;}
.fc-carddesc{color:var(--fc-muted); font-size:14.5px; line-height:1.6; margin:0 0 16px; flex:1;}
</style>
""",
        unsafe_allow_html=True,
    )


@functools.lru_cache(maxsize=1)
def _aistra_logo_uri() -> str:
    """Read data/logo.png and return a base64 data URI (empty string if missing)."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logo.png")
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    except Exception:
        return ""


def _fc(size_px: int | None = None) -> str:
    """First Cut wordmark as inline HTML — white 'first' + cyan slash + purple 'cut',
    always lowercase. Pass size_px to scale it to the surrounding text. Use everywhere
    the product/deliverable name appears in rendered HTML so the mark is identical."""
    style = f' style="font-size:{size_px}px"' if size_px else ""
    return f'<span class="fc-logo"{style}>first<span class="b"></span><span class="c">cut</span></span>'


def render_brandbar() -> None:
    uri = _aistra_logo_uri()
    right = (
        f'<img class="aistra" src="{uri}" alt="Aistra">'
        if uri
        else '<div class="fc-who"><span class="dot"></span>Aistra · Managed AI Services</div>'
    )
    st.markdown(
        f"""
<div class="fc-bar">
  <div>
    <div class="fc-logo">first<span class="b"></span><span class="c">cut</span></div>
    <div class="fc-byline">A Tool by Aistra</div>
  </div>
  {right}
</div>
""",
        unsafe_allow_html=True,
    )


def render_steps(active: str) -> None:
    parts = []
    for i, label in enumerate(STEPS, start=1):
        on = " on" if label == active else ""
        parts.append(
            f'<div class="fc-step{on}"><span class="n">{i}</span> {label}</div>'
        )
        if i < len(STEPS):
            parts.append('<div class="fc-bar2"></div>')
    st.markdown(f'<div class="fc-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def _init_state() -> None:
    st.session_state.setdefault("page", "select")
    st.session_state.setdefault("pack_type", "ai_strategy")
    st.session_state.setdefault("output_package", None)
    st.session_state.setdefault("candidate_state", None)
    st.session_state.setdefault("excluded_archetypes", [])
    st.session_state.setdefault("uploaded_files", None)


def _goto(page: str) -> None:
    st.session_state.page = page


# --------------------------------------------------------------------------------- #
# Page 1 — Choose pack type
# --------------------------------------------------------------------------------- #
def render_select_page() -> None:
    render_brandbar()
    render_steps("Choose")

    st.markdown(
        f"""
<div style="text-align:center; margin:14px 0 30px;">
  <div class="fc-eyebrow">Strategy packs</div>
  <h1 style="font-weight:400; font-size:46px; margin:6px 0 10px;">Generate a {_fc(46)}.</h1>
  <p style="color:var(--fc-muted); max-width:620px; margin:0 auto; font-size:16px; line-height:1.6;">
    Pick a pack type. {_fc(16)} researches the target and returns a strategist-grade draft —
    with sources, assumptions, and the ROI math shown. You edit the last&nbsp;mile.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    cards = '<div class="fc-cards">'
    for pack in PACK_TYPES:
        soon = "" if pack["active"] else " fc-soon"
        cards += (
            f'<div class="fc-card{soon}">'
            f'<div class="fc-kicker">{pack["eyebrow"]}</div>'
            f'<div class="fc-cardtitle">{pack["name"]}</div>'
            f'<p class="fc-carddesc">{pack["description"]}</p>'
            f'<div class="fc-shape">{pack["shape"]}</div>'
            f"</div>"
        )
    cards += "</div>"
    st.markdown(cards, unsafe_allow_html=True)

    # Buttons in a matching 2-col row directly beneath, so they align under the cards.
    b1, b2 = st.columns(2, gap="medium")
    for col, pack in zip((b1, b2), PACK_TYPES):
        with col:
            if pack["active"]:
                st.button(
                    "Start brief →",
                    key=f"pick_{pack['key']}",
                    type="primary",
                    use_container_width=True,
                    on_click=_pick_pack,
                    args=(pack["key"],),
                )
            else:
                st.button("Coming soon", key=f"pick_{pack['key']}", disabled=True, use_container_width=True)


def _pick_pack(key: str) -> None:
    st.session_state.pack_type = key
    _goto("form")


# --------------------------------------------------------------------------------- #
# Page 2 — Brief
# --------------------------------------------------------------------------------- #
def _role_input() -> tuple[str, str]:
    """Audience picker. When 'Other' is selected, a free-text box opens inline, beside
    the control, instead of as a separate labelled field below. Returns (role, other)."""
    col_a, col_b = st.columns([3, 2])
    with col_a:
        if hasattr(st, "segmented_control"):
            role = st.segmented_control(
                "Target audience", AUDIENCE_ROLES, default="CEO", key="role_sc"
            ) or ""
        else:
            role = st.selectbox("Target audience", AUDIENCE_ROLES, index=0, key="role_sb")
    other = ""
    with col_b:
        if role == "Other":
            other = st.text_input(
                "Other", placeholder="Type the role…",
                label_visibility="hidden", key="other_role_inline",
            )
    return role, other


def _sync_scope() -> None:
    """Keep the scope multiselect coherent:
    - ticking 'All AI opportunities' selects all three;
    - narrowing to a single catalogue area drops 'All'.
    Uses a stored previous selection to tell 'add All' from 'remove a sub-scope'."""
    ALL = "All AI opportunities"
    subs = {"Customer Service", "Finance & Accounting"}
    sel = set(st.session_state.get("scope_ms", []))
    prev = set(st.session_state.get("_scope_prev", []))
    added = sel - prev

    if ALL in added:
        sel = {ALL} | subs                      # selecting All implies all three
    elif ALL in sel and not subs <= sel:
        sel.discard(ALL)                        # narrowed a sub -> All no longer holds

    ordered = [s for s in SCOPE_OPTIONS if s in sel]
    st.session_state.scope_ms = ordered
    st.session_state._scope_prev = ordered


def _scope_input() -> list[str]:
    """Scope picker — multi-select across the three opportunity areas."""
    if "scope_ms" not in st.session_state:
        st.session_state.scope_ms = SCOPE_OPTIONS[:]      # default: all three
        st.session_state._scope_prev = SCOPE_OPTIONS[:]
    st.multiselect(
        "Scope", SCOPE_OPTIONS, key="scope_ms", on_change=_sync_scope,
        help="The opportunity areas to explore for this company.",
    )
    return st.session_state.scope_ms


def render_form_page() -> None:
    render_brandbar()
    render_steps("Brief")

    st.button("← Back to pack types", on_click=_goto, args=("select",))
    st.markdown('<div class="fc-eyebrow">AI Strategy · New brief</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-weight:700; font-size:1.75rem; color:#fff; line-height:1.2; '
        f'margin:.2rem 0 .4rem;">Tell {_fc(28)} about the target.</div>',
        unsafe_allow_html=True,
    )
    st.caption("Company name and HQ are required. Everything else is optional.")

    # Not wrapped in st.form so the conditional "Other role" field can react live.
    c1, c2 = st.columns(2)
    with c1:
        company_name = st.text_input("Company name *", placeholder="e.g. Their Care Pty Ltd")
        ticker = st.text_input("Ticker + exchange", help="If the company is publicly listed.")
    with c2:
        hq = st.text_input("HQ / domicile *", placeholder="e.g. Melbourne, Australia")
        key_countries = st.text_input("Key countries", help="The markets that matter most for this company.")

    st.write("")
    audience_role, other_role = _role_input()

    st.write("")
    scope_choices = _scope_input()
    include_talent_gap = st.toggle(
        "Include Talent Gap Assessment",
        value=False, key="talent_gap_toggle",
        help="Assess whether the client can staff and run the build.",
    )

    st.write("")
    uploaded_files = st.file_uploader(
        "Materials",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        help="Anything you'd hand an analyst to get up to speed — reports, prior decks, data.",
    )
    additional_notes = st.text_area(
        "Additional context",
        placeholder="Anything First Cut should weigh — a known sale process, a board mandate, a recent restructure…",
    )

    st.write("")
    st.markdown(
        f'<div style="color:var(--fc-muted); font-size:14px; line-height:1.5; margin-bottom:20px;">{_fc(14)} runs '
        f'research, forms and prioritises hypotheses, then assembles the deck. A typical run takes '
        f'about 20\u201330 minutes and costs about $8.</div>',
        unsafe_allow_html=True,
    )
    if st.button("Generate first cut →", type="primary"):
        _handle_submit(
            _build_form_params(
                company_name, hq, ticker, key_countries,
                audience_role, other_role, scope_choices, include_talent_gap, additional_notes,
            ),
            uploaded_files,
        )


def _build_form_params(company_name, hq, ticker, key_countries,
                       audience_role, other_role, scope_choices, include_talent_gap,
                       additional_notes) -> dict:
    """Assemble form_params for the v2 (hypothesis-led) pipeline."""
    choices = list(scope_choices or [])
    if "All AI opportunities" in choices or not choices:
        scope_label = "All AI opportunities"
    else:
        scope_label = " + ".join(choices)
    return {
        "company_name": (company_name or "").strip(),
        "hq": (hq or "").strip(),
        "ticker": (ticker or "").strip(),
        "key_countries": (key_countries or "").strip(),
        "audience_role": audience_role or "",
        "other_role": (other_role or "").strip(),
        "scope_choices": choices,
        "scope_choice": scope_label,
        "include_talent_gap": bool(include_talent_gap),
        "pack_type": st.session_state.get("pack_type", "ai_strategy"),
        "additional_notes": (additional_notes or "").strip(),
    }


def _validate(form_params: dict) -> list[str]:
    errors = []
    if not form_params["company_name"]:
        errors.append("Company name is required.")
    if not form_params["hq"]:
        errors.append("HQ / domicile is required.")
    if not form_params["audience_role"]:
        errors.append("Select a target audience role.")
    if form_params["audience_role"] == "Other" and not form_params["other_role"]:
        errors.append("Please name the 'Other' audience role.")
    # Scope is intentionally optional — no error if empty.
    return errors


def _handle_submit(form_params: dict, uploaded_files: list) -> None:
    errors = _validate(form_params)
    if errors:
        for err in errors:
            st.error(err)
        return

    with st.status("Researching, forming hypotheses, and assembling the deck…", expanded=True) as status:
        def _progress(message: str) -> None:
            st.write(message)

        try:
            package = orchestrator.generate_deck_v2(
                form_params, uploaded_files, progress=_progress,
            )
        except Exception as exc:
            status.update(label="Generation failed.", state="error", expanded=True)
            st.error(f"Generation failed: {exc}")
            return
        status.update(label="Deck ready.", state="complete", expanded=False)

    st.session_state.output_package = package
    st.session_state.company_name = form_params["company_name"]
    st.session_state.uploaded_files = uploaded_files
    _goto("output")
    st.rerun()


# --------------------------------------------------------------------------------- #
# Page 3 — Storyline
# --------------------------------------------------------------------------------- #
def render_storyline_page() -> None:
    render_brandbar()
    render_steps("Storyline")

    state = st.session_state.get("candidate_state")
    if not state or not state.get("candidates"):
        st.warning("No storyline candidates available. Start over from the brief.")
        st.button("← Back to brief", on_click=_goto, args=("form",))
        return

    company_name = st.session_state.get("company_name", "the target company")
    candidates = [c for c in state["candidates"] if isinstance(c, dict) and c.get("thesis_line")]
    if not candidates:
        st.error("The model returned no usable storyline candidates. Try regenerating.")
        st.button("← Back to brief", on_click=_goto, args=("form",))
        return

    st.button("← Back to brief", on_click=_goto, args=("form",))
    st.markdown(f'<div class="fc-eyebrow">AI Strategy · {company_name}</div>', unsafe_allow_html=True)
    st.markdown("## Pick the storyline.")
    st.caption(
        "Three angles — each a different thesis the deck will argue, with its own four-beat arc. "
        "Pick one to build, or regenerate for fresh archetypes."
    )

    n_assume = len(state.get("candidate_assumptions") or [])
    n_flags = len(state.get("candidate_flags") or [])
    if n_assume or n_flags:
        st.markdown(
            f'<span class="fc-chip">Behind these drafts · <b>{n_assume} assumptions</b> · '
            f'<b>{n_flags} to validate</b></span>',
            unsafe_allow_html=True,
        )
    st.write("")

    for i, cand in enumerate(candidates):
        _render_candidate_card(i, cand)
        st.write("")

    # Regenerate
    excluded = st.session_state.get("excluded_archetypes") or []
    regen_disabled = len(set(excluded)) >= 12
    rc1, rc2 = st.columns([1, 3])
    with rc1:
        if st.button(
            "↻ Regenerate angles",
            disabled=regen_disabled,
            use_container_width=True,
            help=("Three fresh archetypes not yet shown." if not regen_disabled
                  else "All 12 archetypes have been shown."),
        ):
            _handle_regenerate()
    with rc2:
        remaining = max(0, 12 - len(set(excluded)))
        st.caption(f"Fresh archetypes from the 12-angle taxonomy · {remaining} remaining · adds ~$0.40.")


_BEAT_LABELS = ["Context", "Buckets", "Deep-dive", "Close"]


def _render_candidate_card(index: int, cand: dict) -> None:
    lens = (cand.get("lens_label") or "").strip()
    thesis = (cand.get("thesis_line") or "").strip()
    why = (cand.get("why_for_persona") or "").strip()
    anchor = (cand.get("quantified_anchor") or "").strip()
    archetype = (cand.get("archetype") or "").strip()

    raw_beats = cand.get("storyline_beats")
    if isinstance(raw_beats, str):
        beats = [raw_beats]
    elif isinstance(raw_beats, list):
        beats = [str(b).strip() for b in raw_beats if str(b).strip()]
    else:
        beats = []

    with st.container(border=True):
        top_l, top_r = st.columns([3, 1])
        with top_l:
            if lens:
                st.markdown(f'<span class="fc-tag">{lens}</span>', unsafe_allow_html=True)
        with top_r:
            if anchor:
                st.markdown(
                    f'<div style="text-align:right;"><div class="fc-anchor-k">Anchor</div>'
                    f'<div class="fc-anchor-v">{anchor}</div></div>',
                    unsafe_allow_html=True,
                )
        st.markdown(f"### {thesis}" if thesis else "### _(missing thesis line)_")
        if why:
            st.markdown(f"_{why}_")

        if beats:
            st.write("")
            bcols = st.columns(len(beats[:4]))
            for j, (bcol, beat) in enumerate(zip(bcols, beats[:4])):
                with bcol:
                    label = _BEAT_LABELS[j] if j < len(_BEAT_LABELS) else f"Beat {j+1}"
                    st.markdown(f'<div class="fc-beat-l">{j+1} · {label}</div>', unsafe_allow_html=True)
                    st.caption(beat)

        st.write("")
        if st.button(
            "Build this storyline →",
            key=f"choose_{index}_{archetype or 'unknown'}",
            type="primary",
            disabled=not thesis,
        ):
            _handle_choose(cand)


def _handle_regenerate() -> None:
    state = st.session_state.get("candidate_state")
    if not state:
        return
    excluded = list(set(st.session_state.get("excluded_archetypes") or []))

    with st.status("Drafting fresh storyline candidates…", expanded=True) as status:
        def _progress(message: str) -> None:
            st.write(message)

        try:
            new_state = orchestrator.generate_candidates(
                state["form_params"],
                st.session_state.get("uploaded_files"),
                excluded_archetypes=excluded,
                progress=_progress,
                prior_state=state,
            )
        except Exception as exc:
            status.update(label="Regeneration failed.", state="error", expanded=True)
            st.error(f"Regeneration failed: {exc}")
            return
        status.update(label="Fresh candidates ready.", state="complete", expanded=False)

    st.session_state.candidate_state = new_state
    for c in new_state["candidates"]:
        a = c.get("archetype")
        if a and a not in excluded:
            excluded.append(a)
    st.session_state.excluded_archetypes = excluded
    st.rerun()


def _handle_choose(chosen_candidate: dict) -> None:
    state = st.session_state.get("candidate_state")
    if not state:
        return

    with st.status("Building the deck around your chosen storyline…", expanded=True) as status:
        def _progress(message: str) -> None:
            st.write(message)

        try:
            output_package = orchestrator.generate_deck_from_storyline(
                state, chosen_candidate, progress=_progress,
            )
        except Exception as exc:
            status.update(label="Deck assembly failed.", state="error", expanded=True)
            st.error(f"Deck assembly failed: {exc}")
            return
        status.update(label="Deck ready.", state="complete", expanded=False)

    st.session_state.output_package = output_package
    _goto("output")
    st.rerun()


# --------------------------------------------------------------------------------- #
# Page 4 — Output
# --------------------------------------------------------------------------------- #
def render_output_page() -> None:
    render_brandbar()
    render_steps("Output")

    pkg = st.session_state.get("output_package")
    if not pkg:
        st.warning("No deck has been generated yet.")
        st.button("← Start over", on_click=_goto, args=("select",))
        return

    company_name = st.session_state.get("company_name", "the target company")
    st.button("← New brief", on_click=_goto, args=("form",))
    st.markdown(f'<div class="fc-eyebrow">AI Strategy · {company_name}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-weight:700; font-size:1.75rem; color:#fff; line-height:1.2; '
        f'margin:.2rem 0 .4rem;">Your {_fc(28)} is ready.</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Generated {pkg['generated_at']} · {pkg['duration_sec']:.0f}s")

    with st.container(border=True):
        st.markdown(f"#### 📊 {pkg['deck_filename']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Slides", pkg["slide_count"])
        c2.metric("File size", f"{pkg['file_size_kb']} KB")
        usage = pkg.get("usage_summary") or {}
        c3.metric("Cost", f"${usage.get('total_cost_usd', 0):.2f}")

        deck_path = pkg.get("deck_path")
        if deck_path and os.path.exists(deck_path):
            with open(deck_path, "rb") as fh:
                deck_bytes = fh.read()
            st.download_button(
                "⬇ Download deck",
                data=deck_bytes,
                file_name=pkg["deck_filename"],
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                type="primary",
            )
        else:
            st.button("⬇ Download deck", disabled=True)
            st.caption("Deck file unavailable.")

    # Usage detail
    if usage:
        total = usage.get("total_cost_usd", 0)
        with st.expander(f"Usage & cost · ${total:.2f} this run", expanded=False):
            c1, c2 = st.columns(2)
            c1.metric("Total cost", f"${total:.2f}")
            c2.metric("Total API calls", usage.get("total_calls", 0))
            stages = usage.get("stages", {})
            rows = []
            for stage_key in ("stage_1", "stage_2", "stage_3"):
                s = stages.get(stage_key)
                if not s:
                    continue
                rows.append({
                    "Stage": stage_key.replace("_", " ").title(),
                    "Calls": s["calls"],
                    "Input tokens": f"{s['input_tokens']:,}",
                    "Cached tokens": f"{s['cache_read_tokens']:,}",
                    "Output tokens": f"{s['output_tokens']:,}",
                    "Cost (USD)": f"${s['cost_usd']:.2f}",
                })
            if rows:
                st.markdown("**Per-stage breakdown**")
                st.dataframe(rows, use_container_width=True, hide_index=True)

    st.write("")
    tab_sources, tab_assumptions, tab_validate = st.tabs(["Sources", "Assumptions", "To validate"])
    with tab_sources:
        st.markdown(pkg["sources_markdown"])
    with tab_assumptions:
        st.markdown(pkg["assumptions_markdown"])
    with tab_validate:
        st.markdown(pkg["validation_markdown"])

    st.write("")
    st.button("← Generate another", on_click=_goto, args=("select",))


# --------------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------------- #
def main() -> None:
    _init_state()
    inject_css()
    page = st.session_state.page
    if page == "form":
        render_form_page()
    elif page == "storyline":
        render_storyline_page()
    elif page == "output":
        render_output_page()
    else:
        render_select_page()


if __name__ == "__main__":
    main()
