"""
scripts/phase5/run_phase5_demo.py

Phase 5 demo — The Forge.

Problem statement:
  "The current API abuse detection approach (volume thresholds + account clustering)
   misses slow-burn coordinated campaigns that spread activity across many accounts
   below individual thresholds. Design a novel detection approach."

Expected pipeline outcome:
  - Generation mode: FIRST_PRINCIPLES (novel problem; no high-similarity Second Brain prior)
  - Derivation: percolation threshold monitoring on account behavioral graph
  - Red-Team verdict: Conditionally Robust
    (E1 — mimicking organic network growth is the primary weakness, but adversary cost is HIGH)
  - Pre-Screen Gate: PROMOTED → SHADOW tier
  - All 13 IPR assets present

Phase 5 exit criterion (implementation_plan.md §5):
  "The Forge produces a novel detection framework (not a refinement) that passes the
   Red-Team stress test with a Conditionally Robust verdict. The Invention Pipeline
   Report meets all 13 required asset specifications."

Run:
  $env:PYTHONUTF8 = "1"
  $env:ANTHROPIC_API_KEY = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
  python scripts/phase5/run_phase5_demo.py
"""
import sys
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.artifact import create_artifact, write_artifact
from agents.forge.forge import ForgeAgent

# ─── Problem statement (verbatim from specification) ─────────────────────────

PROBLEM_STATEMENT = (
    "The current API abuse detection approach (volume thresholds + account clustering) "
    "misses slow-burn coordinated campaigns that spread activity across many accounts "
    "below individual thresholds. Design a novel detection approach."
)


def create_forge_capability_bundle(task_id: str) -> str:
    """
    Create a synthetic Capability Bundle for the Phase 5 Forge task.
    In a full pipeline run, the Orchestrator emits this before any agent begins.
    """
    cb = create_artifact(
        artifact_type="capability_bundle",
        producing_agent="orchestrator",
        phase=5,
        content={
            "task_id": task_id,
            "task_description": PROBLEM_STATEMENT,
            "cdi_query_timestamp": datetime.now(timezone.utc).isoformat(),
            "active_reasoning_modes": [
                "FIRST_PRINCIPLES", "ADVERSARIAL_GAME_TREES", "CROSS_DOMAIN_ANALOGY"
            ],
            "capabilities_met": [
                "Graph-based behavioral analysis (CDI XDA_011–XDA_015)",
                "Adversarial game tree reasoning (CDI reasoning_frameworks)",
                "Cross-domain analogues: epidemiological SEIR, network percolation theory",
            ],
            "capabilities_not_met": [],
            "cdi_lineage_trace": {
                "domains_queried": [
                    "reasoning_frameworks", "cross_domain_analogues",
                    "second_brain_signal", "exemplar_surface"
                ],
                "key_findings": [
                    "No high-similarity prior in Second Brain for slow-burn graph detection",
                    "Cross-domain analogue: percolation theory from condensed matter physics",
                    "Adversarial game tree mode activated for detection framework design",
                ],
                "alternative_approaches_surfaced": [
                    "Network percolation threshold monitoring",
                    "Behavioral entropy gradient across account graph edges",
                    "Temporal graph evolution via SEIR-inspired compartmental model",
                ],
            },
            "l1_veto_state": {
                "nominal": True,
                "active_vetoes": [],
            },
            "second_brain_similarity_score": 0.12,
            "decomposition": {
                "tasks": [
                    {
                        "agent": "forge",
                        "description": "Generate novel detection framework via FIRST_PRINCIPLES derivation",
                    }
                ]
            },
            "algorithmic_rule": {
                "cycle_number": 11,
                "is_exploration_cycle": True,
                "exploration_percent": 10.0,
                "cycles_until_next_exploration": 10,
                "diversion": {
                    "triggered": True,
                    "constraint_id": "CR-007",
                    "counter_intuitive_hypothesis": (
                        "Small coordinated clusters produce significant financial exposure "
                        "while remaining invisible to population-level rate monitors. "
                        "Graph-topology signals may detect them below volume thresholds."
                    ),
                },
            },
        },
        provenance=[],
        confidence_score=0.95,
        known_limitations=[
            "Synthetic Capability Bundle for Phase 5 demo — production version emitted by Orchestrator"
        ],
    )
    path = write_artifact(cb)
    print(f"[Demo] Capability Bundle: {cb['artifact_id']}")
    return cb["artifact_id"]


