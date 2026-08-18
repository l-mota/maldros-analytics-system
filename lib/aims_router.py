"""
lib/aims_router.py

Phase 6 — Full AIMS Routing.

Deterministic routing function that assigns every artifact to either:
  Mode A — Operational Log (auto-logged, no human gate)
  Mode B — Stakeholder Briefing (human sign-off required)

Routing rules per analytics_engineering_system_prompt.md (AIMS section):
  Mode B (human approval required):
    - Novel analytical findings
    - First-principles inventions (is_novel=True, DI #12)
    - Brittle Red-Team verdict
    - A/B ship/no-ship recommendation
    - New data product
    - Architectural change
    - L3+ escalation
    - Phase 7 structural improvement proposals

  Mode A (auto-logged):
    - Routine pipeline self-heals (L1–L2)
    - Routine telemetry exemplar promotions
    - Analogical-mode model generation with Robust or CR verdict
    - Operational records (capability bundle, context bundle, diagnostics L0–L2, etc.)

Every routing decision is logged to aims/mode_a/aims_routing_log.jsonl.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"


def route_artifact(artifact: dict) -> dict:
    """
    Determine Mode A or Mode B routing for a given artifact.

    Returns:
      {
        "routing_id": str,
        "routing_timestamp": str,
        "artifact_id": str,
        "artifact_type": str,
        "producing_agent": str,
        "mode": "A" | "B",
        "trigger": str,        # which rule fired
        "rationale": str,
        "human_sign_off_required": bool,
      }
    """
    mode, trigger, rationale = _evaluate_routing_rules(artifact)
    decision = {
        "routing_id": str(uuid.uuid4()),
        "routing_timestamp": datetime.now(timezone.utc).isoformat(),
        "artifact_id": artifact.get("artifact_id", "unknown"),
        "artifact_type": artifact.get("artifact_type", "unknown"),
        "producing_agent": artifact.get("producing_agent", "unknown"),
        "mode": mode,
        "trigger": trigger,
        "rationale": rationale,
        "human_sign_off_required": mode == "B",
    }
    _log_routing_decision(decision)
    return decision


def _evaluate_routing_rules(artifact: dict) -> tuple:
    """
    Apply routing rules in priority order. Returns (mode, trigger, rationale).
    Mode B triggers are checked first; Mode A is the default.
    """
    artifact_type = artifact.get("artifact_type", "")
    c = artifact.get("content", {})

    # ── Mode B checks (priority order, first match wins) ──────────────────────

    # Brittle Red-Team verdict — blocks production deployment
    rt_verdict = c.get("red_team_verdict", c.get("overall_verdict", ""))
    if rt_verdict == "Brittle":
        return ("B", "brittle_red_team",
                "Red-Team verdict is Brittle — adversarial vulnerability found that "
                "blocks production deployment. Requires human review and hardening plan approval.")

    # Phase 7 structural improvement proposal — always Mode B (architectural change)
    if artifact_type == "phase7_proposal" or c.get("is_phase7_proposal", False):
        return ("B", "phase7_proposal",
                "Phase 7 structural improvement proposal — modifies system architecture. "
                "Requires explicit operator sign-off (Design Invariant #2 — no auto-approve).")

    # AIMS Mode B artifact itself
    if artifact_type == "aims_mode_b":
        return ("B", "aims_mode_b_artifact",
                "AIMS Mode B artifact — stakeholder briefing requiring human review gate.")

    # Discovery report — always Mode B (novel finding deliverable)
    if artifact_type == "discovery_report":
        return ("B", "novel_analytical_finding",
                "Discovery Report is always a Mode B stakeholder deliverable — "
                "contains full dual-layer output requiring human review gate.")

    # Novel invention (Forge — is_novel=True, DI #12)
    if artifact_type == "invention_pipeline_report" and c.get("is_novel", False):
        return ("B", "novel_invention",
                f"Novel analytical framework (is_novel=True, typology: "
                f"{c.get('novel_invention_typology', 'N/A')}) — Innovation Mandate DI #12 "
                "triggers Mode B as a novel first-principles derivation.")

    # A/B ship/no-ship recommendation
    ship_verdict = c.get("ship_verdict", c.get("recommendation", ""))
    if artifact_type == "statistical_result" and ship_verdict in (
        "SHIP", "NO_SHIP", "HOLD_FOR_HARDENING", "ship", "no_ship"
    ):
        return ("B", "ab_ship_recommendation",
                f"A/B experiment ship/no-ship recommendation: {ship_verdict}. "
                "Requires analyst review before production deployment.")

    # L3+ escalation from Diagnostic Agent
    level = c.get("level", "L0")
    if artifact_type == "diagnostic_result" and level in ("L3", "L4"):
        return ("B", "l3_escalation",
                f"Diagnostic escalation level {level} — above L2 operational threshold. "
                "Requires human intervention beyond automated self-healing.")

    # Architectural change flagged in healing record
    if c.get("is_architectural_change", False):
        return ("B", "architectural_change",
                "Healing record flags a structural/architectural change — "
                "requires operator sign-off before production merge.")

    # Novel finding in evidence bundle (unless explicitly marked routine)
    if artifact_type == "evidence_bundle" and not c.get("is_routine_finding", False):
        if c.get("is_novel_finding", False) or c.get("primary_conclusion") not in (None, ""):
            return ("B", "novel_analytical_finding",
                    "Evidence bundle with novel analytical finding — "
                    "routes to Mode B for Discovery Report and stakeholder briefing.")

    # ── Mode A (auto-logged) ───────────────────────────────────────────────────

    # Routine healing L1/L2 (not escalated)
    if artifact_type == "healing_record" and not c.get("escalated", False):
        return ("A", "routine_self_heal_l1_l2",
                "Routine healing at L1/L2 — fully autonomous remediation, "
                "no human intervention required.")

    # Telemetry / Few-Shot Bank promotions
    if artifact_type in ("few_shot_exemplar", "promotion_gate_decision"):
        return ("A", "telemetry_exemplar_promotion",
                "Routine telemetry-driven exemplar promotion — auto-logged to Mode A.")

    # Analogical mode with Robust/CR verdict (non-novel)
    if (artifact_type == "invention_pipeline_report"
            and c.get("generation_mode") == "ANALOGICAL"
            and rt_verdict in ("Robust", "Conditionally Robust")):
        return ("A", "analogical_robust",
                "Analogical-mode framework generation with acceptable Red-Team verdict — "
                "auto-logged to Mode A. No novel first-principles derivation.")

    # Bottleneck report — operational telemetry analysis
    if artifact_type == "bottleneck_report":
        return ("A", "routine_ops",
                "Bottleneck report — operational telemetry analysis. Auto-logged to Mode A. "
                "Phase 7 proposals derived from it route separately (always Mode B).")

    # All other operational records
    if artifact_type in (
        "capability_bundle", "context_bundle", "algorithmic_rule_cycle",
        "telemetry_triple", "aims_mode_a", "sandbox_test_result",
        "diagnostic_result",  # L0–L2 diagnostics
    ):
        return ("A", "routine_ops",
                f"{artifact_type} — routine operational record, auto-logged to Mode A.")

    # Default: Mode A (log everything; unknown types do not silently escalate to Mode B)
    return ("A", "routine_ops",
            f"No Mode B trigger matched for artifact_type={artifact_type}. "
            "Defaulting to Mode A operational log.")


def verify_routing_for_all_artifacts(artifacts_dir: Path = None) -> dict:
    """
    Audit: scan all artifacts in the artifact store and report routing breakdown.
    Returns a summary with counts by mode and artifact type.
    """
    if artifacts_dir is None:
        artifacts_dir = BASE / "artifacts"

    total = 0
    mode_a_count = 0
    mode_b_count = 0
    by_type: dict = {}

    for type_dir in sorted(artifacts_dir.iterdir()):
        if not type_dir.is_dir():
            continue
        for artifact_file in type_dir.glob("*.json"):
            try:
                with open(artifact_file, "r", encoding="utf-8") as f:
                    artifact = json.load(f)
            except Exception:
                continue

            total += 1
            mode, trigger, _ = _evaluate_routing_rules(artifact)

            if mode == "A":
                mode_a_count += 1
            else:
                mode_b_count += 1

            atype = artifact.get("artifact_type", "unknown")
            if atype not in by_type:
                by_type[atype] = {"A": 0, "B": 0}
            by_type[atype][mode] += 1

    return {
        "total_artifacts_audited": total,
        "mode_a_count": mode_a_count,
        "mode_b_count": mode_b_count,
        "mode_b_pct": round(mode_b_count / total * 100, 1) if total else 0,
        "by_artifact_type": by_type,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _log_routing_decision(decision: dict) -> None:
    """Log every routing decision to AIMS Mode A for traceability."""
    AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
    log_file = AIMS_MODE_A_DIR / "aims_routing_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision) + "\n")
