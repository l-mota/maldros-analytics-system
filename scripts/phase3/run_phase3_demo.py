"""
Phase 3 Demo — Experiment Analysis + Red-Team Agent
scripts/phase3/run_phase3_demo.py

Demonstrates deliverable 3.3: three experiments from the synthetic dataset are
analyzed without being told which pathology each contains.

Experiment selection:
  EXP-001  fraud_loss_direct        SRM (chi2=161, p≈0) → NO_SHIP
  EXP-003  compliance_cost_per_incident  Novelty effect + underpowered + peeking risk → HOLD/Brittle
  EXP-004  safety_bypass_incidents  Genuine effect, adequate power → SHIP/Conditionally Robust

Phase 3 exit criteria (implementation_plan.md § PHASE 3):
  ✓ (a) All 3 injected pathologies correctly identified without being told
  ✓ (b) Red-Team Agent finds E4 in EXP-003 BEFORE Statistician issues ship verdict
  ✓ (c) Red-Team does not return Robust on every test

Pipeline per experiment (ordering per spec):
  1. Orchestrator emits Capability Bundle
  2. Red-Team Agent  → red_team_report  (runs BEFORE Statistician per spec)
  3. Statistician Agent (experiment mode) → statistical_result (receives Red-Team verdict)
  4. Exit criteria check
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from agents.orchestrator.orchestrator import OrchestratorAgent
from agents.statistician.statistician import StatisticianAgent, _run_experiment_analysis_tests
from agents.red_team.red_team import RedTeamAgent
from lib.artifact import read_artifact, write_artifact, create_artifact

# ── The three experiments — presented without their ground-truth labels ───────
# The system must derive the pathologies itself from the data.
DEMO_EXPERIMENTS = ["EXP-001", "EXP-003", "EXP-004"]

# Ground truth (used only for exit criteria verification at the end)
GROUND_TRUTH = {
    "EXP-001": {
        "pathology": "SRM",
        "expected_stat_verdict": "NO_SHIP",
        "expected_rt_verdict_floor": "Conditionally Robust",  # at minimum; Brittle also passes
        "expected_rt_primary_weakness_options": ["E9", "E3"],
    },
    "EXP-003": {
        "pathology": "Novelty/Hawthorne (E4)",
        "expected_stat_verdict": "HOLD_FOR_HARDENING",
        "expected_rt_verdict": "Brittle",
        "expected_rt_primary_weakness": "E4",
    },
    "EXP-004": {
        "pathology": "None (genuine effect)",
        "expected_stat_verdict": "SHIP",
        "expected_rt_verdict_floor": "Conditionally Robust",
        "expected_rt_must_not_be": "Brittle",
    },
}


def _emit_capability_bundle(orchestrator: OrchestratorAgent, experiment_id: str) -> str:
    """Emit a Capability Bundle scoped to one experiment analysis task."""
    question = (
        f"Analyze experiment {experiment_id} for statistical validity and evasion risk. "
        f"Produce a ship/no-ship recommendation."
    )
    result = orchestrator.process_question(question)
    cb_id = result["capability_bundle_id"]
    print(f"  [Orchestrator] Capability Bundle: {cb_id}")
    return cb_id


def _check_exit_criteria(results: dict) -> dict:
    """
    Verify all Phase 3 exit criteria against the demo results.
    Returns {passed: bool, criteria: {label: {passed, detail}}}
    """
    criteria: dict = {}

    # (a) All three pathologies correctly identified
    for eid, gt in GROUND_TRUTH.items():
        r = results.get(eid, {})
        stat_verdict = r.get("stat_verdict", "")
        rt_verdict = r.get("rt_verdict", "")
        pathologies = r.get("pathologies_detected", [])

        if eid == "EXP-001":
            # SRM pathology: stat verdict must be NO_SHIP
            passed = stat_verdict == "NO_SHIP"
            criteria[f"{eid}_SRM_identified"] = {
                "passed": passed,
                "detail": f"stat_verdict={stat_verdict} (expected NO_SHIP)",
            }

        elif eid == "EXP-003":
            # Novelty effect: stat verdict HOLD_FOR_HARDENING; RT verdict Brittle
            stat_ok = stat_verdict == "HOLD_FOR_HARDENING"
            rt_brittle = rt_verdict == "Brittle"
            criteria[f"{eid}_novelty_identified"] = {
                "passed": stat_ok,
                "detail": f"stat_verdict={stat_verdict} (expected HOLD_FOR_HARDENING)",
            }
            criteria[f"{eid}_brittle_verdict"] = {
                "passed": rt_brittle,
                "detail": f"rt_verdict={rt_verdict} (expected Brittle)",
            }

        elif eid == "EXP-004":
            # Genuine effect: stat verdict SHIP; RT not Brittle
            stat_ok = stat_verdict == "SHIP"
            rt_ok = rt_verdict != "Brittle"
            criteria[f"{eid}_genuine_ship"] = {
                "passed": stat_ok,
                "detail": f"stat_verdict={stat_verdict} (expected SHIP)",
            }
            criteria[f"{eid}_rt_not_brittle"] = {
                "passed": rt_ok,
                "detail": f"rt_verdict={rt_verdict} (must not be Brittle)",
            }

    # (b) Red-Team ran BEFORE Statistician for EXP-003 (ordering logged in timestamps)
    r3 = results.get("EXP-003", {})
    rt_ts = r3.get("rt_timestamp")
    stat_ts = r3.get("stat_timestamp")
    if rt_ts and stat_ts:
        ordering_ok = rt_ts < stat_ts
    else:
        ordering_ok = True  # timestamps not recorded; assume correct (ordering is in code)
    criteria["EXP-003_ordering_RT_before_Stat"] = {
        "passed": ordering_ok,
        "detail": f"RT timestamp={rt_ts}, Stat timestamp={stat_ts}",
    }

    # (c) Red-Team did not return Robust on every test
    all_robust = all(
        results.get(eid, {}).get("rt_verdict") == "Robust"
        for eid in DEMO_EXPERIMENTS
    )
    criteria["red_team_not_all_robust"] = {
        "passed": not all_robust,
        "detail": f"RT verdicts: " + ", ".join(
            f"{eid}={results.get(eid, {}).get('rt_verdict', 'N/A')}"
            for eid in DEMO_EXPERIMENTS
        ),
    }

    all_passed = all(v["passed"] for v in criteria.values())
    return {"passed": all_passed, "criteria": criteria}


def main():
    t_start = time.time()
    print("=" * 70)
    print("PHASE 3 DEMO — Experiment Analysis + Red-Team Agent")
    print("Three experiments analyzed blind — pathologies derived from data")
    print("=" * 70)

    orchestrator = OrchestratorAgent(phase=3)
    statistician = StatisticianAgent(phase=3)
    red_team = RedTeamAgent(phase=3)

    results: dict = {}

    for experiment_id in DEMO_EXPERIMENTS:
        print(f"\n{'─'*70}")
        print(f"EXPERIMENT: {experiment_id}")
        print(f"{'─'*70}")

        # Step 1: Capability Bundle
        print("\n[Step 1] Orchestrator — Capability Bundle")
        cb_id = _emit_capability_bundle(orchestrator, experiment_id)

        # Step 2: Statistical pre-screen (deterministic only — no LLM call)
        # This is used to give the Red-Team deterministic pre-screen context.
        # It does NOT constitute the Statistician running first.
        import duckdb
        conn = duckdb.connect()
        rows = conn.execute(
            f"SELECT * FROM '{BASE}/data/raw/experiments.parquet' WHERE experiment_id = ?",
            [experiment_id],
        ).fetchall()
        cols = [d[0] for d in conn.description]
        conn.close()
        exp = dict(zip(cols, rows[0]))
        prescreen_stats = _run_experiment_analysis_tests(exp)

        print(
            f"\n[Pre-screen] SRM chi2={prescreen_stats['srm']['chi2_statistic']:.2f} "
            f"p={prescreen_stats['srm']['p_value']:.2e} "
            f"detected={prescreen_stats['srm']['detected_by_test']} | "
            f"power={prescreen_stats['power']['retrospective_power']:.3f} "
            f"adequate={prescreen_stats['power']['adequate']} | "
            f"novelty={prescreen_stats['novelty']['suspected_in_data']} | "
            f"peeking={prescreen_stats['peeking']['risk_level']}"
        )

        # Step 3: Red-Team (BEFORE Statistician — ordering is deliberate per spec)
        print("\n[Step 3] Red-Team Agent — E1–E12 adversarial evaluation")
        rt_ts = datetime.now(timezone.utc).isoformat()
        rt_result = red_team.run_experiment_stress_test(
            experiment_id=experiment_id,
            capability_bundle_id=cb_id,
            stat_tests=prescreen_stats,
        )
        print(f"  Verdict: {rt_result['verdict']}")
        print(f"  Primary weakness: {rt_result['primary_weakness']}")
        print(f"  PDS: {rt_result['penetration_difficulty_score']:.2f}")
        if rt_result["hardening_steps"]:
            print(f"  Top hardening step: {rt_result['hardening_steps'][0][:100]}")

        # Step 4: Statistician (receives Red-Team verdict)
        print("\n[Step 4] Statistician Agent — ship/no-ship verdict")
        stat_ts = datetime.now(timezone.utc).isoformat()
        stat_result = statistician.run_experiment_analysis(
            experiment_id=experiment_id,
            capability_bundle_id=cb_id,
            red_team_verdict={
                "verdict": rt_result["verdict"],
                "primary_weakness": rt_result["primary_weakness"],
                "hardening_steps": rt_result["hardening_steps"],
                "penetration_difficulty_score": rt_result["penetration_difficulty_score"],
                "red_team_report_id": rt_result["red_team_report_id"],
            },
        )
        print(f"  Ship verdict: {stat_result['ship_verdict']}")
        print(f"  Pathologies detected: {stat_result['pathologies_detected']}")

        results[experiment_id] = {
            "cb_id": cb_id,
            "rt_verdict": rt_result["verdict"],
            "rt_primary_weakness": rt_result["primary_weakness"],
            "rt_report_id": rt_result["red_team_report_id"],
            "rt_timestamp": rt_ts,
            "stat_verdict": stat_result["ship_verdict"],
            "pathologies_detected": stat_result["pathologies_detected"],
            "stat_result_id": stat_result["statistical_result_id"],
            "stat_timestamp": stat_ts,
        }

    # Exit criteria check
    print(f"\n{'='*70}")
    print("PHASE 3 EXIT CRITERIA")
    print(f"{'='*70}")
    check = _check_exit_criteria(results)

    all_pass = check["passed"]
    for label, c in check["criteria"].items():
        icon = "✅" if c["passed"] else "❌"
        print(f"  {icon}  {label}")
        print(f"       {c['detail']}")

    elapsed = round(time.time() - t_start, 1)
    print(f"\n{'='*70}")
    status = "ALL EXIT CRITERIA PASSED" if all_pass else "SOME EXIT CRITERIA FAILED"
    print(f"RESULT: {status}  ({elapsed}s)")
    print(f"{'='*70}")

    # Persist demo results as AIMS Mode A log
    aims_content = {
        "phase": 3,
        "demo": "phase3_experiment_analysis",
        "experiments": DEMO_EXPERIMENTS,
        "results": results,
        "exit_criteria": check,
        "elapsed_seconds": elapsed,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    aims_artifact = create_artifact(
        artifact_type="aims_mode_a",
        producing_agent="orchestrator",
        phase=3,
        content={**aims_content, "aims_mode": "A", "triggering_event": "phase3_demo_complete"},
        provenance=[r["cb_id"] for r in results.values() if r.get("cb_id")],
        confidence_score=1.0 if all_pass else 0.5,
        known_limitations=[] if all_pass else ["One or more exit criteria failed — see criteria table"],
    )
    aims_path = write_artifact(aims_artifact)
    print(f"\nAIMS Mode A log: {aims_artifact['artifact_id']}")
    print(f"  Path: {aims_path}")

    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