def check_exit_criteria(result: dict, ipr: dict) -> list[dict]:
    """
    Verify Phase 5 exit criteria against the completed IPR.

    Exit criterion (implementation_plan.md §5):
      1. Novel detection framework produced (not a refinement)
      2. Red-Team verdict: Conditionally Robust or Robust (not Brittle)
      3. All 13 IPR assets present in the artifact
    """
    c = ipr.get("content", {})
    criteria = []

    # Criterion 1: Novel framework (not incremental refinement)
    is_novel = c.get("is_novel", False)
    typology = c.get("novel_invention_typology", "incremental_refinement")
    criteria.append({
        "criterion": "Novel detection framework produced",
        "expected": "is_novel=True and typology ≠ incremental_refinement",
        "actual": f"is_novel={is_novel}, typology={typology}",
        "pass": is_novel and typology != "incremental_refinement",
    })

    # Criterion 2: Red-Team verdict not Brittle
    verdict = c.get("red_team_verdict", "Brittle")
    criteria.append({
        "criterion": "Red-Team verdict: Conditionally Robust or Robust",
        "expected": "Conditionally Robust or Robust",
        "actual": verdict,
        "pass": verdict in ("Conditionally Robust", "Robust"),
    })

    # Criterion 3: All 13 IPR assets present
    required_assets = [
        "problem_framing",         # Asset 1
        "generation_mode",         # Asset 2
        "is_novel",                # Asset 3a
        "novel_invention_typology",# Asset 3b
        "proposed_framework",      # Asset 4
        "derivation_chain",        # Asset 5
        "red_team_verdict",        # Asset 6
        "statistical_pre_validation",  # Asset 7
        "cost_model",              # Asset 8
        "pre_screen_gate_outcome", # Asset 9
        "recommended_deployment_tier", # Asset 10
        "cross_references",        # Asset 11
        "lineage_trace",           # Asset 12
    ]
    # Asset 13: known_limitations is in the artifact envelope
    has_limitations = bool(ipr.get("known_limitations"))
    present = [a for a in required_assets if c.get(a) is not None]
    missing = [a for a in required_assets if c.get(a) is None]

    criteria.append({
        "criterion": "All 13 IPR assets present",
        "expected": "13/13",
        "actual": f"{len(present) + (1 if has_limitations else 0)}/13"
                  + (f" (missing: {missing})" if missing else "")
                  + ("" if has_limitations else " [known_limitations missing from envelope]"),
        "pass": len(missing) == 0 and has_limitations,
    })

    # Criterion 4: Pre-Screen Gate outcome
    gate_outcome = c.get("pre_screen_gate_outcome", "UNKNOWN")
    criteria.append({
        "criterion": "Pre-Screen Gate outcome: PROMOTED or PARKED (not REJECTED)",
        "expected": "PROMOTED",
        "actual": gate_outcome,
        "pass": gate_outcome in ("PROMOTED", "PARKED"),
    })

    return criteria


def main():
    print("=" * 70)
    print("  PHASE 5 DEMO — The Forge")
    print("=" * 70)
    print(f"\nProblem:\n  {PROBLEM_STATEMENT}\n")

    # ── Create Capability Bundle ──────────────────────────────────────────────
    task_id = f"phase5_forge_{uuid.uuid4().hex[:8]}"
    print(f"[Demo] Task ID: {task_id}")
    cb_id = create_forge_capability_bundle(task_id)

    # ── Run Forge invention cycle ─────────────────────────────────────────────
    forge = ForgeAgent(phase=5)
    result = forge.run_invention_cycle(
        problem_statement=PROBLEM_STATEMENT,
        capability_bundle_id=cb_id,
        trigger="algorithmic_rule_exploration",
    )

    # ── Load IPR artifact for exit criteria check ─────────────────────────────
    from lib.artifact import read_artifact
    ipr = read_artifact(result["ipr_artifact_id"])

    # ── Exit criteria evaluation ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PHASE 5 EXIT CRITERIA")
    print("=" * 70)

    criteria = check_exit_criteria(result, ipr)
    all_pass = all(c["pass"] for c in criteria)

    for c in criteria:
        status = "✅ PASS" if c["pass"] else "❌ FAIL"
        print(f"\n  {status}  {c['criterion']}")
        print(f"         Expected: {c['expected']}")
        print(f"         Actual:   {c['actual']}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"\n  Framework:        {result.get('framework_name', 'N/A')}")
    print(f"  Generation mode:  {result.get('gen_mode', 'N/A')} (DI #7)")
    print(f"  Novel:            {result.get('is_novel', False)} ({result.get('novel_typology', 'N/A')})")
    print(f"  Red-Team verdict: {result.get('verdict', 'N/A')}")
    print(f"  Primary weakness: {result.get('primary_weakness', 'N/A')}")
    print(f"  Gate outcome:     {result.get('gate_outcome', 'N/A')}")
    print(f"  Deployment tier:  {result.get('recommended_deployment_tier', 'N/A')}")
    print(f"  Derivation steps: {result.get('derivation_steps', 0)}")
    print(f"  PDS:              {result.get('penetration_difficulty_score', 0):.2f}")
    print(f"\n  IPR artifact:     {result.get('ipr_artifact_id', 'N/A')}")
    print(f"  AIMS Mode A:      {result.get('aims_mode_a_id', 'N/A')[:8]}")

    hardening = result.get("hardening_steps", [])
    if hardening:
        print(f"\n  Hardening steps ({len(hardening)}):")
        for h in hardening[:3]:
            print(f"    - {h}")

    print("\n" + "=" * 70)
    final = "  ✅ PHASE 5 EXIT CRITERIA PASSED" if all_pass else "  ❌ PHASE 5 EXIT CRITERIA FAILED"
    print(final)
    print("=" * 70 + "\n")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
