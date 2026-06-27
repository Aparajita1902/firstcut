"""Stage 4 — Outputs produced (SPEC.md Section 5).

Pure Python, no LLM. Renders the three audit artifacts (sources, assumptions, validation)
as markdown strings ready for ``st.markdown()`` and returns the output package dict.
"""

from __future__ import annotations

import os

from pptx import Presentation


def _esc(s: str | None) -> str:
    """Escape characters that Streamlit's markdown renderer treats as LaTeX delimiters.

    Streamlit (>= ~1.25) interprets ``$...$`` and ``$$...$$`` in ``st.markdown`` as
    LaTeX math, which mangles currency strings like ``US$1.5–4.0m``. Escaping every
    ``$`` as ``\\$`` keeps the rendered output verbatim. Apply to all user-content
    strings before they enter the markdown output.
    """
    return (s or "").replace("$", r"\$")


def _render_sources(sources_by_section: dict) -> str:
    if not sources_by_section:
        return "_No sources recorded for this run._"
    parts: list[str] = []
    for section, sources in sources_by_section.items():
        parts.append(f"#### {_esc(section)}")
        if not sources:
            parts.append("_No sources cited for this section._")
            continue
        for i, src in enumerate(sources, 1):
            title = _esc((src.get("title") or "Untitled source").strip())
            url = (src.get("url") or "").strip()
            accessed = _esc((src.get("accessed") or "").strip())
            link = f"[{url}]({url})" if url else "_no link_"
            line = f"{i}. {title} · {link}"
            if accessed:
                line += f" · accessed {accessed}"
            parts.append(line)
        parts.append("")  # blank line between groups
    return "\n".join(parts).strip()


def _render_assumptions(assumptions_by_section: dict) -> str:
    if not assumptions_by_section:
        return "_No assumptions recorded for this run._"
    parts: list[str] = []
    for section, assumptions in assumptions_by_section.items():
        parts.append(f"#### {_esc(section)}")
        if not assumptions:
            parts.append("_No assumptions for this section._")
            continue
        for a in assumptions:
            assumption = _esc((a.get("assumption") or "").strip())
            basis = _esc((a.get("basis") or "").strip())
            line = f"- **{assumption}**"
            if basis:
                line += f" *Basis:* {basis}"
            parts.append(line)
        parts.append("")
    return "\n".join(parts).strip()


def _render_validation(validation_flags: list) -> str:
    if not validation_flags:
        return "_No validation flags raised for this run._"
    parts: list[str] = []
    for i, flag in enumerate(validation_flags, 1):
        claim = _esc((flag.get("claim") or "").strip())
        slide_ref = _esc((flag.get("slide_ref") or "").strip())
        basis = _esc((flag.get("basis") or "").strip())
        action = _esc((flag.get("suggested_action") or "").strip())
        impact = _esc((flag.get("impact") or "").strip())
        uncertainty = _esc((flag.get("uncertainty") or "").strip())

        line = f"{i}. **{claim}**"
        if slide_ref:
            line += f" *({slide_ref})*"
        if impact or uncertainty:
            tag = " · ".join(
                t for t in (
                    f"impact: {impact}" if impact else "",
                    f"uncertainty: {uncertainty}" if uncertainty else "",
                ) if t
            )
            line += f"  \n   _{tag}_"
        if basis:
            line += f"  \n   *Basis:* {basis}"
        if action:
            line += f"  \n   *Validate:* {action}"
        parts.append(line)
    return "\n".join(parts)


def _actual_slide_count(deck_path: str, fallback: int) -> int:
    """Read the real slide count from the .pptx so the UI matches the deck.

    Stage 2's ``slide_count`` is computed from the deck spec and does not include
    section-divider slides that Stage 3 adds during deck assembly. Reading the saved
    file is authoritative; fall back to the passed-in count if the file is missing
    or unreadable.
    """
    if not deck_path or not os.path.exists(deck_path):
        return fallback
    try:
        return len(Presentation(deck_path).slides)
    except Exception:
        return fallback


def run(
    deck_path: str,
    slide_count: int,
    sources_by_section: dict,
    assumptions_by_section: dict,
    validation_flags: list,
    duration_sec: float,
    generated_at: str,
    usage_summary: dict | None = None,
) -> dict:
    deck_filename = os.path.basename(deck_path)
    file_size_kb = 0
    if deck_path and os.path.exists(deck_path):
        file_size_kb = max(1, round(os.path.getsize(deck_path) / 1024))

    return {
        "deck_path": deck_path,
        "deck_filename": deck_filename,
        "slide_count": _actual_slide_count(deck_path, slide_count),
        "file_size_kb": file_size_kb,
        "duration_sec": duration_sec,
        "generated_at": generated_at,
        "sources_markdown": _render_sources(sources_by_section),
        "assumptions_markdown": _render_assumptions(assumptions_by_section),
        "validation_markdown": _render_validation(validation_flags),
        "usage_summary": usage_summary or {},
    }
