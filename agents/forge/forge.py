"""
Forge Agent — Phase 5 implementation.
agents/forge/forge.py

Mandate: invent novel analytical frameworks, measurement approaches, and data product
architectures for the Financial Impact Analysis domain.

Innovation Mandate (Design Invariant #12): ≥15% of FIRST_PRINCIPLES invention cycles
must produce is_novel=True outputs. Tracked in telemetry/forge_state.json.

Generation mode is always declared before all output (Design Invariant #7).

Pipeline ordering (spec-deliberate):
  Red-Team stress test RUNS BEFORE statistical validation — per architectural_overview
  Phase 5 spec and CLAUDE.md Critical Architecture Rules §3.

All 13 Invention Pipeline Report (IPR) assets are produced on every cycle regardless of
Pre-Screen Gate outcome.
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.artifact import create_artifact, write_artifact, read_artifact
from lib.second_brain import write_forge_entry
from lib.llm_wrapper import LLMWrapper
from lib.few_shot_bank import FewShotBank
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

STATE_PATH = BASE / "telemetry" / "forge_state.json"

# Forge system prompt (loaded from system_prompt.md at runtime)
_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"
FORGE_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


class ForgeAgent:
    """
    Phase 5 Forge Agent.

    run_invention_cycle(problem_statement, capability_bundle_id, trigger)
        — full 11-step invention pipeline, 13-asset IPR output.
    """

    def __init__(self, phase: int = 5):
        self.phase = phase
        self._state = self._load_state()

    # ── State management (Innovation Mandate tracking) ────────────────────────

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "total_cycles": 0,
            "first_principles_cycles": 0,
            "novel_cycles": 0,
            "innovation_mandate_pct": 15.0,
            "last_cycle_timestamp": None,
            "cycles": [],
        }

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _innovation_mandate_status(self) -> dict:
        fp = self._state["first_principles_cycles"]
        novel = self._state["novel_cycles"]
        mandate_pct = self._state["innovation_mandate_pct"]
        actual_pct = (novel / fp * 100.0) if fp > 0 else 0.0
        # Grace period: first 2 FIRST_PRINCIPLES cycles don't gate
        in_grace = fp < 2
        compliant = in_grace or (actual_pct >= mandate_pct)
        return {
            "first_principles_cycles": fp,
            "novel_cycles": novel,
            "mandate_pct": mandate_pct,
            "actual_pct": round(actual_pct, 1),
            "compliant": compliant,
            "in_grace_period": in_grace,
        }

    # ── Mode selection ────────────────────────────────────────────────────────

    def _select_generation_mode(self, problem_statement: str, reader: CDIReader) -> str:
        """
        Select generation mode based on Second Brain signal and problem keywords.
        FIRST_PRINCIPLES when no strong prior exists or problem is explicitly novel.
        ANALOGICAL when Second Brain surfaces a high-similarity prior.
        """
        try:
            sb = reader.get_second_brain_state()
            prior_analyses = sb.get("recent_analyses", [])
            problem_lower = problem_statement.lower()
            # Check if any prior analysis addresses the same structural problem
            for analysis in prior_analyses:
                key = str(analysis).lower()
                if any(term in key for term in ("percolation", "slow-burn", "graph threshold")):
                    return "ANALOGICAL"
        except Exception:
            pass

        # Keywords indicating the problem is new / explicitly requests novel approach
        first_principles_signals = [
            "novel", "new approach", "new detection", "miss", "gap",
            "below threshold", "slow-burn", "design a", "invent", "different from",
            "current approach fails", "not caught", "evades",
        ]
        problem_lower = problem_statement.lower()
        if any(sig in problem_lower for sig in first_principles_signals):
            return "FIRST_PRINCIPLES"

        return "FIRST_PRINCIPLES"  # conservative default: derive, don't assume prior

    # ── Pre-Screen Gate ───────────────────────────────────────────────────────

    def _run_pre_screen_gate(
        self,
        rt_result: dict,
        stat_pre: dict,
        cost_model: dict,
        gen_mode: str,
        is_novel: bool,
    ) -> dict:
        """
        Pre-Screen Gate — determines PROMOTED / PARKED / REJECTED.

        REJECTED : Red-Team verdict is Brittle (unacceptable adversarial risk)
        PARKED   : Conditionally Robust but statistical or cost concerns flag it
        PROMOTED : Robust or Conditionally Robust with acceptable stats/cost
        """
        filters = []
        rejected = False
        parked = False

        # Filter 1: Red-Team verdict
        verdict = rt_result.get("verdict", "Brittle")
        if verdict == "Brittle":
            filters.append({
                "filter": "red_team_verdict",
                "outcome": "FAIL",
                "rationale": (
                    f"Red-Team verdict is Brittle — framework rejected. "
                    f"Primary weakness: {rt_result.get('primary_weakness', 'unknown')}"
                ),
            })
            rejected = True
        else:
            filters.append({
                "filter": "red_team_verdict",
                "outcome": "PASS",
                "rationale": (
                    f"Red-Team verdict is {verdict} — acceptable for deployment planning."
                ),
            })

        # Filter 2: Statistical pre-validation precision floor
        precision = float(stat_pre.get("precision_estimate", 0.0))
        if not rejected:
            if precision > 0.0 and precision < 0.40:
                filters.append({
                    "filter": "statistical_pre_validation",
                    "outcome": "PARK",
                    "rationale": (
                        f"Estimated precision {precision:.0%} is below 40% minimum threshold — "
                        f"parked pending empirical calibration or framework redesign."
                    ),
                })
                parked = True
            else:
                desc = (
                    f"Precision estimate {precision:.0%} acceptable."
                    if precision > 0.0
                    else "Statistical pre-validation deferred to production pilot (estimates unavailable)."
                )
                filters.append({
                    "filter": "statistical_pre_validation",
                    "outcome": "PASS",
                    "rationale": desc,
                })

        # Filter 3: Cost model — dual-HIGH park condition
        if not rejected:
            fp_harm = cost_model.get("false_positive_harm", "LOW")
            user_friction = cost_model.get("user_friction", "LOW")
            if fp_harm == "HIGH" and user_friction == "HIGH":
                filters.append({
                    "filter": "cost_model",
                    "outcome": "PARK",
                    "rationale": (
                        f"Both false-positive harm and user friction rated HIGH — "
                        f"deployment requires hardening before production."
                    ),
                })
                parked = True
            else:
                filters.append({
                    "filter": "cost_model",
                    "outcome": "PASS",
                    "rationale": (
                        f"Cost model acceptable "
                        f"(FP harm={fp_harm}, user friction={user_friction})."
                    ),
                })

        # Filter 4: Innovation Mandate (DI #12) — FIRST_PRINCIPLES cycles
        if gen_mode == "FIRST_PRINCIPLES" and not rejected:
            mandate = self._innovation_mandate_status()
            if (
                not mandate["in_grace_period"]
                and not mandate["compliant"]
                and not is_novel
            ):
                filters.append({
                    "filter": "innovation_mandate",
                    "outcome": "PARK",
                    "rationale": (
                        f"Innovation Mandate at {mandate['actual_pct']:.1f}% "
                        f"(threshold {mandate['mandate_pct']:.0f}%) — "
                        f"incremental refinement cycle parked for operator review."
                    ),
                })
                parked = True
            else:
                status = (
                    f"{mandate['actual_pct']:.1f}% of {mandate['first_principles_cycles']} FP cycles novel"
                    if not mandate["in_grace_period"]
                    else "grace period active (< 2 FIRST_PRINCIPLES cycles completed)"
                )
                filters.append({
                    "filter": "innovation_mandate",
                    "outcome": "PASS",
                    "rationale": f"Innovation Mandate compliant — {status}.",
                })

        # Determine outcome and deployment tier
        if rejected:
            outcome = "REJECTED"
            tier = "NOT_DEPLOYED"
        elif parked:
            outcome = "PARKED"
            tier = "EXPERIMENTAL"
        else:
            outcome = "PROMOTED"
            tier = "SHADOW" if verdict == "Conditionally Robust" else "PRODUCTION"

        return {
            "outcome": outcome,
            "filters": filters,
            "recommended_deployment_tier": tier,
        }

    # ── Main invention cycle ──────────────────────────────────────────────────

    def run_invention_cycle(
        self,
        problem_statement: str,
        capability_bundle_id: str,
        trigger: str = "manual",
    ) -> dict:
        """
        Full invention pipeline — 11 steps, 13-asset IPR.

        Parameters
        ----------
        problem_statement     : Natural-language problem description
        capability_bundle_id  : Artifact ID of the Orchestrator's Capability Bundle
        trigger               : "manual" | "algorithmic_rule_exploration" | "constraint_research"

        Returns
        -------
        dict with: ipr_artifact_id, gate_outcome, verdict, framework_name, gen_mode,
                   is_novel, recommended_deployment_tier, aims_mode_a_id
        """
        cb = read_artifact(capability_bundle_id)
        task_id = cb["content"]["task_id"]

        print(f"\n[Forge] ═══ Invention Cycle ═══")
        print(f"[Forge] task_id={task_id} | trigger={trigger}")
        print(f"[Forge] Problem: {problem_statement[:120]}...")

        # ── Step 1: CDI Layer query (mandatory — DI #3 audit trail) ──────────
        reader = CDIReader(agent_name="forge", task_id=task_id)
        reasoning_frameworks = reader.get_reasoning_frameworks()
        cross_domain_analogues = reader.get_all_analogues()
        second_brain_signal = reader.get_second_brain_state()
        _ = reader.get_inference_layer_status("L1")

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[Forge] CDI Layer queried: {cdi_query_record['domains_queried']}")

        # ── Step 2: Mode selection (DI #7 — always declared) ─────────────────
        gen_mode = self._select_generation_mode(problem_statement, reader)
        print(f"[Forge] Generation mode (DI #7): {gen_mode}")

        # ── Step 3: FSB injection ─────────────────────────────────────────────
        fsb = FewShotBank(agent_name="forge", task_id=task_id)
        forge_prompt, fsb_ids = fsb.inject_into_system_prompt(
            FORGE_SYSTEM_PROMPT, "forge_invention", "forge"
        )

        # ── Step 4: LLM call — derivation + proposed_framework ───────────────
        llm = LLMWrapper(agent_name="forge", task_id=task_id)

        llm_input = {
            "problem_statement": problem_statement,
            "trigger": trigger,
            "generation_mode_declared": gen_mode,
            "cdi_context": {
                "active_reasoning_modes": [
                    m.get("id", str(m)) for m in reasoning_frameworks[:3]
                ],
                "cross_domain_analogues": [
                    {
                        "source_domain": a.get("source_domain", ""),
                        "analytics_translation": a.get("analytics_translation", ""),
                        "structural_isomorphism": a.get("structural_isomorphism", ""),
                    }
                    for a in cross_domain_analogues[:6]
                ],
                "second_brain_prior_analyses": second_brain_signal.get("analyses", [])[:2],
            },
            "innovation_mandate_status": self._innovation_mandate_status(),
            "instructions": (
                f"You are operating in {gen_mode} mode. "
                + (
                    "Full derivation chain is mandatory — minimum 4 logical steps from "
                    "first principles. Begin from the problem structure, not the solution. "
                    if gen_mode == "FIRST_PRINCIPLES"
                    else "Cite the precedent and state your structural adaptation rationale. "
                )
                + "Produce all 13 IPR assets. Return ONLY valid JSON."
            ),
        }

        print(f"[Forge] Calling LLM for {gen_mode} invention...")
        t0 = time.time()
        llm_response = llm.generate(
            system_prompt=forge_prompt,
            user_message=json.dumps(llm_input, indent=2, default=str),
            max_tokens=8000,
        )
        llm_elapsed = round(time.time() - t0, 2)
        print(f"[Forge] LLM returned in {llm_elapsed}s")

        # Parse LLM JSON output
        llm_content = llm_response["content"]
        try:
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if "```" in clean:
                clean = clean.rsplit("```", 1)[0]
            llm_out = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"[Forge] JSON parse failed ({exc}); using fallback scaffold")
            llm_out = {
                "derivation_chain": [f"[LLM parse failed: {exc}]"],
                "proposed_framework": {
                    "name": "Parse Failure",
                    "description": "LLM output could not be parsed as JSON.",
                    "detection_principle": "",
                    "mathematical_foundation": "",
                    "implementation_mechanism": "",
                },
                "is_novel": False,
                "novel_invention_typology": "incremental_refinement",
                "statistical_pre_validation": {
                    "precision_estimate": 0.0, "precision_ci": [0.0, 0.0],
                    "recall_estimate": 0.0, "recall_ci": [0.0, 0.0],
                    "false_positive_rate_estimate": 0.0, "fpr_ci": [0.0, 0.0],
                    "confidence_in_estimates": "LOW",
                    "estimation_rationale": "Parse failed.",
                },
                "cost_model": {
                    "user_friction": "HIGH", "infrastructure_load": "HIGH",
                    "false_positive_harm": "HIGH", "stakeholder_trust_impact": "HIGH",
                    "cost_rationale": "Parse failed.",
                },
                "cross_references": [],
                "known_limitations": ["LLM output could not be parsed as JSON."],
                "recommended_deployment_tier": "EXPERIMENTAL",
            }

        framework = llm_out.get("proposed_framework", {})
        derivation_chain = llm_out.get("derivation_chain", [])
        is_novel = bool(llm_out.get("is_novel", False))
        novel_typology = llm_out.get("novel_invention_typology", "incremental_refinement")
        stat_pre = llm_out.get("statistical_pre_validation", {})
        cost_model = llm_out.get("cost_model", {})

        print(f"[Forge] Framework: {framework.get('name', 'unnamed')}")
        print(f"[Forge] Novel: {is_novel} ({novel_typology})")
        print(f"[Forge] Derivation chain: {len(derivation_chain)} step(s)")

        # ── Step 5: Innovation Mandate tracking (DI #12) ──────────────────────
        self._state["total_cycles"] += 1
        if gen_mode == "FIRST_PRINCIPLES":
            self._state["first_principles_cycles"] += 1
            if is_novel:
                self._state["novel_cycles"] += 1
        self._state["last_cycle_timestamp"] = datetime.now(timezone.utc).isoformat()
        self._state["cycles"].append({
            "timestamp": self._state["last_cycle_timestamp"],
            "problem_statement": problem_statement[:120],
            "gen_mode": gen_mode,
            "is_novel": is_novel,
            "trigger": trigger,
        })
        self._save_state()
        mandate = self._innovation_mandate_status()
        print(
            f"[Forge] Innovation Mandate (DI #12): "
            f"{mandate['novel_cycles']}/{mandate['first_principles_cycles']} FP novel "
            f"({mandate['actual_pct']:.1f}% vs {mandate['mandate_pct']:.0f}% target)"
        )

        # ── Step 6: Red-Team stress test ──────────────────────────────────────
        # Runs BEFORE statistical validation — ordering is spec-deliberate
        # (architectural_overview Phase 5, CLAUDE.md Critical Architecture Rules)
        print(f"\n[Forge] → Invoking Red-Team for framework stress test...")
        from agents.red_team.red_team import RedTeamAgent
        rt_agent = RedTeamAgent(phase=5)
        rt_result = rt_agent.run_framework_stress_test(
            framework_dict=framework,
            capability_bundle_id=capability_bundle_id,
        )
        print(f"[Forge] Red-Team verdict: {rt_result['verdict']}")

        # ── Step 7: Statistical pre-validation (from LLM output) ─────────────
        # stat_pre extracted from LLM output above
        precision = stat_pre.get("precision_estimate", 0.0)
        recall = stat_pre.get("recall_estimate", 0.0)
        fpr = stat_pre.get("false_positive_rate_estimate", 0.0)
        print(
            f"[Forge] Statistical pre-validation: "
            f"precision={precision:.0%}, recall={recall:.0%}, FPR={fpr:.0%} "
            f"[confidence: {stat_pre.get('confidence_in_estimates', 'N/A')}]"
        )

        # ── Steps 8-9: Pre-Screen Gate ────────────────────────────────────────
        gate = self._run_pre_screen_gate(rt_result, stat_pre, cost_model, gen_mode, is_novel)
        print(f"[Forge] Pre-Screen Gate: {gate['outcome']} → tier: {gate['recommended_deployment_tier']}")

        # ── Step 10: Assemble 13-asset IPR artifact ───────────────────────────
        ipr_content = {
            "task_id": task_id,
            "trigger": trigger,
            # Asset 1: problem_framing
            "problem_framing": problem_statement,
            # Asset 2: generation_mode (DI #7)
            "generation_mode": gen_mode,
            # Asset 3: is_novel + novel_invention_typology (DI #12)
            "is_novel": is_novel,
            "novel_invention_typology": novel_typology,
            # Asset 4: proposed_framework
            "proposed_framework": framework,
            # Asset 5: derivation_chain
            "derivation_chain": derivation_chain,
            # Asset 6: red_team results
            "red_team_verdict": rt_result["verdict"],
            "red_team_primary_weakness": rt_result.get("primary_weakness", ""),
            "red_team_hardening_steps": rt_result.get("hardening_steps", []),
            "red_team_report_id": rt_result["red_team_report_id"],
            # Asset 7: statistical_pre_validation
            "statistical_pre_validation": stat_pre,
            # Asset 8: cost_model
            "cost_model": cost_model,
            # Asset 9: pre_screen_gate_outcome + filters
            "pre_screen_gate_outcome": gate["outcome"],
            "pre_screen_gate_filters": gate["filters"],
            # Asset 10: recommended_deployment_tier
            "recommended_deployment_tier": gate["recommended_deployment_tier"],
            # Asset 11: cross_references
            "cross_references": llm_out.get("cross_references", []),
            # Asset 12: lineage_trace (provenance chain in artifact envelope)
            "lineage_trace": {
                "capability_bundle_id": capability_bundle_id,
                "red_team_report_id": rt_result["red_team_report_id"],
                "llm_elapsed_sec": llm_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
                "fsb_injected_ids": fsb_ids,
                "cdi_query_record": cdi_query_record,
            },
            "innovation_mandate_status": mandate,
        }

        # Asset 13: known_limitations (in artifact envelope field)
        known_limitations = llm_out.get("known_limitations", [
            "Theoretical statistical pre-validation only — no empirical simulation performed",
            "Red-Team evaluation is sandbox-only; production adversary behavior may differ",
        ])

        ipr_artifact = create_artifact(
            artifact_type="invention_pipeline_report",
            producing_agent="forge",
            phase=self.phase,
            content=ipr_content,
            provenance=[capability_bundle_id, rt_result["red_team_report_id"]],
            confidence_score=min(0.95, float(rt_result.get("penetration_difficulty_score", 0.55))),
            known_limitations=known_limitations,
        )

        # ── Step 11a: Write artifact ──────────────────────────────────────────
        ipr_path = write_artifact(ipr_artifact)
        print(f"\n[Forge] IPR artifact written: {ipr_artifact['artifact_id']}")

        # ── Step 11b: Second Brain vault write ───────────────────────────────
        write_forge_entry(ipr_artifact)

        # ── Step 11c: CDI non-activation record ──────────────────────────────
        updater = CDIUpdater(agent_name="forge", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        # ── Step 11d: AIMS Mode A logging ─────────────────────────────────────
        aims_a = create_artifact(
            artifact_type="aims_mode_a",
            producing_agent="forge",
            phase=self.phase,
            content={
                "event_type": "forge_invention_cycle",
                "task_id": task_id,
                "trigger": trigger,
                "gen_mode": gen_mode,
                "is_novel": is_novel,
                "novel_typology": novel_typology,
                "framework_name": framework.get("name", ""),
                "red_team_verdict": rt_result["verdict"],
                "gate_outcome": gate["outcome"],
                "deployment_tier": gate["recommended_deployment_tier"],
                "ipr_artifact_id": ipr_artifact["artifact_id"],
                "innovation_mandate": mandate,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            provenance=[ipr_artifact["artifact_id"]],
            confidence_score=0.95,
            known_limitations=[],
        )
        write_artifact(aims_a)
        print(f"[Forge] AIMS Mode A logged: {aims_a['artifact_id'][:8]}")

        return {
            "ipr_artifact_id": ipr_artifact["artifact_id"],
            "ipr_path": str(ipr_path),
            "gate_outcome": gate["outcome"],
            "verdict": rt_result["verdict"],
            "primary_weakness": rt_result.get("primary_weakness", ""),
            "hardening_steps": rt_result.get("hardening_steps", []),
            "penetration_difficulty_score": rt_result.get("penetration_difficulty_score", 0.0),
            "framework_name": framework.get("name", ""),
            "gen_mode": gen_mode,
            "is_novel": is_novel,
            "novel_typology": novel_typology,
            "recommended_deployment_tier": gate["recommended_deployment_tier"],
            "aims_mode_a_id": aims_a["artifact_id"],
            "derivation_steps": len(derivation_chain),
        }
