"""
lib/algorithmic_rule.py
Phase 4 — The Algorithmic Rule (Design Invariant #5 — permanently locked)

Mandatory Exploration Budget: every 10th investigation cycle is diverted
to a counter-intuitive hypothesis drawn from the open Constraint Register.

  Default percentage:  10%      (locked floor at 5%; ceiling at 50%)
  Adjustable by:       analyst (operator) — in either direction
  Not adjustable by:   the system itself — under any condition

This module:
  - Maintains a persistent cycle counter at telemetry/algorithmic_rule_state.json
  - Decides whether the next cycle is an exploration cycle
  - Selects a counter-intuitive hypothesis from open Constraint Register entries
  - Logs every fire to AIMS Mode A (`algorithmic_rule_log.jsonl`)
  - Logs every fire to the Second Brain (`constraints/` subfolder)
  - Records to CDI Layer `phase7_signals.json` for compounding tracking

Compounding math — SPECIFIED DESIGN TARGET, NOT A MEASURED RESULT.
These figures are the modelled projection that motivates the exploration budget.
They are derived from the decay parameters below; they have not been observed
empirically and must not be cited as measured outcomes.
  without exploration: r ≈ 0.05 decay d=0.9   → 1.65× after 50 cycles (projected)
  with exploration:    r ≈ 0.05 sustained     → 11.5× after 50 cycles (projected)
"""

import json
import sys
import uuid
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from cdi_layer.services.cdi_read import CDIReader
from lib.second_brain import write_algorithmic_rule_entry

STATE_FILE = BASE / "telemetry" / "algorithmic_rule_state.json"
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"

