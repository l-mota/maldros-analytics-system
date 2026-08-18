"""
Phase 1 — Run Investigation
scripts/phase1/run_investigation.py

Sequences the full Phase 1 agent pipeline:
  Orchestrator → Analyst → Statistician → Storyteller

Investigation question (fixed per implementation_plan.md):
  "Is the spike in API abuse volume in Q1 of the synthetic dataset driven by
   coordinated multi-account behavior, or is it organic growth? If coordinated,
   what is the estimated financial impact and what countermeasure is indicated?"

Usage:
    $env:ANTHROPIC_API_KEY = "<your-api-key>"
    python scripts/phase1/run_investigation.py

Output artifacts written to:
    artifacts/capability_bundle/
    artifacts/context_bundle/
    artifacts/evidence_bundle/
    artifacts/statistical_result/
    artifacts/discovery_report/
    artifacts/aims_mode_b/
    aims/mode_b/<task_id>_mode_b.json

AIMS Mode A log entries written to:
    aims/mode_a/llm_call_log.jsonl
    aims/mode_a/phase1_investigation.jsonl
"""
import sys
import os
import json
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

# Check ANTHROPIC_API_KEY before doing anything else
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("\nERROR: ANTHROPIC_API_KEY environment variable not set.")
    print("Set it with: $env:ANTHROPIC_API_KEY = '<your-api-key>'")
    print("Then re-run: python scripts/phase1/run_investigation.py")
    sys.exit(1)

from agents.orchestrator.orchestrator import OrchestratorAgent
from agents.analyst.analyst import AnalystAgent
from agents.statistician.statistician import StatisticianAgent
from agents.storyteller.storyteller import StorytellerAgent

AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)

PHASE1_QUESTION = (
    "Is the spike in API abuse volume in Q1 of the synthetic dataset driven by "
    "coordinated multi-account behavior, or is it organic growth? If coordinated, "
    "what is the estimated financial impact and what countermeasure is indicated?"
)


