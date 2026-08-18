"""
lib/promotion_gate.py
Phase 4 — Promotion Gate

Categorizes analyst corrections from TelemetryCapture and routes them:

  generalizable   → auto-promote to Few-Shot Bank via CDIUpdater.promote_exemplar()
  local_exception → stored entity-specific in telemetry/local_exceptions/, never globalized
  factual_error   → logged for investigation review
  stylistic       → acknowledged, not promoted (low-signal surface change)
  ambiguous       → quarantined for human curation in telemetry/quarantine/

The gate never silently learns from a signal it cannot categorize. Every decision
is logged to AIMS Mode A (promotion_gate_log.jsonl).

Design Invariant (permanently locked): only the generalizable class auto-promotes.
Local, factual, and stylistic corrections never enter the global Few-Shot Bank.
Ambiguous corrections never auto-promote — they sit in quarantine until a human
reviews them.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from lib.telemetry import TelemetryCapture, classify_edit_pattern

TELEMETRY_DIR = BASE / "telemetry"
LOCAL_EXCEPTIONS_DIR = TELEMETRY_DIR / "local_exceptions"
QUARANTINE_DIR = TELEMETRY_DIR / "quarantine"
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
CDI_EXEMPLAR_SURFACE = BASE / "cdi_layer" / "index" / "exemplar_surface.json"

# Category constants
CAT_GENERALIZABLE = "generalizable"
CAT_LOCAL_EXCEPTION = "local_exception"
CAT_FACTUAL_ERROR = "factual_error"
CAT_STYLISTIC = "stylistic"
CAT_AMBIGUOUS = "ambiguous"

# Entity-specific ID patterns (presence in diff signals entity scope)
_ENTITY_PATTERNS = [
    "account_", "experiment_", "incident_", "pipeline_",
    "EXP-", "ACC-", "FRA-", "INC-", "PLN-",
]

# Local-exception language: scope-narrowing phrases that explicitly limit
# a rule to a single entity (not a generalizable principle)
_LOCAL_EXCEPTION_SIGNALS = [
    "exempt from", "exempt ", "only for ", "applies only to", "only applies to",
    "do not apply", "is a known ", "is a test ", "internal test account",
    "except for", "except in the case of", "scoped to ", "noting that",
    "specific to ", "(noting ",
]

# Analyst-context keywords that indicate a factual error
_FACTUAL_CONTEXT_KEYWORDS = [
    "incorrect", "wrong", "error", "mistake", "inaccurate",
    "actual ", "wrong figure", "wrong number", "wrong rate",
    "off by", "miscalculation",
]

# STRONG rule-language patterns — unambiguous generalizable signals
_STRONG_GENERALIZABLE_SIGNALS = [
    "always start", "always check", "always query", "always include",
    "should always", "should never", "must always", "must never",
    "never recommend", "never propose", "never report",
    "every investigation", "every analysis", "every cycle", "every output",
    "for all ", "in all cases", "the rule is", "as a pattern",
    "going forward", "by convention", "consistently apply",
]

# Number-token regex — used to detect single short numerical edits
import re
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_to_aims_mode_a(event_type: str, payload: dict) -> None:
    AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": _now_iso(),
        "event_type": event_type,
        "payload": payload,
    }
    log_file = AIMS_MODE_A_DIR / "promotion_gate_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class PromotionGate:
    """
    Phase 4 Promotion Gate.

    Deterministic (L1) categorization followed by rule-based routing.
    The generalizable-class-only auto-promotion rule is a Design Invariant.

    Usage:
        gate = PromotionGate()
        result = gate.process_triple(triple_id)
        # or
        results = gate.process_all_pending()
    """

    def __init__(self):
        LOCAL_EXCEPTIONS_DIR.mkdir(parents=True, exist_ok=True)
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        self.tc = TelemetryCapture()

    # ─── categorization (L1 deterministic) ────────────────────────────────────

    def categorize_correction(
        self,
        triple: dict,
        agent_context: Optional[dict] = None,
    ) -> tuple[str, str]:
        """
        Categorize a correction triple.
        Returns (category, justification).

        Rules are evaluated in priority order (first match wins):
          1. distance < 0.05                            → stylistic
          2. entity-specific ID in diff + distance < 0.3 → local_exception
          3. number change in diff                       → factual_error
          4. edit_context contains factual keywords      → factual_error
          5. consistent structural op across ≥2 changes  → generalizable
          6. generalizable language in accepted output   → generalizable
          7. distance in [0.3, 0.7]                     → ambiguous
          8. distance < 0.2                             → stylistic
          9. default                                    → factual_error
        """
        diff = triple.get("diff", {})
        distance = diff.get("edit_distance", 0.0)
        changes = diff.get("change_summary", [])
        accepted_str = str(triple.get("accepted_output", ""))
        original_str = str(triple.get("agent_output", ""))
        accepted_lower = accepted_str.lower()
        original_lower = original_str.lower()
        edit_context = triple.get("edit_context", "").lower()

        # Detect tokens added/changed in the accepted output that weren't in original
        added_text = " ".join(
            str(c.get("edited", c.get("to", "")))
            for c in changes if isinstance(c, dict)
        ).lower()

        # Rule 1 — stylistic (near-identical)
        if distance < 0.05:
            return CAT_STYLISTIC, f"Edit distance {distance:.3f} < 0.05; surface-level change only"

        # Rule 2 — generalizable (STRONG rule language introduced)
        # Run before entity/numerical checks: rule language is a stronger signal
        # than incidental entity IDs or numbers cited within the new rule.
        strong_signals_added = [
            sig for sig in _STRONG_GENERALIZABLE_SIGNALS
            if sig in accepted_lower and sig not in original_lower
        ]
        if strong_signals_added and distance > 0.15:
            return (
                CAT_GENERALIZABLE,
                f"Strong rule language introduced ({len(strong_signals_added)} signal(s), "
                f"e.g. '{strong_signals_added[0].strip()}'); distance {distance:.2f}"
            )

        # Rule 3 — local exception (explicit scope-narrowing language)
        local_signals_added = [
            sig for sig in _LOCAL_EXCEPTION_SIGNALS
            if sig in accepted_lower and sig not in original_lower
        ]
        if local_signals_added:
            return (
                CAT_LOCAL_EXCEPTION,
                f"Local-exception language introduced ('{local_signals_added[0].strip()}'); "
                f"scope-narrowing change, not globalizable"
            )

        # Rule 4 — factual error (numerical change with small edit footprint)
        # Look for actual number tokens in original/accepted that differ
        original_nums = set(_NUMBER_RE.findall(original_str))
        accepted_nums = set(_NUMBER_RE.findall(accepted_str))
        nums_changed = original_nums.symmetric_difference(accepted_nums)
        if nums_changed and distance < 0.4:
            sample = list(nums_changed)[:3]
            return (
                CAT_FACTUAL_ERROR,
                f"Numerical tokens changed ({sample}); distance {distance:.2f} — factual correction"
            )

        # Rule 5 — factual error (analyst context keyword)
        if any(kw in edit_context for kw in _FACTUAL_CONTEXT_KEYWORDS):
            return CAT_FACTUAL_ERROR, f"Edit context indicates factual correction: '{edit_context[:60]}'"

        # Rule 6 — generalizable (consistent structural operation across changes)
        if diff.get("diff_type") == "json_structural" and len(changes) >= 2:
            ops = [c.get("op") for c in changes]
            if len(set(ops)) == 1 and ops[0]:
                return (
                    CAT_GENERALIZABLE,
                    f"Consistent structural op '{ops[0]}' applied across {len(ops)} locations — rule-like"
                )

        # Rule 7 — ambiguous (mid-range distance, no clearer signal)
        if 0.3 <= distance <= 0.75:
            return (
                CAT_AMBIGUOUS,
                f"Edit distance {distance:.2f} in ambiguous range [0.3, 0.75]; "
                f"no rule language, no entity exception, no numerical change"
            )

        # Rule 8 — stylistic (small edit, no specific pattern matched)
        if distance < 0.2:
            return CAT_STYLISTIC, f"Edit distance {distance:.2f}; no specific pattern matched — treated as stylistic"

        # Rule 9 — default: factual
        return CAT_FACTUAL_ERROR, f"Edit distance {distance:.2f}; default classification (no pattern match)"

    # ─── routing ─────────────────────────────────────────────────────────────

    def process_triple(
        self,
        triple_id: str,
        agent_context: Optional[dict] = None,
    ) -> dict:
        """
        Process a correction triple through the Promotion Gate.

        Returns:
          gate_decision_id, triple_id, category, routing_decision,
          justification, exemplar_id (if promoted), timestamp_utc
        """
        triple = self.tc.get_triple(triple_id)
        category, justification = self.categorize_correction(triple, agent_context)

        result = {
            "gate_decision_id": str(uuid.uuid4()),
            "triple_id": triple_id,
            "category": category,
            "justification": justification,
            "timestamp_utc": _now_iso(),
            "routing_decision": None,
            "exemplar_id": None,
        }

        print(f"\n[Promotion Gate] Processing {triple_id[:8]}...")
        print(f"  Category: {category}")
        print(f"  Justification: {justification[:80]}")

        if category == CAT_GENERALIZABLE:
            result["routing_decision"] = "AUTO_PROMOTE"
            exemplar_id = self._promote_to_few_shot_bank(triple, justification)
            result["exemplar_id"] = exemplar_id
            self.tc.update_promotion_status(triple_id, "PROMOTED", category)
            print(f"  → AUTO_PROMOTED | exemplar={exemplar_id[:8]}...")

        elif category == CAT_LOCAL_EXCEPTION:
            result["routing_decision"] = "STORE_LOCAL"
            self._store_local_exception(triple, justification)
            self.tc.update_promotion_status(triple_id, "LOCAL_STORED", category)
            print("  → STORE_LOCAL (entity-specific, not globalized)")

        elif category == CAT_FACTUAL_ERROR:
            result["routing_decision"] = "LOG_FACTUAL"
            self.tc.update_promotion_status(triple_id, "LOGGED_FACTUAL", category)
            print("  → LOG_FACTUAL (flagged for investigation review)")

        elif category == CAT_STYLISTIC:
            result["routing_decision"] = "ACKNOWLEDGE"
            self.tc.update_promotion_status(triple_id, "ACKNOWLEDGED_STYLISTIC", category)
            print("  → ACKNOWLEDGE (low-signal stylistic change)")

        elif category == CAT_AMBIGUOUS:
            result["routing_decision"] = "QUARANTINE"
            self._quarantine(triple, justification)
            self.tc.update_promotion_status(triple_id, "QUARANTINED", category)
            print("  → QUARANTINE (human curation required)")

        # Log every decision to AIMS Mode A — no silent decisions
        _log_to_aims_mode_a("PROMOTION_GATE_DECISION", {
            "gate_decision_id": result["gate_decision_id"],
            "triple_id": triple_id,
            "category": category,
            "routing_decision": result["routing_decision"],
            "justification": justification,
            "query_class": triple.get("query_class"),
            "agent_name": triple.get("agent_name"),
            "edit_distance": triple.get("diff", {}).get("edit_distance", 0.0),
            "exemplar_id": result.get("exemplar_id"),
        })

        return result

    def _promote_to_few_shot_bank(self, triple: dict, justification: str) -> str:
        """Auto-promote a generalizable correction to the Few-Shot Bank."""
        from cdi_layer.services.cdi_update import CDIUpdater
        from lib.second_brain import write_few_shot_entry

        exemplar_id = str(uuid.uuid4())
        exemplar = {
            "id": exemplar_id,
            "query_class": triple.get("query_class", "general"),
            "input": {
                "query_class": triple.get("query_class", "general"),
                "task_id": triple.get("task_id"),
                "agent_name": triple.get("agent_name", "unknown"),
                "original_hash": triple.get("agent_output_hash"),
            },
            "output": {
                "accepted_output": triple.get("accepted_output"),
                "diff_summary": triple.get("diff", {}).get("change_summary", [])[:5],
            },
            "justification": justification,
            "source_triple_id": triple["triple_id"],
            "edit_pattern": triple.get("edit_pattern", "unknown"),
        }

        updater = CDIUpdater(
            agent_name="promotion_gate",
            task_id=triple.get("task_id", "unknown"),
        )
        updater.promote_exemplar(exemplar)
        write_few_shot_entry(exemplar, triple)
        return exemplar_id

    def _store_local_exception(self, triple: dict, justification: str) -> None:
        entry = {
            "triple_id": triple["triple_id"],
            "query_class": triple.get("query_class"),
            "agent_name": triple.get("agent_name"),
            "justification": justification,
            "accepted_output": triple.get("accepted_output"),
            "timestamp_utc": _now_iso(),
            "scope": "entity_specific",
        }
        path = LOCAL_EXCEPTIONS_DIR / f"{triple['triple_id']}.json"
        path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")

    def _quarantine(self, triple: dict, justification: str) -> None:
        entry = {
            "triple_id": triple["triple_id"],
            "query_class": triple.get("query_class"),
            "agent_name": triple.get("agent_name"),
            "justification": justification,
            "timestamp_utc": _now_iso(),
            "status": "QUARANTINE_PENDING_HUMAN_REVIEW",
        }
        path = QUARANTINE_DIR / f"{triple['triple_id']}.json"
        path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")

        # Mirror to CDI exemplar_surface.json quarantine_queue
        try:
            data = json.loads(CDI_EXEMPLAR_SURFACE.read_text(encoding="utf-8"))
            queue = data.setdefault("promotion_gate", {}).setdefault("quarantine_queue", [])
            if not any(q.get("triple_id") == triple["triple_id"] for q in queue):
                queue.append(entry)
            data["_meta"]["last_updated"] = _now_iso()
            CDI_EXEMPLAR_SURFACE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            print(f"  [Warning] Could not mirror to CDI quarantine_queue: {e}")

    # ─── batch processing ─────────────────────────────────────────────────────

    def process_all_pending(self) -> list[dict]:
        """Process all PENDING triples through the gate. Returns list of results."""
        results = []
        for triple in self.tc.get_all_triples():
            if triple.get("promotion_status") == "PENDING":
                try:
                    results.append(self.process_triple(triple["triple_id"]))
                except Exception as e:
                    print(f"  [Warning] Error on triple {triple['triple_id'][:8]}: {e}")
        return results

    def get_quarantine_queue(self) -> list[dict]:
        """Return all quarantined triples awaiting human review."""
        items = []
        for p in QUARANTINE_DIR.glob("*.json"):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return sorted(items, key=lambda x: x.get("timestamp_utc", ""))

    def get_gate_statistics(self) -> dict:
        """Return aggregate statistics for the Promotion Gate decisions."""
        triples = self.tc.get_all_triples()
        categories: dict = {}
        for t in triples:
            cat = t.get("promotion_category", t.get("promotion_status", "PENDING"))
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_processed": len(triples),
            "by_category": categories,
            "quarantine_queue_size": len(self.get_quarantine_queue()),
        }
