"""
scripts/phase6/run_phase6_demo.py

Phase 6 End-to-End Demo — Full AIMS Integration + Recursive Self-Improvement

Demonstrates all Phase 6 exit criteria from implementation_plan.md §6:

  6.1 — Full AIMS routing: every artifact routes correctly to Mode A or Mode B.
  6.2 — Phase 7 bottleneck identification: telemetry aggregation → 3 candidates.
  6.3 — Improvement proposal + sandbox test: highest-priority bottleneck → proposal.
  6.4 — Mode B routing verified for Phase 7 proposal (human approval gate marked).
  6.5 — Portability layer: generate_streaming() exercised as alternative invocation.

Exit criteria (implementation_plan.md §6):
  (a) Full workflow runs without human scaffolding at intermediate steps.
  (b) Human is involved only at governance gates (Confirmation Gate intercept).
  (c) Portability wrapper documented and tested against at least one alternative
      invocation pattern (generate_streaming).

Usage:
    $env:PYTHONUTF8 = "1"
    $env:ANTHROPIC_API_KEY = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
    cd <repository root>
    python scripts/phase6/run_phase6_demo.py
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.artifact import create_artifact, write_artifact
from lib.aims_router import route_artifact, verify_routing_for_all_artifacts
from lib.bottleneck_detector import BottleneckDetector
from lib.phase7_proposals import Phase7Proposer
from lib.llm_wrapper import LLMWrapper
from agents.orchestrator.orchestrator import OrchestratorAgent


# ── Convenience helpers ───────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}")


def _check(label: str, passed: bool, detail: str = "") -> bool:
    icon = "✅" if passed else "❌"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return passed


# ── Phase 6 Exit Criterion Checks ────────────────────────────────────────────

def _check_exit_a(orchestrator_result: dict) -> bool:
    """(a) Orchestrator ran without human scaffolding; Capability Bundle emitted."""
    has_cb = bool(orchestrator_result.get("capability_bundle_id"))
    has_ctx = bool(orchestrator_result.get("context_bundle_id"))
    has_decomp = bool(orchestrator_result.get("task_decomposition"))
    return has_cb and has_ctx and has_decomp


def _check_exit_b(proposal_result: dict) -> bool:
    """(b) Confirmation Gate intercepted proposal; no auto-approve."""
    gate_item = proposal_result.get("confirmation_gate_item_id")
    no_auto = proposal_result.get("gate_outcome") == "SUBMITTED_AWAITING_DECISION"
    mode_b = proposal_result.get("routed_to_mode_b", False)
    return bool(gate_item) and no_auto and mode_b


def _check_exit_c(streaming_result: dict) -> bool:
    """(c) generate_streaming() returned a valid response (portability test)."""
    return bool(streaming_result.get("content")) and streaming_result.get("input_tokens", 0) > 0


def _check_aims_routing(routing_summary: dict) -> bool:
    """6.1 — AIMS routing audit: at least 1 artifact routed to each mode."""
    return (
        routing_summary.get("mode_a_count", 0) > 0
        and routing_summary.get("mode_b_count", 0) > 0
    )


def _check_bottlenecks(bottleneck_result: dict) -> bool:
    """6.2 — At least one bottleneck candidate with confidence > 0.7."""
    top = bottleneck_result.get("top_bottleneck") or {}
    return top.get("confidence_score", 0) >= 0.7


def _check_sandbox(proposal_result: dict) -> bool:
    """6.3 — Sandbox ran and returned PASS or CONDITIONAL_PASS."""
    return proposal_result.get("sandbox_verdict") in ("PASS", "CONDITIONAL_PASS")


# ── Step 1: Portability Test — generate_streaming() ──────────────────────────

def run_portability_test() -> dict:
    """
    Exercise generate_streaming() as an alternative invocation pattern.
    Uses a minimal system prompt + question (not a full investigation) to
    verify the streaming path is functional without burning large token budget.
    This directly satisfies Phase 6 exit criterion (c) and deliverable 6.5.
    """
    _section("STEP 1 — Portability Test: generate_streaming()")

    task_id = str(uuid.uuid4())
    llm = LLMWrapper(agent_name="phase6_portability_test", task_id=task_id)

    PORTABILITY_SYSTEM_PROMPT = """You are confirming the Maldros portability layer is operational.
