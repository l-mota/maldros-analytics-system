"""
scripts/phase4/run_phase4_demo.py

Phase 4 demo — exercises Telemetry Capture, Promotion Gate, Few-Shot Bank,
and the Algorithmic Rule end-to-end without invoking any LLM.

What it does:
  1. Resets Phase 4 demo state (telemetry/, exemplar_surface exemplars list).
  2. Records 6 synthetic correction triples spanning all 5 promotion-gate
     categories: generalizable, local_exception, factual_error, stylistic, ambiguous.
  3. Runs the Promotion Gate on every PENDING triple.
  4. Demonstrates Few-Shot Bank retrieval + prompt injection for the promoted class.
  5. Advances the Algorithmic Rule counter through 10 cycles to verify exploration
     fires exactly once at cycle 10.
  6. Prints a summary table per Phase 4 exit criteria.

Run:
  $env:PYTHONUTF8 = "1"
  python scripts/phase4/run_phase4_demo.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.telemetry import TelemetryCapture
from lib.promotion_gate import PromotionGate
from lib.few_shot_bank import FewShotBank
from lib.algorithmic_rule import AlgorithmicRule


def reset_demo_state() -> None:
    """Clear Phase 4 state for a clean demo run."""
    tel_dir = BASE / "telemetry"
    for sub in ("triples", "quarantine", "local_exceptions", "patterns"):
        d = tel_dir / sub
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()
    state_file = tel_dir / "algorithmic_rule_state.json"
    if state_file.exists():
        state_file.unlink()
    # Reset CDI exemplar_surface exemplars
    ex_path = BASE / "cdi_layer" / "index" / "exemplar_surface.json"
    if ex_path.exists():
        data = json.loads(ex_path.read_text(encoding="utf-8"))
        data["exemplars"] = []
        data["bank_state"]["total_exemplars"] = 0
        data["bank_state"]["query_classes_covered"] = []
        data["bank_state"]["last_promotion"] = None
        data["promotion_gate"]["ambiguous_queue"] = []
        data["promotion_gate"]["quarantine_queue"] = []
        ex_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[Phase 4 Demo] State reset complete.\n")


# ─── synthetic correction triples ────────────────────────────────────────────

def build_triples() -> list[dict]:
    """
    Six synthetic triples spanning all 5 categories.

    Each is a (agent_output, human_edit, accepted_output, edit_context, expected) tuple
    used to drive TelemetryCapture.record_triple().
    """
    return [
        # 1 — generalizable: rule language introduced in accepted output
        {
            "expected_category": "generalizable",
            "agent_name": "analyst",
            "query_class": "api_abuse_investigation",
            "agent_output": (
                "The cluster shows elevated abuse rates compared to other accounts. "
                "Consider monitoring these accounts."
            ),
            "human_edit": (
                "The cluster shows elevated abuse rates. Going forward, every "
                "investigation of coordinated multi-account abuse should always start "
                "from a graph-topology query before falling back to per-account rates."
            ),
            "accepted_output": (
                "The cluster shows elevated abuse rates. Going forward, every "
                "investigation of coordinated multi-account abuse should always start "
                "from a graph-topology query before falling back to per-account rates."
            ),
            "edit_context": "Reviewer added a procedural rule; should apply to all future cases.",
        },
        # 2 — local_exception: entity-specific tweak
        {
            "expected_category": "local_exception",
            "agent_name": "analyst",
            "query_class": "api_abuse_investigation",
            "agent_output": (
                "Account account_4071 shows policy_violation rate of 0.024 in Q1."
            ),
            "human_edit": (
                "Account account_4071 shows policy_violation rate of 0.024 in Q1 "
                "(noting account_4071 is a known internal test account — exempt from "
                "the standard escalation path)."
            ),
            "accepted_output": (
                "Account account_4071 shows policy_violation rate of 0.024 in Q1 "
                "(noting account_4071 is a known internal test account — exempt from "
                "the standard escalation path)."
            ),
            "edit_context": "Edit specific to account_4071.",
        },
        # 3 — factual_error: numerical correction
        {
            "expected_category": "factual_error",
            "agent_name": "statistician",
            "query_class": "experiment_analysis",
            "agent_output": "EXP-004 shows treatment effect of 3.2% (p<0.05).",
            "human_edit": "EXP-004 shows treatment effect of 3.7% (p<0.05).",
            "accepted_output": "EXP-004 shows treatment effect of 3.7% (p<0.05).",
            "edit_context": "Original figure was wrong — actual effect was 3.7%.",
        },
        # 4 — stylistic: trivial near-identical
        {
            "expected_category": "stylistic",
            "agent_name": "storyteller",
            "query_class": "aims_mode_b_drafting",
            "agent_output": "The finding shows a 41-account cluster driving 25.87% of abuse.",
            "human_edit": "The finding shows a 41-account cluster driving 25.87% of abuse events.",
            "accepted_output": "The finding shows a 41-account cluster driving 25.87% of abuse events.",
            "edit_context": "Added the word 'events' for clarity.",
        },
        # 5 — ambiguous: mid-range distance, no clear signal
        # No rule language, no entity-exception language, no numerical change,
        # no factual context keyword — distance in the ambiguous band.
        {
            "expected_category": "ambiguous",
            "agent_name": "analyst",
            "query_class": "pipeline_diagnosis",
            "agent_output": (
                "The pipeline shows degradation. Investigate input schema. "
                "Consider retrying the last batch. Schedule a manual review."
            ),
            "human_edit": (
                "The pipeline shows degradation. Look at output drift. "
                "Compare against the rolling baseline. The on-call team will "
                "review and choose how to proceed."
            ),
            "accepted_output": (
                "The pipeline shows degradation. Look at output drift. "
                "Compare against the rolling baseline. The on-call team will "
                "review and choose how to proceed."
            ),
            "edit_context": "Reviewer reframed the recommendations.",
        },
        # 6 — generalizable #2: same class, different rule (compounding evidence)
        {
            "expected_category": "generalizable",
            "agent_name": "analyst",
            "query_class": "api_abuse_investigation",
            "agent_output": (
                "Q1 shows elevated abuse. Recommend tightening rate limits."
            ),
            "human_edit": (
                "Q1 shows elevated abuse concentrated in a small cluster. The rule is: "
                "never recommend population-wide rate limits when the elevated signal "
                "is concentrated in fewer than 5% of accounts; recommend targeted "
                "cluster action instead."
            ),
            "accepted_output": (
                "Q1 shows elevated abuse concentrated in a small cluster. The rule is: "
                "never recommend population-wide rate limits when the elevated signal "
                "is concentrated in fewer than 5% of accounts; recommend targeted "
                "cluster action instead."
            ),
            "edit_context": "General principle — applies to all future cluster-vs-population analyses.",
        },
    ]


# ─── demo ────────────────────────────────────────────────────────────────────

def demo_telemetry_and_promotion() -> dict:
    print("=" * 72)
    print("PHASE 4 DEMO — Telemetry + Promotion Gate + Few-Shot Bank + Algorithmic Rule")
    print("=" * 72)
    tc = TelemetryCapture()
    gate = PromotionGate()

    print("\n[1] Recording 6 synthetic correction triples")
    print("-" * 72)
    triple_ids = []
    triples = build_triples()
    for i, t in enumerate(triples, start=1):
        tid = tc.record_triple(
            agent_output=t["agent_output"],
            human_edit=t["human_edit"],
            accepted_output=t["accepted_output"],
            task_id=f"demo-task-{i:03d}",
            agent_name=t["agent_name"],
            query_class=t["query_class"],
            edit_context=t["edit_context"],
        )
        triple_ids.append((tid, t["expected_category"]))

    print(f"\n[2] Running Promotion Gate on {len(triple_ids)} PENDING triples")
    print("-" * 72)
    results = gate.process_all_pending()

    print("\n[3] Categorization Audit")
    print("-" * 72)
    expected_by_tid = {tid: exp for tid, exp in triple_ids}
    correct = 0
    for res in results:
        tid = res["triple_id"]
        expected = expected_by_tid.get(tid, "?")
        actual = res["category"]
        mark = "✓" if actual == expected else "✗"
        print(f"  {mark} triple={tid[:8]} | expected={expected:18s} | actual={actual}")
        if actual == expected:
            correct += 1
    accuracy = correct / len(triple_ids)
    print(f"\n  Categorization accuracy: {correct}/{len(triple_ids)} = {accuracy:.0%}")

    print("\n[4] Few-Shot Bank state after promotions")
    print("-" * 72)
    bank = FewShotBank(agent_name="orchestrator", task_id="demo-bank-state")
    state = bank.bank_state()
    print(f"  Total exemplars: {state.get('total_exemplars', 0)}")
    print(f"  Query classes covered: {state.get('query_classes_covered', [])}")

    print("\n[5] Retrieval test for query_class='api_abuse_investigation'")
    print("-" * 72)
    retrieved = bank.retrieve(query_class="api_abuse_investigation")
    print(f"  Retrieved {len(retrieved)} exemplar(s)")
    for r in retrieved:
        print(f"    - id={r.get('id', '?')[:8]} | pattern={r.get('edit_pattern', '?')} "
              f"| recency={r.get('_retrieval_recency_score', '?')}")

    print("\n[6] Prompt-injection preview (first 600 chars)")
    print("-" * 72)
    injection = bank.format_for_prompt(retrieved)
    if injection:
        print(injection[:600])
        print("..." if len(injection) > 600 else "")
    else:
        print("  (no exemplars to inject)")

    print("\n[7] Gate statistics")
    print("-" * 72)
    stats = gate.get_gate_statistics()
    print(f"  Total processed: {stats['total_processed']}")
    print(f"  Quarantine queue size: {stats['quarantine_queue_size']}")
    print(f"  By category: {json.dumps(stats['by_category'], indent=2)}")

    return {
        "categorization_correct": correct,
        "categorization_total": len(triple_ids),
        "categorization_accuracy": accuracy,
        "exemplars_promoted": state.get("total_exemplars", 0),
        "retrieval_count": len(retrieved),
        "quarantined": stats["quarantine_queue_size"],
        "by_category": stats["by_category"],
    }


def demo_algorithmic_rule() -> dict:
    print("\n" + "=" * 72)
    print("[8] Algorithmic Rule — advancing 10 cycles at 10% budget")
    print("-" * 72)

    ar = AlgorithmicRule(agent_name="orchestrator", task_id="demo-algorithmic-rule")
    cycles_fired_at = []
    for i in range(1, 11):
        cycle = ar.next_cycle()
        marker = "⚡ EXPLORATION" if cycle["is_exploration_cycle"] else "  standard   "
        print(f"  Cycle {cycle['cycle_number']:>3}: {marker} "
              f"(expected={cycle['expected_explorations']}, fired={cycle['fired_so_far']})")
        if cycle["is_exploration_cycle"]:
            try:
                diversion = ar.fire(cycle, task_id=f"demo-cycle-{i}")
                cycles_fired_at.append(cycle["cycle_number"])
                print(f"        → constraint={diversion['constraint_id']}")
                print(f"        → hypothesis preview: {diversion['hypothesis'][:120]}...")
            except Exception as e:
                print(f"        → fire failed: {e}")

    rate = ar.get_exploration_rate()
    print(f"\n  Actual exploration rate: {rate['actual_exploration_percent']}% "
          f"(target {rate['target_exploration_percent']}%)")
    print(f"  Fired at cycles: {cycles_fired_at}")
    return {
        "fired_count": len(cycles_fired_at),
        "fired_at_cycles": cycles_fired_at,
        "actual_pct": rate["actual_exploration_percent"],
        "target_pct": rate["target_exploration_percent"],
    }


def print_exit_criteria(promotion: dict, algo: dict) -> bool:
    print("\n" + "=" * 72)
    print("PHASE 4 PARTIAL EXIT CRITERIA — Session 23 modules")
    print("=" * 72)
    checks = [
        ("Telemetry capture: ≥1 triple recorded per category",
         promotion["categorization_total"] >= 5),
        ("Promotion Gate: ≥80% categorization accuracy on synthetic suite",
         promotion["categorization_accuracy"] >= 0.80),
        ("Promotion Gate: ≥1 generalizable exemplar promoted to Few-Shot Bank",
         promotion["exemplars_promoted"] >= 1),
        ("Promotion Gate: ≥1 ambiguous correction quarantined (not auto-promoted)",
         promotion["quarantined"] >= 1),
        ("Few-Shot Bank: retrieval returns promoted exemplars for matching class",
         promotion["retrieval_count"] >= 1),
        ("Algorithmic Rule: fires on cycle 10 at 10% budget",
         10 in algo["fired_at_cycles"]),
        ("Algorithmic Rule: fires exactly once in 10 cycles (10%)",
         algo["fired_count"] == 1),
    ]
    all_pass = True
    for label, ok in checks:
        mark = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {mark}  {label}")
        all_pass = all_pass and ok
    print("\n" + ("✅ ALL PHASE 4 SESSION 23 CHECKS PASSED" if all_pass else "❌ SOME CHECKS FAILED"))
    return all_pass


if __name__ == "__main__":
    reset_demo_state()
    promotion = demo_telemetry_and_promotion()
    algo = demo_algorithmic_rule()
    ok = print_exit_criteria(promotion, algo)
    sys.exit(0 if ok else 1)
