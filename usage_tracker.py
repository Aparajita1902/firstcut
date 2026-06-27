"""Cumulative token usage and cost tracking across the deck-generation pipeline.

Pass a single ``UsageTracker`` instance through the orchestrator to every stage.
Each stage records its API call usage via ``record(...)``. Stage 3 additionally
calls ``check_budget(...)`` after every billable call so a runaway iteration loop
can be aborted before it consumes the whole credit balance.

Pricing constants reflect Anthropic's public pricing as of mid-2026. If pricing
changes, update PRICING_USD_PER_M and nothing else needs to move.
"""

from __future__ import annotations


# Per-million-token pricing in USD. Update if Anthropic changes pricing.
PRICING_USD_PER_M = {
    "claude-opus-4-7":   {"input": 15.00, "cache_read": 1.50, "cache_write": 18.75, "output": 75.00},
    "claude-sonnet-4-6": {"input":  3.00, "cache_read": 0.30, "cache_write":  3.75, "output": 15.00},
}


def _pricing_for(model: str) -> dict:
    """Return pricing for a model string. Tolerant of model-version suffixes."""
    if model in PRICING_USD_PER_M:
        return PRICING_USD_PER_M[model]
    if "opus" in model:
        return PRICING_USD_PER_M["claude-opus-4-7"]
    if "sonnet" in model:
        return PRICING_USD_PER_M["claude-sonnet-4-6"]
    # Default to Sonnet pricing if model is unrecognised — better than crashing.
    return PRICING_USD_PER_M["claude-sonnet-4-6"]


class BudgetExceeded(RuntimeError):
    """Base class for cost-cap breaches. Catch this to handle either kind."""


class StageBudgetExceeded(BudgetExceeded):
    """Raised when a single stage exceeds its configured cost budget."""


class TotalBudgetExceeded(BudgetExceeded):
    """Raised when cumulative spend across all stages exceeds the per-deck cap."""


class UsageTracker:
    """Accumulates per-call token usage across stages and computes USD cost.

    ``total_budget_usd`` is the hard per-deck ceiling: once cumulative spend
    crosses it, the next ``check_budget`` call aborts the run. ``None`` disables
    the global cap (per-stage caps still apply).
    """

    def __init__(self, total_budget_usd: float | None = None) -> None:
        self.calls: list[dict] = []
        self.total_budget_usd = total_budget_usd

    def record(self, stage: str, model: str, usage) -> dict:
        """Record one API call. ``usage`` is the ``message.usage`` from a response."""
        rec = {
            "stage": stage,
            "model": model,
            "input_tokens":        getattr(usage, "input_tokens", 0) or 0,
            "output_tokens":       getattr(usage, "output_tokens", 0) or 0,
            "cache_read_tokens":   getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_create_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        rec["cost_usd"] = self._cost(model, rec)
        self.calls.append(rec)
        return rec

    @staticmethod
    def _cost(model: str, r: dict) -> float:
        p = _pricing_for(model)
        return round(
            r["input_tokens"]        / 1_000_000 * p["input"]
            + r["cache_read_tokens"]   / 1_000_000 * p["cache_read"]
            + r["cache_create_tokens"] / 1_000_000 * p["cache_write"]
            + r["output_tokens"]       / 1_000_000 * p["output"],
            4,
        )

    def stage_cost_usd(self, stage: str) -> float:
        return sum(r["cost_usd"] for r in self.calls if r["stage"] == stage)

    def stage_call_count(self, stage: str) -> int:
        return sum(1 for r in self.calls if r["stage"] == stage)

    def total_cost_usd(self) -> float:
        return sum(r["cost_usd"] for r in self.calls)

    def summary(self) -> dict:
        """Per-stage breakdown suitable for surfacing in the UI / output package."""
        stages: dict[str, dict] = {}
        for r in self.calls:
            s = stages.setdefault(
                r["stage"],
                {"calls": 0, "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            s["calls"] += 1
            s["input_tokens"]      += r["input_tokens"]
            s["cache_read_tokens"] += r["cache_read_tokens"]
            s["output_tokens"]     += r["output_tokens"]
            s["cost_usd"]          += r["cost_usd"]
        for s in stages.values():
            s["cost_usd"] = round(s["cost_usd"], 4)
        return {
            "stages": stages,
            "total_cost_usd": round(self.total_cost_usd(), 4),
            "total_calls": len(self.calls),
        }


def check_budget(tracker: UsageTracker, stage: str, budget_usd: float) -> None:
    """Enforce both the per-stage cap and the per-deck total cap.

    Raises ``StageBudgetExceeded`` if ``stage`` has spent more than ``budget_usd``,
    or ``TotalBudgetExceeded`` if cumulative spend across all stages has crossed
    ``tracker.total_budget_usd`` (when that global cap is set).

    Both checks are post-call: they fire once a recorded call pushes spend over a
    cap, aborting the *next* call. Spend can therefore overshoot a cap by at most
    the cost of the single call that crossed it.
    """
    total = tracker.total_cost_usd()
    if tracker.total_budget_usd is not None and total > tracker.total_budget_usd:
        raise TotalBudgetExceeded(
            f"Per-deck total cap exceeded: ${total:.2f} spent vs "
            f"${tracker.total_budget_usd:.2f} allowed. Aborting to prevent runaway cost."
        )
    spent = tracker.stage_cost_usd(stage)
    if spent > budget_usd:
        raise StageBudgetExceeded(
            f"Stage '{stage}' exceeded its budget cap: ${spent:.2f} spent vs "
            f"${budget_usd:.2f} allowed. Aborting to prevent runaway cost."
        )