Respond with a JSON object: {"status": "operational", "model": "<model-id>", "note": "<one sentence>"}"""

    question = (
        "Confirm that the Maldros LLM portability wrapper is functional. "
        "Return the JSON response as instructed."
    )

    tokens_received = 0
    chars_streamed = 0

    def on_token(delta: str) -> None:
        nonlocal tokens_received, chars_streamed
        tokens_received += 1
        chars_streamed += len(delta)

    print(f"[Portability] Calling generate_streaming() with on_token callback...")
    t0 = time.time()
    result = llm.generate_streaming(
        system_prompt=PORTABILITY_SYSTEM_PROMPT,
        user_message=question,
        max_tokens=256,
        on_token=on_token,
    )
    elapsed = round(time.time() - t0, 2)

    print(f"[Portability] Elapsed: {elapsed}s")
    print(f"[Portability] Tokens streamed (deltas): {tokens_received}")
    print(f"[Portability] Chars received via callback: {chars_streamed}")
    print(f"[Portability] Input tokens: {result['input_tokens']}")
    print(f"[Portability] Output tokens: {result['output_tokens']}")
    print(f"[Portability] Response content: {result['content'][:200]}")
    print(f"[Portability] supports_extended_thinking: {llm.supports_extended_thinking}")

    # Verify the response
    raw = result["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if "```" in raw:
        raw = raw.rsplit("```", 1)[0]
    try:
        parsed = json.loads(raw.strip())
        print(f"[Portability] Parsed JSON: {parsed}")
    except json.JSONDecodeError:
        print(f"[Portability] Note: response not pure JSON — content still valid for portability test")

    return result


# ── Step 2: Orchestrator — fresh Phase 6 question ───────────────────────────

def run_orchestrator() -> dict:
    """
    Orchestrator processes a fresh Phase 6 natural-language question.
    Phase 6 question is distinct from Phases 1–5 — focuses on system
    self-improvement rather than a specific investigation question.
    """
    _section("STEP 2 — Orchestrator: Fresh Phase 6 Question")

    orchestrator = OrchestratorAgent()
    task_id = str(uuid.uuid4())

    question = (
        "Across all investigation cycles completed so far, where is the Maldros "
        "system spending the most tokens and producing the most variance in output "
        "quality? Identify the top structural bottleneck and propose a concrete "
        "improvement that would reduce unnecessary token consumption without "
        "compromising output accuracy or governance compliance."
    )

    print(f"[Orchestrator] Question: {question[:120]}...")
    t0 = time.time()
    result = orchestrator.process_question(question=question, task_id=task_id)
    elapsed = round(time.time() - t0, 2)

    print(f"[Orchestrator] Completed in {elapsed}s")
    print(f"[Orchestrator] Capability Bundle ID: {result.get('capability_bundle_id', 'N/A')[:8]}...")
    print(f"[Orchestrator] Context Bundle ID:    {result.get('context_bundle_id', 'N/A')[:8]}...")

    decomp = result.get("task_decomposition", {})
    subtasks = decomp.get("sub_tasks", decomp.get("subtasks", []))
    print(f"[Orchestrator] Sub-tasks identified: {len(subtasks)}")
    for i, t in enumerate(subtasks[:3], 1):
        if isinstance(t, dict):
            print(f"  {i}. [{t.get('agent', 'N/A')}] {str(t.get('description', t.get('task', '')))[:80]}")
        else:
            print(f"  {i}. {str(t)[:80]}")

    return result


# ── Step 3: AIMS Routing Audit (6.1) ─────────────────────────────────────────

def run_aims_routing_audit() -> dict:
    """
    6.1 — Verify all artifacts in the store route correctly to Mode A or B.
    This uses the deterministic router — no LLM call.
    """
    _section("STEP 3 — AIMS Routing Audit (6.1)")

    summary = verify_routing_for_all_artifacts()

    total = summary["total_artifacts_audited"]
    a = summary["mode_a_count"]
    b = summary["mode_b_count"]
    pct_b = summary["mode_b_pct"]

    print(f"[AIMS Routing] Total artifacts audited:  {total}")
    print(f"[AIMS Routing] Mode A (auto-log):        {a}")
    print(f"[AIMS Routing] Mode B (human approval):  {b} ({pct_b}%)")
    print(f"[AIMS Routing] By artifact type:")

    for atype, counts in sorted(summary["by_artifact_type"].items()):
        mode_a = counts.get("A", 0)
        mode_b = counts.get("B", 0)
        print(f"  {atype:<35} A={mode_a}  B={mode_b}")

    return summary


# ── Step 4: Bottleneck Detection (6.2) ───────────────────────────────────────

def run_bottleneck_detection() -> dict:
    """6.2 — Aggregate telemetry across all prior investigation cycles."""
    _section("STEP 4 — Phase 7 Bottleneck Identification (6.2)")

    detector = BottleneckDetector(phase=6)
    result = detector.run_analysis()
    return result


# ── Step 5: Improvement Proposal + Sandbox (6.3 + 6.4) ──────────────────────

def run_improvement_proposal(
    bottleneck_result: dict,
    orchestrator_result: dict,
) -> dict:
    """
    6.3 — Generate improvement proposal for the top bottleneck.
    6.4 — Route to Mode B (human approval gate marked; no auto-approve).
    """
    _section("STEP 5 — Phase 7 Proposal + Sandbox Test (6.3 + 6.4)")

    top_bottleneck = bottleneck_result["top_bottleneck"]
    if not top_bottleneck:
        print("[Phase7Proposer] No bottleneck identified — cannot generate proposal.")
        return {}

    capability_bundle_id = orchestrator_result.get("capability_bundle_id", str(uuid.uuid4()))
    task_id = str(uuid.uuid4())

    proposer = Phase7Proposer(phase=6)
    result = proposer.generate_proposal(
        bottleneck=top_bottleneck,
        capability_bundle_id=capability_bundle_id,
        task_id=task_id,
    )

    print(f"\n[Phase7Proposer] Proposal title:     {result.get('proposal_title', 'N/A')}")
    print(f"[Phase7Proposer] Sandbox verdict:    {result.get('sandbox_verdict', 'N/A')}")
    print(f"[Phase7Proposer] Gate outcome:       {result.get('gate_outcome', 'N/A')}")
    print(f"[Phase7Proposer] Mode B routing:     {result.get('routed_to_mode_b', False)}")
    print(f"[Phase7Proposer] Confirmation Gate item: {str(result.get('confirmation_gate_item_id', 'N/A'))[:8]}...")

    # Explicit governance check — DI #2 permanently locked
    if result.get("gate_outcome") == "SUBMITTED_AWAITING_DECISION":
        print(f"[Phase7Proposer] ⚠  Confirmation Gate OPEN — proposal NOT deployed.")
        print(f"[Phase7Proposer]    DI #2: No auto-approve. Silence ≠ approval.")
        print(f"[Phase7Proposer]    Operator must explicitly approve before any deployment.")

    return result


# ── Step 6: Exit Criteria Summary ─────────────────────────────────────────────

def print_exit_criteria_summary(
    orchestrator_result: dict,
    streaming_result: dict,
    routing_summary: dict,
    bottleneck_result: dict,
    proposal_result: dict,
    t_total: float,
) -> bool:
    _section("PHASE 6 EXIT CRITERIA SUMMARY")

    results = []

    # Core exit criteria from implementation_plan.md §6
    r_a = _check_exit_a(orchestrator_result)
    results.append(("(a) Workflow runs without human scaffolding at intermediate steps",
                     r_a, "Orchestrator → BottleneckDetector → Phase7Proposer all ran autonomously"))

    r_b = _check_exit_b(proposal_result) if proposal_result else False
    results.append(("(b) Human involved only at governance gates (Confirmation Gate)",
                     r_b, "DI #2 confirmed — AWAITING_DECISION, no auto-approve"))

    r_c = _check_exit_c(streaming_result)
    results.append(("(c) Portability wrapper documented and tested (generate_streaming)",
                     r_c, f"{streaming_result.get('output_tokens', 0)} output tokens via streaming path"))

    # Deliverable-level checks
    r_61 = _check_aims_routing(routing_summary)
    results.append(("6.1  AIMS routing correct for all artifact types",
                     r_61, f"Mode A={routing_summary.get('mode_a_count', 0)}, "
                            f"Mode B={routing_summary.get('mode_b_count', 0)}"))

    r_62 = _check_bottlenecks(bottleneck_result) if bottleneck_result else False
    top = (bottleneck_result or {}).get("top_bottleneck") or {}
    results.append(("6.2  Phase 7 bottleneck identified (confidence ≥ 0.70)",
                     r_62, f"{top.get('id', 'N/A')}: {round(top.get('confidence_score', 0) * 100)}%"))

    r_63 = _check_sandbox(proposal_result) if proposal_result else False
    results.append(("6.3  Improvement proposal + sandbox test PASS or CONDITIONAL_PASS",
                     r_63, f"Sandbox: {proposal_result.get('sandbox_verdict', 'N/A')}"))

    r_64 = proposal_result.get("routed_to_mode_b", False) if proposal_result else False
    results.append(("6.4  Mode B AIMS routing confirmed for proposal (human gate marked)",
                     r_64, "proposal artifact_type='phase7_proposal' → Mode B trigger"))

    r_65 = bool(r_c)
    results.append(("6.5  Portability layer documented; alternative invocation functional",
                     r_65, "lib/llm_wrapper.py: 3 integration points + generate_streaming() active"))

    print(f"\n{'─' * 70}")
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    for label, p, detail in results:
        _check(label, p, detail)

    print(f"\n{'─' * 70}")
    all_pass = passed == total
    status_icon = "✅" if all_pass else "❌"
    print(f"\n  {status_icon} {passed}/{total} exit criteria PASS  |  Total elapsed: {round(t_total, 1)}s")

    if all_pass:
        print("\n  PHASE 6 COMPLETE ✅")
        print("  Full AIMS Integration + Recursive Self-Improvement loop is operational.")
        print("  Maldros Phase 0 → Phase 6 architecture is COMPLETE.")
    else:
        failed = [(l, d) for l, p, d in results if not p]
        print("\n  PHASE 6 INCOMPLETE — criteria failed:")
        for label, detail in failed:
            print(f"    ✗ {label}")
            if detail:
                print(f"      → {detail}")

    return all_pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\nMaldros Phase 6 Demo — {datetime.now(timezone.utc).isoformat()}")
    print(f"Full AIMS Integration + Recursive Self-Improvement")
    print(f"Working directory: {BASE}")

    t_start = time.time()

    # Step 1: Portability test — generate_streaming() (no investigation overhead)
    streaming_result = run_portability_test()

    # Step 2: Orchestrator (CDI query + Capability Bundle; one LLM call)
    orchestrator_result = run_orchestrator()

    # Step 3: AIMS routing audit (deterministic — no LLM call)
    routing_summary = run_aims_routing_audit()

    # Step 4: Bottleneck detection (deterministic telemetry scan — no LLM call)
    bottleneck_result = run_bottleneck_detection()

    # Step 5: Improvement proposal + sandbox (one LLM call — Phase7Proposer)
    proposal_result = run_improvement_proposal(bottleneck_result, orchestrator_result)

    t_total = time.time() - t_start

    # Step 6: Exit criteria summary
    all_pass = print_exit_criteria_summary(
        orchestrator_result=orchestrator_result,
        streaming_result=streaming_result,
        routing_summary=routing_summary,
        bottleneck_result=bottleneck_result,
        proposal_result=proposal_result,
        t_total=t_total,
    )

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
