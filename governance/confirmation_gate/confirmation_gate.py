"""
Confirmation Gate — governance/confirmation_gate/confirmation_gate.py
Deliverable 0.12.

Catches triggering conditions → routes to Review Queue → HIGH notification →
no-auto-approve enforced → decisions logged to AIMS Mode A.

PERMANENT RULE (Design Invariant #2):
No auto-approve under any condition. Not on timeout. Not on operator absence.
Silence ≠ approval. This rule is locked.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from governance.notification.notification import (
    NotificationMechanism, ReviewQueueMonitor, Severity, NotificationCategory
)

BASE = Path(__file__).resolve().parents[2]
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
OPERATOR_CONFIG_FILE = BASE / "governance" / "operator_config.json"


class ConfirmationGateTrigger:
    """Defines what causes the Confirmation Gate to activate."""

    @staticmethod
    def financial_materiality(impact_usd: float, config: dict) -> bool:
        return impact_usd >= config["materiality_threshold"]["financial_usd"]

    @staticmethod
    def metric_threshold_breach(metric: str, value: float, threshold: float) -> bool:
        return value >= threshold

    @staticmethod
    def brittle_red_team_verdict(verdict: str) -> bool:
        return verdict == "Brittle"

    @staticmethod
    def ab_experiment_recommendation(ship_verdict: str) -> bool:
        return ship_verdict in ("ship", "no_ship")

    @staticmethod
    def novel_finding(is_novel: bool) -> bool:
        return is_novel

    @staticmethod
    def new_data_product(is_new_product: bool) -> bool:
        return is_new_product

    @staticmethod
    def architectural_change(is_arch_change: bool) -> bool:
        return is_arch_change

    @staticmethod
    def l3_escalation(escalation_level: int) -> bool:
        return escalation_level >= 3

    @staticmethod
    def phase_7_proposal(is_phase7_proposal: bool) -> bool:
        return is_phase7_proposal


class ConfirmationGate:
    """
    Confirmation Gate — routes items requiring human authorization to the Review Queue.

    PERMANENT CONSTRAINT: No auto-approve. No timeout approval.
    Every item requires an explicit operator decision.
    Decisions are logged to AIMS Mode A.
    """

    def __init__(self):
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
        self.notifier = NotificationMechanism()
        self.queue_monitor = ReviewQueueMonitor()
        self._config = self._load_config()

    def _load_config(self) -> dict:
        with open(OPERATOR_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_and_gate(
        self,
        artifact_id: str,
        artifact_type: str,
        producing_agent: str,
        trigger_reason: str,
        trigger_category: str,
        priority: str = "HIGH",
        context: Optional[dict] = None,
    ) -> str:
        """
        Check if an artifact requires Confirmation Gate review.
        If yes: add to Review Queue, send HIGH notification, log to AIMS Mode A.
        Returns the queue item_id.

        NO AUTO-APPROVE: this method can only submit to the queue.
        The operator's explicit response is required before any gated action proceeds.
        """
        gate_item = {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "producing_agent": producing_agent,
            "trigger_reason": trigger_reason,
            "trigger_category": trigger_category,
            "priority": priority,
            "context": context or {},
            "no_auto_approve": True,  # Permanent. Cannot be changed.
            "requires_explicit_operator_decision": True,
        }

        # Add to Review Queue
        item_id = self.queue_monitor.add_item(gate_item)
        queue = self.queue_monitor.get_queue()

        # Send HIGH notification (always — cannot be disabled)
        self.notifier.send(
            severity=Severity.HIGH,
            category=NotificationCategory.GOVERNANCE,
            title=f"Confirmation Gate: {trigger_category}",
            message=(
                f"Artifact {artifact_id[:8]}... from {producing_agent} requires your review.\n"
                f"Reason: {trigger_reason}\n"
                f"Queue depth: {queue['item_count']} items (state: {queue['queue_state']})\n"
                f"NO AUTO-APPROVE — explicit decision required."
            ),
            source_agent=producing_agent,
            artifact_ref=artifact_id,
            requires_action=True,
        )

        # Log to AIMS Mode A
        self._log_to_aims_mode_a({
            "event_type": "CONFIRMATION_GATE_TRIGGERED",
            "item_id": item_id,
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "producing_agent": producing_agent,
            "trigger_reason": trigger_reason,
            "trigger_category": trigger_category,
            "queue_depth_at_trigger": queue["item_count"],
            "no_auto_approve_confirmed": True,
        })

        return item_id

    def record_decision(
        self,
        item_id: str,
        decision: str,
        rationale: str,
        decided_by: str = "Luis",
    ) -> None:
        """
        Record the operator's explicit decision on a Confirmation Gate item.
        Only callable by the operator — not by any agent.

        decision: "approve" | "reject" | "request_revision"
        """
        if decision not in ("approve", "reject", "request_revision"):
            raise ValueError(f"Invalid decision: {decision}. Must be approve/reject/request_revision")

        queue = self.queue_monitor.get_queue()
        item_found = False
        for item in queue["items"]:
            if item.get("item_id") == item_id:
                item["status"] = "decided"
                item["decision"] = decision
                item["rationale"] = rationale
                item["decided_by"] = decided_by
                item["decided_at"] = datetime.now(timezone.utc).isoformat()
                item_found = True
                break

        if not item_found:
            raise ValueError(f"Item {item_id} not found in Review Queue")

        queue["item_count"] = len([i for i in queue["items"] if i["status"] == "pending"])
        self.queue_monitor._save_queue(queue)

        self._log_to_aims_mode_a({
            "event_type": "CONFIRMATION_GATE_DECIDED",
            "item_id": item_id,
            "decision": decision,
            "rationale": rationale,
            "decided_by": decided_by,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        self.notifier.send(
            severity=Severity.OPERATIONAL,
            category=NotificationCategory.GOVERNANCE,
            title=f"Decision recorded: {decision.upper()}",
            message=f"Confirmation Gate item {item_id[:8]}... → {decision}. Rationale: {rationale}",
            source_agent="operator",
            requires_action=False,
        )

    def _log_to_aims_mode_a(self, entry: dict) -> None:
        entry["aims_entry_id"] = str(uuid.uuid4())
        entry["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        log_file = AIMS_MODE_A_DIR / "confirmation_gate_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_pending_items(self) -> list[dict]:
        """Return all pending Confirmation Gate items."""
        queue = self.queue_monitor.get_queue()
        return [i for i in queue.get("items", []) if i.get("status") == "pending"]

    def get_queue_state(self) -> dict:
        """Return current Review Queue state summary."""
        queue = self.queue_monitor.get_queue()
        return {
            "state": queue["queue_state"],
            "item_count": queue["item_count"],
            "pending_items": self.get_pending_items(),
            "phase7_allowed": queue["queue_state"] not in ("red", "critical"),
        }


def evaluate_artifact_for_gate(
    artifact: dict,
    config: Optional[dict] = None,
) -> Optional[dict]:
    """
    Evaluate whether an artifact should be routed through the Confirmation Gate.
    Returns a gate_trigger dict if gating is needed, None if not.

    This is called by the Orchestrator on every artifact before delivery.
    """
    if config is None:
        with open(OPERATOR_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

    artifact_type = artifact.get("artifact_type", "")
    content = artifact.get("content", {})
    triggers = ConfirmationGateTrigger()

    # Red-Team Brittle verdict
    if artifact_type == "red_team_report":
        if triggers.brittle_red_team_verdict(content.get("verdict", "")):
            return {
                "trigger_reason": "Red-Team Agent returned Brittle verdict — do not ship without remediation",
                "trigger_category": "brittle_red_team_verdict",
                "priority": "HIGH",
            }

    # A/B experiment ship/no-ship
    if artifact_type == "statistical_result":
        exp = content.get("experiment_analysis", {})
        if exp and triggers.ab_experiment_recommendation(exp.get("ship_verdict", "")):
            return {
                "trigger_reason": f"A/B ship/no-ship recommendation: {exp.get('ship_verdict')}",
                "trigger_category": "ab_ship_no_ship",
                "priority": "HIGH",
            }

    # AIMS Mode B — novel findings, architectural changes, new data products
    if artifact_type == "aims_mode_b":
        trigger_cat = content.get("trigger_category", "")
        if trigger_cat in ("novel_analytical_finding", "first_principles_invention",
                           "new_data_product", "architectural_change"):
            return {
                "trigger_reason": f"AIMS Mode B output — trigger: {trigger_cat}",
                "trigger_category": trigger_cat,
                "priority": "HIGH",
            }

    # Discovery Report — high materiality findings
    if artifact_type == "discovery_report":
        findings = content.get("findings_technical", [])
        critical_findings = [f for f in findings if f.get("materiality") == "critical"]
        if critical_findings:
            return {
                "trigger_reason": f"{len(critical_findings)} critical-materiality finding(s) in Discovery Report",
                "trigger_category": "high_materiality_output",
                "priority": "HIGH",
            }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI — operator sign-off interface
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    """
    Operator CLI for the Confirmation Gate.

    Two modes:
      --list                                        Show pending Review Queue items
      --artifact-id <UUID> --decision <D> --rationale <text>
                                                    Record a decision on an artifact

    If the artifact is not yet in the Review Queue (e.g., when the operator
    is signing off on an artifact produced by a partial pipeline that never
    enqueued it), pass --enqueue-if-missing to auto-enqueue + decide in one
    step. This is the typical Phase 1 sign-off path.
    """
    import argparse
    parser = argparse.ArgumentParser(
        description="Confirmation Gate operator CLI — record explicit decisions on Review Queue items.",
    )
    parser.add_argument("--list", action="store_true",
                        help="List pending Review Queue items and exit.")
    parser.add_argument("--artifact-id",
                        help="Artifact UUID to decide on (e.g. f3d5a232-...).")
    parser.add_argument("--decision",
                        choices=["approve", "reject", "request_revision",
                                 "APPROVE", "REJECT", "REQUEST_REVISION"],
                        help="Operator decision.")
    parser.add_argument("--rationale",
                        help="Plain-language reason for the decision (recorded to AIMS Mode A).")
    parser.add_argument("--decided-by", default="Luis",
                        help="Operator identifier (default: Luis).")
    parser.add_argument("--enqueue-if-missing", action="store_true",
                        help="If the artifact is not yet in the Review Queue, "
                             "enqueue it as an aims_mode_b/MODE_B_REVIEW item before deciding.")
    parser.add_argument("--artifact-type", default="aims_mode_b",
                        help="Artifact type (used only when auto-enqueuing). Default: aims_mode_b.")
    args = parser.parse_args()

    gate = ConfirmationGate()

    if args.list:
        state = gate.get_queue_state()
        print(f"Queue state : {state['state']}")
        print(f"Pending     : {len(state['pending_items'])}")
        for it in state["pending_items"]:
            print(f"  • item_id={it.get('item_id','?')[:8]}  "
                  f"artifact={(it.get('artifact_id') or '-')[:8]}  "
                  f"agent={it.get('producing_agent','?')}  "
                  f"reason={it.get('trigger_reason','?')[:60]}")
        return

    if not args.artifact_id or not args.decision or not args.rationale:
        parser.error("--artifact-id, --decision, and --rationale are all required (or use --list).")

    decision = args.decision.lower()

    # Find item by artifact_id
    queue = gate.queue_monitor.get_queue()
    item_id = None
    for item in queue.get("items", []):
        if item.get("artifact_id") == args.artifact_id and item.get("status") == "pending":
            item_id = item["item_id"]
            break

    if item_id is None:
        if not args.enqueue_if_missing:
            print(f"ERROR: artifact {args.artifact_id} is not in the Review Queue.")
            print("       Pass --enqueue-if-missing to enqueue it first.")
            sys.exit(1)
        item_id = gate.check_and_gate(
            artifact_id=args.artifact_id,
            artifact_type=args.artifact_type,
            producing_agent="storyteller",
            trigger_reason="Operator review of AIMS Mode B artifact (Phase 1 sign-off)",
            trigger_category="MODE_B_REVIEW",
            priority="HIGH",
        )
        print(f"Enqueued as item {item_id[:8]} (was not previously in Review Queue).")

    gate.record_decision(
        item_id=item_id,
        decision=decision,
        rationale=args.rationale,
        decided_by=args.decided_by,
    )
    print(f"")
    print(f"Decision recorded : {decision.upper()}")
    print(f"Item              : {item_id}")
    print(f"Artifact          : {args.artifact_id}")
    print(f"Decided by        : {args.decided_by}")
    print(f"Rationale         : {args.rationale}")
    print(f"")
    print(f"Logged to: aims/mode_a/confirmation_gate_log.jsonl")
    print(f"Phase 1 sign-off complete." if decision == "approve" else "")


if __name__ == "__main__":
    _cli()
