"""
lib/few_shot_bank.py
Phase 4 — Few-Shot Bank

Versioned store of approved telemetry exemplars in the Second Brain
(/exemplars/ subfolder). Retrieval injects matching exemplars into future
agent prompt context for the matching query class.

Behavior changes through retrieval-time context, not model retraining —
every change auditable, reversible, attributable to a named exemplar.

Read path:  CDI Layer `exemplar_surface.json` (single source of truth for
            active exemplars; written by `CDIUpdater.promote_exemplar()`).
Write path: Only the PromotionGate writes — via that same CDI update interface.
            Direct writes are forbidden.

Phase 4 retrieval mode: exact query_class match + recency weighting.
Phase 5 upgrade: vector-similarity retrieval (deferred).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from cdi_layer.services.cdi_read import CDIReader

EXEMPLAR_SURFACE = BASE / "cdi_layer" / "index" / "exemplar_surface.json"

# Phase 4 retrieval defaults
MAX_EXEMPLARS_PER_QUERY = 3            # Bounded — don't drown the prompt
MIN_RECENCY_SCORE = 0.0                # All promoted exemplars eligible
RECENCY_HALF_LIFE_DAYS = 30.0          # Score decays by half over 30 days


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(iso_str: str) -> float:
    if not iso_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return max(delta.total_seconds() / 86400.0, 0.0)
    except Exception:
        return 0.0


def _recency_score(promoted_at: str) -> float:
    """Exponential decay: 1.0 at promotion, 0.5 after RECENCY_HALF_LIFE_DAYS."""
    days = _days_since(promoted_at)
    return 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


class FewShotBank:
    """
    Phase 4 Few-Shot Bank.

    Reads from CDI `exemplar_surface.json`. Writes are not exposed here —
    promotion goes through `PromotionGate.process_triple()` which routes
    through `CDIUpdater.promote_exemplar()`.

    Usage:
        bank = FewShotBank(agent_name="analyst", task_id=task_id)
        exemplars = bank.retrieve(query_class="api_abuse_investigation")
        prompt_section = bank.format_for_prompt(exemplars)
        # ... inject into agent prompt before LLM call
    """

    def __init__(self, agent_name: str = "unknown", task_id: str = "unknown"):
        self.agent_name = agent_name
        self.task_id = task_id

    # ─── retrieval ───────────────────────────────────────────────────────────

    def retrieve(
        self,
        query_class: str,
        limit: int = MAX_EXEMPLARS_PER_QUERY,
        min_recency: float = MIN_RECENCY_SCORE,
    ) -> list[dict]:
        """
        Retrieve up to `limit` exemplars matching `query_class`, sorted by
        recency-decayed score (most recent first).

        Records CDI Layer query via CDIReader so the non-activation log
        reflects exemplar_surface use.
        """
        reader = CDIReader(agent_name=self.agent_name, task_id=self.task_id)
        all_exemplars = reader.get_exemplars(query_class=query_class)

        scored: list[tuple] = []
        for ex in all_exemplars:
            score = _recency_score(ex.get("promoted_at", _now_iso()))
            if score >= min_recency:
                scored.append((score, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = []
        for score, ex in scored[:limit]:
            ex = dict(ex)
            ex["_retrieval_recency_score"] = round(score, 4)
            result.append(ex)
        return result

    def retrieve_for_agent(
        self,
        agent_name: str,
        query_class: str,
        limit: int = MAX_EXEMPLARS_PER_QUERY,
    ) -> list[dict]:
        """Retrieve exemplars relevant to a specific agent role."""
        candidates = self.retrieve(query_class, limit=limit * 2)
        # Filter to exemplars whose source agent matches
        for_agent = [
            e for e in candidates
            if e.get("input", {}).get("agent_name") == agent_name
        ]
        if for_agent:
            return for_agent[:limit]
        # Fall back to class-level matches if no agent-specific exemplar exists
        return candidates[:limit]

    # ─── prompt injection ────────────────────────────────────────────────────

    def format_for_prompt(self, exemplars: list[dict]) -> str:
        """
        Format exemplars as a prompt-injectable block.
        Returns "" if no exemplars — caller should skip the section entirely.
        """
        if not exemplars:
            return ""

        lines = [
            "## FEW-SHOT EXEMPLARS (Telemetry-derived — auto-promoted by Promotion Gate)",
            "",
            "The following exemplars represent generalizable corrections from prior cycles.",
            "Each was promoted to the Few-Shot Bank because human review consistently produced",
            "the same structural improvement to outputs of this class. Apply these patterns",
            "where context permits; deviate explicitly if the current task warrants it.",
            "",
        ]
        for i, ex in enumerate(exemplars, start=1):
            qc = ex.get("query_class", "general")
            pattern = ex.get("edit_pattern", "unknown")
            justification = ex.get("justification", "")
            recency = ex.get("_retrieval_recency_score", 1.0)
            output_json = json.dumps(ex.get("output", {}), indent=2, default=str)
            if len(output_json) > 1200:
                output_json = output_json[:1200] + "\n  ... (truncated)"

            lines.append(f"### Exemplar {i} — class: `{qc}` | pattern: `{pattern}` | recency: {recency:.2f}")
            lines.append("")
            lines.append(f"**Why promoted:** {justification}")
            lines.append("")
            lines.append("**Accepted output pattern:**")
            lines.append("```json")
            lines.append(output_json)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    def inject_into_system_prompt(self, base_prompt: str, query_class: str,
                                   agent_name: Optional[str] = None) -> tuple[str, list[str]]:
        """
        Inject few-shot exemplars into a base system prompt.
        Returns (augmented_prompt, list_of_injected_exemplar_ids).
        If no exemplars match, returns (base_prompt, []) unchanged.
        """
        if agent_name:
            exemplars = self.retrieve_for_agent(agent_name, query_class)
        else:
            exemplars = self.retrieve(query_class)

        if not exemplars:
            return base_prompt, []

        injection = self.format_for_prompt(exemplars)
        injected_ids = [e.get("id", "?") for e in exemplars]

        # Insert before any "RULES" / "HARD RULES" / "RESPONSE FORMAT" section
        # if present; otherwise append after the role description.
        markers = ("HARD RULES", "RULES", "RESPONSE FORMAT", "OUTPUT FORMAT")
        for marker in markers:
            idx = base_prompt.find(marker)
            if idx > 0:
                return (
                    base_prompt[:idx] + injection + "\n" + base_prompt[idx:],
                    injected_ids,
                )
        return base_prompt + "\n\n" + injection, injected_ids

    # ─── statistics ──────────────────────────────────────────────────────────

    def bank_state(self) -> dict:
        """Return current Few-Shot Bank state (total exemplars, classes covered)."""
        if not EXEMPLAR_SURFACE.exists():
            return {"total_exemplars": 0, "query_classes_covered": [], "last_promotion": None}
        data = json.loads(EXEMPLAR_SURFACE.read_text(encoding="utf-8"))
        return data.get("bank_state", {})

    def list_query_classes(self) -> list[str]:
        return self.bank_state().get("query_classes_covered", [])

    def list_all_exemplars(self) -> list[dict]:
        if not EXEMPLAR_SURFACE.exists():
            return []
        data = json.loads(EXEMPLAR_SURFACE.read_text(encoding="utf-8"))
        return data.get("exemplars", [])