def log_phase1_aims(entry: dict) -> None:
    log_file = AIMS_MODE_A_DIR / "phase1_investigation.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def run_investigation(question: str = PHASE1_QUESTION) -> dict:
    run_id = str(uuid.uuid4())
    t_start = time.time()

    print("\n" + "=" * 70)
    print("MALDROS — PHASE 1 INVESTIGATION")
    print("=" * 70)
    print(f"Run ID: {run_id}")
    print(f"Question: {question}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    log_phase1_aims({
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": "PHASE1_INVESTIGATION_STARTED",
        "run_id": run_id,
        "question": question,
        "phase": 1,
    })

    results = {"run_id": run_id, "question": question, "phase": 1}

    # ── Step 1: Orchestrator ────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("STEP 1: ORCHESTRATOR")
    print("─" * 70)
    t_orch = time.time()
    try:
        orchestrator = OrchestratorAgent(phase=1)
        orch_result = orchestrator.process_question(question)
        results["orchestrator"] = orch_result
        results["capability_bundle_id"] = orch_result["capability_bundle_id"]
        results["context_bundle_id"] = orch_result["context_bundle_id"]
        print(f"\n[Runner] Orchestrator complete in {round(time.time() - t_orch, 1)}s")
        print(f"[Runner] Capability Bundle: {orch_result['capability_bundle_id']}")
        print(f"[Runner] Context Bundle: {orch_result['context_bundle_id']}")

        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "ORCHESTRATOR_COMPLETE",
            "run_id": run_id,
            "capability_bundle_id": orch_result["capability_bundle_id"],
            "context_bundle_id": orch_result["context_bundle_id"],
            "elapsed_sec": round(time.time() - t_orch, 2),
        })

    except Exception as e:
        print(f"\n[Runner] ORCHESTRATOR FAILED: {e}")
        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "ORCHESTRATOR_FAILED",
            "run_id": run_id,
            "error": str(e),
        })
        raise

    # ── Step 2: Analyst ─────────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("STEP 2: ANALYST AGENT")
    print("─" * 70)
    t_analyst = time.time()
    try:
        analyst = AnalystAgent(phase=1)
        analyst_result = analyst.run(
            capability_bundle_id=results["capability_bundle_id"],
            context_bundle_id=results["context_bundle_id"],
        )
        results["analyst"] = analyst_result
        results["evidence_bundle_id"] = analyst_result["evidence_bundle_id"]
        print(f"\n[Runner] Analyst complete in {round(time.time() - t_analyst, 1)}s")
        print(f"[Runner] Evidence Bundle: {analyst_result['evidence_bundle_id']}")
        print(f"[Runner] Conclusion: {analyst_result['conclusion']} (confidence={analyst_result['confidence']:.2f})")

        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "ANALYST_COMPLETE",
            "run_id": run_id,
            "evidence_bundle_id": analyst_result["evidence_bundle_id"],
            "conclusion": analyst_result.get("conclusion"),
            "confidence": analyst_result.get("confidence"),
            "elapsed_sec": round(time.time() - t_analyst, 2),
        })

    except Exception as e:
        print(f"\n[Runner] ANALYST FAILED: {e}")
        import traceback; traceback.print_exc()
        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "ANALYST_FAILED",
            "run_id": run_id,
            "error": str(e),
        })
        raise

    # ── Step 3: Statistician ─────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("STEP 3: STATISTICIAN AGENT")
    print("─" * 70)
    t_stat = time.time()
    try:
        statistician = StatisticianAgent(phase=1)
        stat_result = statistician.run(
            capability_bundle_id=results["capability_bundle_id"],
            evidence_bundle_id=results["evidence_bundle_id"],
        )
        results["statistician"] = stat_result
        results["statistical_result_id"] = stat_result["statistical_result_id"]
        print(f"\n[Runner] Statistician complete in {round(time.time() - t_stat, 1)}s")
        print(f"[Runner] Statistical Result: {stat_result['statistical_result_id']}")
        print(f"[Runner] Verdict: {stat_result['verdict']} (confidence={stat_result['confidence']:.2f})")

        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "STATISTICIAN_COMPLETE",
            "run_id": run_id,
            "statistical_result_id": stat_result["statistical_result_id"],
            "verdict": stat_result.get("verdict"),
            "confidence": stat_result.get("confidence"),
            "elapsed_sec": round(time.time() - t_stat, 2),
        })

    except Exception as e:
        print(f"\n[Runner] STATISTICIAN FAILED: {e}")
        import traceback; traceback.print_exc()
        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "STATISTICIAN_FAILED",
            "run_id": run_id,
            "error": str(e),
        })
        raise

    # ── Step 4: Storyteller ──────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("STEP 4: STORYTELLER AGENT")
    print("─" * 70)
    t_story = time.time()
    try:
        storyteller = StorytellerAgent(phase=1)
        story_result = storyteller.run(
            capability_bundle_id=results["capability_bundle_id"],
            statistical_result_id=results["statistical_result_id"],
            evidence_bundle_id=results["evidence_bundle_id"],
        )
        results["storyteller"] = story_result
        results["discovery_report_id"] = story_result["discovery_report_id"]
        results["aims_mode_b_id"] = story_result["aims_mode_b_id"]
        print(f"\n[Runner] Storyteller complete in {round(time.time() - t_story, 1)}s")
        print(f"[Runner] Discovery Report: {story_result['discovery_report_id']}")
        print(f"[Runner] AIMS Mode B: {story_result['aims_mode_b_id']}")
        print(f"[Runner] L1 checks passed: {story_result['l1_passed']}")

        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "STORYTELLER_COMPLETE",
            "run_id": run_id,
            "discovery_report_id": story_result["discovery_report_id"],
            "aims_mode_b_id": story_result["aims_mode_b_id"],
            "l1_passed": story_result["l1_passed"],
            "blocked": story_result["blocked"],
            "elapsed_sec": round(time.time() - t_story, 2),
        })

    except Exception as e:
        print(f"\n[Runner] STORYTELLER FAILED: {e}")
        import traceback; traceback.print_exc()
        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "STORYTELLER_FAILED",
            "run_id": run_id,
            "error": str(e),
        })
        raise

    # ── Summary ──────────────────────────────────────────────────────────────────
    total_elapsed = round(time.time() - t_start, 1)
    print("\n" + "=" * 70)
    print("PHASE 1 INVESTIGATION COMPLETE")
    print("=" * 70)
    print(f"Total elapsed: {total_elapsed}s")
    print(f"")
    print(f"Artifacts produced:")
    print(f"  Capability Bundle : {results.get('capability_bundle_id', 'N/A')}")
    print(f"  Context Bundle    : {results.get('context_bundle_id', 'N/A')}")
    print(f"  Evidence Bundle   : {results.get('evidence_bundle_id', 'N/A')}")
    print(f"  Statistical Result: {results.get('statistical_result_id', 'N/A')}")
    print(f"  Discovery Report  : {results.get('discovery_report_id', 'N/A')}")
    print(f"  AIMS Mode B       : {results.get('aims_mode_b_id', 'N/A')}")
    print(f"")
    print(f"Analyst conclusion: {results['analyst'].get('conclusion', 'N/A')}")
    print(f"Statistician verdict: {results['statistician'].get('verdict', 'N/A')}")
    print(f"L1 checks passed: {results['storyteller'].get('l1_passed', False)}")
    print(f"")
    print(f"AIMS Mode B briefing: aims/mode_b/<task_id>_mode_b.json")
    print(f"Review Queue: open operator_ui_mockup.html → Review Queue dashboard")
    print("=" * 70)

    results["total_elapsed_sec"] = total_elapsed

    log_phase1_aims({
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": "PHASE1_INVESTIGATION_COMPLETE",
        "run_id": run_id,
        "analyst_conclusion": results["analyst"].get("conclusion"),
        "statistician_verdict": results["statistician"].get("verdict"),
        "l1_passed": results["storyteller"].get("l1_passed"),
        "blocked": results["storyteller"].get("blocked"),
        "discovery_report_id": results.get("discovery_report_id"),
        "aims_mode_b_id": results.get("aims_mode_b_id"),
        "total_elapsed_sec": total_elapsed,
        "phase": 1,
    })

    return results