# Hard-coded operational parameter (Design Invariant)
DEFAULT_EXPLORATION_PERCENT = 10.0
MIN_EXPLORATION_PERCENT = 5.0     # analyst-floor; system cannot go below
MAX_EXPLORATION_PERCENT = 50.0    # analyst-ceiling; system cannot go above


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
    log_file = AIMS_MODE_A_DIR / "algorithmic_rule_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class AlgorithmicRule:
    """
    The Algorithmic Rule controller.

    Usage in Orchestrator:
        ar = AlgorithmicRule(agent_name="orchestrator", task_id=task_id)
        cycle = ar.next_cycle()                  # increments + persists
        if cycle["is_exploration_cycle"]:
            diversion = ar.fire(cycle, task_id, reader)
            # Use diversion.hypothesis to replace/augment the standard investigation question
    """

    def __init__(self, agent_name: str = "orchestrator", task_id: str = "unknown"):
        self.agent_name = agent_name
        self.task_id = task_id
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # ─── state I/O ───────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "total_cycles": 0,
            "exploration_cycles_fired": 0,
            "exploration_percent": DEFAULT_EXPLORATION_PERCENT,
            "history": [],
            "last_constraint_used": None,
            "constraint_use_counts": {},
        }

    def _save_state(self, state: dict) -> None:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    # ─── analyst adjustment ──────────────────────────────────────────────────

    def set_exploration_percent(self, pct: float, set_by: str = "analyst") -> dict:
        """
        Adjust the exploration percentage. Analyst-only. Clamped to [5%, 50%].
        Logged to AIMS Mode A.
        """
        state = self._load_state()
        clamped = max(MIN_EXPLORATION_PERCENT, min(MAX_EXPLORATION_PERCENT, float(pct)))
        old = state.get("exploration_percent", DEFAULT_EXPLORATION_PERCENT)
        state["exploration_percent"] = clamped
        self._save_state(state)
        _log_to_aims_mode_a("ALGORITHMIC_RULE_PERCENT_ADJUSTED", {
            "old_percent": old, "new_percent": clamped, "set_by": set_by,
            "clamped_from_requested": pct != clamped,
        })
        return {"old": old, "new": clamped, "requested": pct}

    # ─── cycle decision ──────────────────────────────────────────────────────

    def next_cycle(self) -> dict:
        """
        Increment cycle counter. Decide whether this cycle is an exploration cycle.

        Decision rule: cycle is an exploration cycle iff
            current_total / 100 * exploration_percent has crossed a new integer.
        For the default 10%, this fires on every 10th cycle (cycles 10, 20, 30, ...).

        Returns: {
            cycle_number, is_exploration_cycle, exploration_percent,
            cycles_until_next_exploration, total_explorations_so_far
        }
        """
        state = self._load_state()
        state["total_cycles"] = state.get("total_cycles", 0) + 1
        cycle_n = state["total_cycles"]
        pct = state.get("exploration_percent", DEFAULT_EXPLORATION_PERCENT)

        expected_explorations = (cycle_n * pct) / 100.0
        fired_so_far = state.get("exploration_cycles_fired", 0)
        is_exploration = expected_explorations - fired_so_far >= 1.0

        prev_expected = ((cycle_n - 1) * pct) / 100.0
        cycles_until_next = (
            0 if is_exploration
            else max(1, int((fired_so_far + 1) * 100 / pct) - cycle_n)
        )

        self._save_state(state)

        return {
            "cycle_number": cycle_n,
            "is_exploration_cycle": is_exploration,
            "exploration_percent": pct,
            "expected_explorations": round(expected_explorations, 3),
            "fired_so_far": fired_so_far,
            "cycles_until_next_exploration": cycles_until_next,
            "decision_basis": (
                f"Cycle {cycle_n} × {pct}% = {expected_explorations:.2f} expected; "
                f"{fired_so_far} fired so far"
            ),
        }

    # ─── exploration cycle execution ─────────────────────────────────────────

    def fire(
        self,
        cycle: dict,
        task_id: str,
        reader: Optional[CDIReader] = None,
    ) -> dict:
        """
        Fire an exploration cycle. Pulls a counter-intuitive hypothesis from
        an open Constraint Register entry and logs the diversion.

        Returns: {
            cycle_number, constraint_id, constraint_description, hypothesis,
            justification, task_id
        }
        """
        if not cycle.get("is_exploration_cycle"):
            raise ValueError("fire() called on a non-exploration cycle")

        reader = reader or CDIReader(agent_name=self.agent_name, task_id=task_id)
        constraints = reader.get_open_constraints()

        constraint = self._pick_constraint(constraints)
        if not constraint:
            return self._fire_with_no_constraint(cycle, task_id)

        hypothesis = self._generate_counter_intuitive_hypothesis(constraint)
        diversion = {
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": constraint.get("constraint_id", constraint.get("id", "CR-UNKNOWN")),
            "constraint_description": constraint.get("description", ""),
            "hypothesis": hypothesis,
            "justification": (
                f"Algorithmic Rule cycle (#{cycle['cycle_number']}, every "
                f"{int(100 / cycle['exploration_percent'])}th cycle). Diverted from "
                f"standard high-probability investigation queue to test counter-intuitive "
                f"hypothesis drawn from open Constraint Register entry "
                f"{constraint.get('id', 'CR-UNKNOWN')}."
            ),
            "timestamp_utc": _now_iso(),
            "outcome": "DIVERTED — awaiting downstream investigation",
        }

        # Mark fired in persistent state + record constraint usage
        state = self._load_state()
        state["exploration_cycles_fired"] = state.get("exploration_cycles_fired", 0) + 1
        state["last_constraint_used"] = constraint.get("id")
        cid = constraint.get("constraint_id", constraint.get("id", "CR-UNKNOWN"))
        state.setdefault("constraint_use_counts", {})
        state["constraint_use_counts"][cid] = state["constraint_use_counts"].get(cid, 0) + 1
        state.setdefault("history", []).append({
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": cid,
            "timestamp_utc": diversion["timestamp_utc"],
        })
        self._save_state(state)

        # Log to AIMS Mode A
        _log_to_aims_mode_a("ALGORITHMIC_RULE_FIRED", {
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": cid,
            "hypothesis_summary": hypothesis[:200],
            "exploration_percent": cycle["exploration_percent"],
        })

        # Write to Second Brain
        try:
            write_algorithmic_rule_entry(diversion)
        except Exception as e:
            print(f"[AlgorithmicRule] Vault write failed: {e}")

        return diversion

    def _pick_constraint(self, constraints: list[dict]) -> Optional[dict]:
        """
        Pick the least-used open constraint. Spreads exploration coverage instead
        of repeatedly drawing from the most prominent constraint.
        """
        if not constraints:
            return None
        state = self._load_state()
        counts = state.get("constraint_use_counts", {})

        def cid_of(c: dict) -> str:
            return c.get("constraint_id", c.get("id", "CR-UNKNOWN"))

        def usage(c: dict) -> int:
            return counts.get(cid_of(c), 0)

        sorted_constraints = sorted(constraints, key=usage)
        min_use = usage(sorted_constraints[0])
        least_used = [c for c in sorted_constraints if usage(c) == min_use]
        # Stable pick among the least-used: deterministic by id
        return sorted(least_used, key=cid_of)[0]

    def _generate_counter_intuitive_hypothesis(self, constraint: dict) -> str:
        """
        Generate a counter-intuitive hypothesis framing from a constraint.
        Phase 4 mode: deterministic templated inversion. Phase 5 upgrade:
        Phase 5 reasoning modes drive hypothesis construction.
        """
        desc = constraint.get("description", constraint.get("summary", constraint.get("title", "")))
        status = constraint.get("status", "")
        cid = constraint.get("constraint_id", constraint.get("id", "CR-UNKNOWN"))

        templates = [
            (
                f"Counter-intuitive hypothesis ({cid}): the constraint "
                f"'{desc}' is not a limitation but a load-bearing system property. "
                f"What if removing it would produce worse outcomes than working "
                f"within it? Investigate the second-order effects of relaxing the "
                f"constraint and surface failure modes that the current restriction prevents."
            ),
            (
                f"Counter-intuitive hypothesis ({cid}): the standard assumption "
                f"underlying '{desc}' may be inverted in a subpopulation we have "
                f"not segmented. Investigate whether a known minority case actually "
                f"behaves opposite to the population mean, and whether that minority "
                f"is the load-bearing signal."
            ),
            (
                f"Counter-intuitive hypothesis ({cid}): '{desc}' has been treated "
                f"as a static constraint; investigate whether it is actually time-varying "
                f"and whether recent shifts in upstream context have changed the "
                f"constraint's validity without a corresponding update to downstream consumers."
            ),
        ]
        # Deterministic pick by constraint id hash
        idx = sum(ord(c) for c in cid) % len(templates)
        hypothesis = templates[idx]
        if status:
            hypothesis += f"\n\n(Constraint status: {status})"
        return hypothesis

    def _fire_with_no_constraint(self, cycle: dict, task_id: str) -> dict:
        """
        Special case: exploration cycle fires but Constraint Register is empty.
        Per spec, exploration cycles cannot be skipped. Falls back to a
        meta-hypothesis about system blind spots from CDI non_activation_log.
        """
        diversion = {
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": "CR-META-BLIND-SPOTS",
            "constraint_description": (
                "No open Constraint Register entries — meta-exploration fallback "
                "per Algorithmic Rule (cycles cannot be skipped)."
            ),
            "hypothesis": (
                "Counter-intuitive meta-hypothesis: query the CDI Layer "
                "non_activation_log for domains consistently not queried by any "
                "agent. Treat the longest-standing blind spot as the load-bearing "
                "signal the system has been systematically ignoring. Investigate "
                "what would change if that domain were forcibly queried for this cycle."
            ),
            "justification": (
                f"Algorithmic Rule cycle #{cycle['cycle_number']}; Constraint Register "
                f"is empty; system cannot skip exploration cycles; fell back to CDI "
                f"non-activation log as the source of counter-intuitive direction."
            ),
            "timestamp_utc": _now_iso(),
            "outcome": "DIVERTED — meta-exploration fallback",
        }

        state = self._load_state()
        state["exploration_cycles_fired"] = state.get("exploration_cycles_fired", 0) + 1
        state.setdefault("history", []).append({
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": "CR-META-BLIND-SPOTS",
            "timestamp_utc": diversion["timestamp_utc"],
        })
        self._save_state(state)

        _log_to_aims_mode_a("ALGORITHMIC_RULE_FIRED", {
            "cycle_number": cycle["cycle_number"],
            "task_id": task_id,
            "constraint_id": "CR-META-BLIND-SPOTS",
            "hypothesis_summary": diversion["hypothesis"][:200],
            "exploration_percent": cycle["exploration_percent"],
            "fallback_reason": "constraint_register_empty",
        })

        try:
            write_algorithmic_rule_entry(diversion)
        except Exception as e:
            print(f"[AlgorithmicRule] Vault write failed: {e}")

        return diversion

    # ─── reporting ───────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        return self._load_state()

    def get_exploration_rate(self) -> dict:
        """Return actual vs. target exploration rate (for Phase 7 compounding check)."""
        state = self._load_state()
        total = max(state.get("total_cycles", 0), 1)
        fired = state.get("exploration_cycles_fired", 0)
        actual_pct = (fired / total) * 100.0
        target_pct = state.get("exploration_percent", DEFAULT_EXPLORATION_PERCENT)
        return {
            "total_cycles": state.get("total_cycles", 0),
            "exploration_cycles_fired": fired,
            "actual_exploration_percent": round(actual_pct, 2),
            "target_exploration_percent": target_pct,
            "drift": round(actual_pct - target_pct, 2),
            "constraint_use_counts": state.get("constraint_use_counts", {}),
        }