def run_storyteller_only(
    capability_bundle_id: str,
    evidence_bundle_id: str,
    statistical_result_id: str,
) -> dict:
    """
    Run only the Storyteller agent on existing artifacts.

    Use this to re-run output generation after fixing L1 veto issues without
    re-running the full pipeline (Orchestrator + Analyst + Statistician).

    Usage:
        python scripts/phase1/run_investigation.py --storyteller-only \
            --capability-bundle-id <id> \
            --evidence-bundle-id <id> \
            --statistical-result-id <id>
    """
    run_id = str(uuid.uuid4())
    t_start = time.time()

    print("\n" + "=" * 70)
    print("MALDROS — STORYTELLER-ONLY RE-RUN")
    print("=" * 70)
    print(f"Run ID      : {run_id}")
    print(f"CB          : {capability_bundle_id}")
    print(f"EB          : {evidence_bundle_id}")
    print(f"SR          : {statistical_result_id}")
    print(f"Started     : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    log_phase1_aims({
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": "STORYTELLER_ONLY_RUN_STARTED",
        "run_id": run_id,
        "capability_bundle_id": capability_bundle_id,
        "evidence_bundle_id": evidence_bundle_id,
        "statistical_result_id": statistical_result_id,
        "phase": 1,
    })

    print("\n" + "─" * 70)
    print("STEP 4 (re-run): STORYTELLER AGENT")
    print("─" * 70)

    try:
        storyteller = StorytellerAgent(phase=1)
        story_result = storyteller.run(
            capability_bundle_id=capability_bundle_id,
            statistical_result_id=statistical_result_id,
            evidence_bundle_id=evidence_bundle_id,
        )
    except Exception as e:
        print(f"\n[Runner] STORYTELLER FAILED: {e}")
        import traceback; traceback.print_exc()
        log_phase1_aims({
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "STORYTELLER_ONLY_RUN_FAILED",
            "run_id": run_id,
            "error": str(e),
        })
        raise

    total_elapsed = round(time.time() - t_start, 1)

    print("\n" + "=" * 70)
    print("STORYTELLER RE-RUN COMPLETE")
    print("=" * 70)
    print(f"Total elapsed     : {total_elapsed}s")
    print(f"Discovery Report  : {story_result['discovery_report_id']}")
    print(f"AIMS Mode B       : {story_result['aims_mode_b_id']}")
    print(f"L1 checks passed  : {story_result['l1_passed']}")
    if story_result['blocked']:
        print(f"  Causal check     : {'PASS' if story_result['causal_check_passed'] else 'FAIL'}")
        print(f"  Citation check   : {'PASS' if story_result['citation_check_passed'] else 'FAIL'}")
        print(f"  Omission check   : {'PASS' if story_result['omission_check_passed'] else 'FAIL'}")
        print(f"  C-020 exec layer : {'PASS' if story_result.get('c020_executive_layer_passed') else 'FAIL'}")
        print(f"  C-020 readiness  : {'PASS' if story_result.get('c020_readiness_passed') else 'FAIL'}")
        criteria = story_result.get('c020_readiness_criteria', {}) or {}
        for k, v in criteria.items():
            print(f"    {k}: {'PASS' if v else 'FAIL'}")
    print(f"")
    print(f"AIMS Mode B file  : aims/mode_b/<task_id>_mode_b.json")
    print("=" * 70)

    log_phase1_aims({
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": "STORYTELLER_ONLY_RUN_COMPLETE",
        "run_id": run_id,
        "discovery_report_id": story_result["discovery_report_id"],
        "aims_mode_b_id": story_result["aims_mode_b_id"],
        "l1_passed": story_result["l1_passed"],
        "blocked": story_result["blocked"],
        "elapsed_sec": total_elapsed,
        "phase": 1,
    })

    return story_result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Maldros Phase 1 Investigation Runner")
    parser.add_argument(
        "--storyteller-only",
        action="store_true",
        help="Run only the Storyteller agent using existing artifacts (skip Orchestrator/Analyst/Statistician)",
    )
    parser.add_argument(
        "--capability-bundle-id",
        type=str,
        help="Capability Bundle artifact ID (required with --storyteller-only)",
    )
    parser.add_argument(
        "--evidence-bundle-id",
        type=str,
        help="Evidence Bundle artifact ID (required with --storyteller-only)",
    )
    parser.add_argument(
        "--statistical-result-id",
        type=str,
        help="Statistical Result artifact ID (required with --storyteller-only)",
    )
    args = parser.parse_args()

    if args.storyteller_only:
        missing = []
        if not args.capability_bundle_id:
            missing.append("--capability-bundle-id")
        if not args.evidence_bundle_id:
            missing.append("--evidence-bundle-id")
        if not args.statistical_result_id:
            missing.append("--statistical-result-id")
        if missing:
            print(f"\nERROR: --storyteller-only requires: {', '.join(missing)}")
            print("\nExample:")
            print("  python scripts/phase1/run_investigation.py --storyteller-only \\")
            print("    --capability-bundle-id a15c92f8-8555-493b-a3c5-ade0f491cf04 \\")
            print("    --evidence-bundle-id   1bcf87a6-1f55-4cd9-9f13-4a78aa7f3b10 \\")
            print("    --statistical-result-id c26f19d3-d516-4600-9c24-8eff8a46ad03")
            sys.exit(1)
        run_storyteller_only(
            capability_bundle_id=args.capability_bundle_id,
            evidence_bundle_id=args.evidence_bundle_id,
            statistical_result_id=args.statistical_result_id,
        )
    else:
        run_investigation()
