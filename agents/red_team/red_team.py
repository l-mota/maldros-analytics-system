"""
Red-Team Agent — Phase 3 full implementation.
agents/red_team/red_team.py

Mandate: adversarial stress-testing of proposed metrics and experiment designs.
Applies evasion categories E1–E12 to every experiment design or metric definition
before it reaches stakeholders. Produces a Red-Team Report with a verdict of
Robust / Conditionally Robust / Brittle and ranked hardening steps.

Phase 0 stub (run()) preserved for backward compatibility.
Phase 3 full implementation: run_experiment_stress_test()

HARD CONSTRAINTS (Design Invariant #8):
- Sandbox only — NO live data access, NO production system access
- Report-only output — no automated remediation, no data writes
- Must attempt maximum adversarial effort — Robust on every category signals
  insufficient effort (C-033 note: this is a system failure, not a success)
- Runs BEFORE statistical validation (ordering is deliberate per spec)
- CDI Layer query mandatory before every evaluation

Evasion categories (E1–E12, from analytics_engineering_system_prompt.md):
  E1  Measurement evasion         E7  Temporal drift
  E2  Survivorship bias           E8  Data pipeline fragility
  E3  Confounding                 E9  Peeking and p-hacking
  E4  Novelty/Hawthorne effect    E10 Semantic drift
  E5  Segment heterogeneity       E11 Adaptive stakeholder response
  E6  Threshold gaming            E12 Structural seam exploitation

C-033 D-1 fix: Phase 0 stub had incorrect evasion category names
(E1_feature_manipulation etc.) — replaced with spec-defined E1–E12.
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.artifact import create_artifact, write_artifact, read_artifact, validate_envelope
from lib.second_brain import write_red_team_entry
from lib.llm_wrapper import LLMWrapper
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

DATA_DIR = BASE / "data" / "raw"

# Spec-authoritative evasion catalogue (analytics_engineering_system_prompt.md)
EVASION_CATALOGUE = {
    "E1":  "Measurement evasion: the metric is gameable by optimizing its proxy without improving the underlying construct",
    "E2":  "Survivorship bias: the population being measured is not the population the conclusion applies to",
    "E3":  "Confounding: a third variable explains both the treatment and the outcome",
    "E4":  "Novelty/Hawthorne effect: behavior changes because of the measurement, not the treatment",
    "E5":  "Segment heterogeneity: the average effect masks divergent effects in subpopulations",
    "E6":  "Threshold gaming: stakeholders adjust behavior to stay on the favorable side of a KPI threshold",
    "E7":  "Temporal drift: the metric is valid today but degrades as user behavior or product context evolves",
    "E8":  "Data pipeline fragility: the result is reproducible only under specific, undocumented pipeline conditions",
    "E9":  "Peeking and p-hacking: the analytical process creates opportunities for selective stopping or reporting",
    "E10": "Semantic drift: the metric definition and the business question it answers diverge over time",
    "E11": "Adaptive stakeholder response: stakeholders learn the system's signals and optimize against them",
    "E12": "Structural seam exploitation: the gap between what the data captures and what the question asks",
}

RED_TEAM_SYSTEM_PROMPT = """You are the Red-Team Agent in the Maldros analytics engineering system.

Your mandate: adversarially stress-test the experiment design across all 12 evasion
categories. You run BEFORE statistical validation — your job is to find failure modes,
not to confirm that the experiment worked.

HARD RULES:
1. Sandbox only — you have no access to live data or production systems.
2. Maximum adversarial effort is required. A Robust verdict on every evasion category
   means you are not trying hard enough — flag a self-assessment warning if this occurs.
3. For each evasion category, ask: "If a sophisticated actor tried to exploit this
   weakness, how hard would it be, and what is the realistic outcome?"
4. Effort-to-exploit scale: TRIVIAL (< 1 day) → LOW → MEDIUM → HIGH → VERY_HIGH.
   TRIVIAL/LOW = Brittle. MEDIUM = Conditionally Robust. HIGH/VERY_HIGH = Robust.
5. The overall verdict equals the worst-case single category finding.
   One Brittle category makes the whole experiment Brittle.
6. The deterministic_prescreens block in the input contains signals already confirmed
   by formal statistical tests. Do NOT downgrade pre-screened HIGH severity findings.
7. SPECIFICITY REQUIREMENT: A Brittle verdict on any evasion category requires a
   concrete, specific attack path against THIS experiment's design — not a generic
   concern that applies equally to any experiment using this metric class. If the
   concern is a category-level structural property of the metric (e.g., "proxy
   metrics can be gamed"), that is a Conditionally Robust finding with hardening
   recommendations, not Brittle. Brittle is reserved for attack paths you can
   articulate specifically: what actor, what action, what signal would shift,
   and why this experiment's design does not prevent it.

EVASION CATALOGUE:
E1  Measurement evasion: the metric is gameable by optimizing its proxy
E2  Survivorship bias: measured population ≠ conclusion population
E3  Confounding: a third variable explains treatment and outcome
E4  Novelty/Hawthorne effect: behavior changes due to observation, not treatment
E5  Segment heterogeneity: average effect masks divergent subpopulation effects
E6  Threshold gaming: stakeholders optimize to stay on the favorable side of a KPI
E7  Temporal drift: metric degrades as context evolves
E8  Data pipeline fragility: result reproducible only under undocumented conditions
E9  Peeking and p-hacking: opportunities for selective stopping or reporting
E10 Semantic drift: metric definition diverges from the business question over time
E11 Adaptive stakeholder response: stakeholders learn and optimize against the signal
E12 Structural seam exploitation: gap between captured data and the actual question

OUTPUT FORMAT (JSON):
{
  "experiment_id": str,
  "overall_verdict": "Robust|Conditionally Robust|Brittle",
  "verdict_rationale": str,
  "primary_weakness": str,
  "hardening_steps": [str],
  "evasion_assessments": [
    {
      "code": "E1",
      "description": str,
      "exploitability": "LOW|MEDIUM|HIGH",
      "effort_to_exploit": "TRIVIAL|LOW|MEDIUM|HIGH|VERY_HIGH",
      "attack_path": str,
      "verdict_contribution": "Robust|Conditionally Robust|Brittle",
      "mitigation": str
    }
  ],
  "penetration_difficulty_score": float,
  "confidence_score": float,
  "known_limitations": [str]
}

Return ONLY valid JSON. No markdown, no preamble."""


def _deterministic_prescreens(exp: dict, stat_tests: Optional[dict] = None) -> dict:
    """
    Deterministic signal extraction before LLM evaluation.
    Flags known Brittle/HIGH-severity signals that the LLM cannot downgrade.
    """
    signals: dict = {}
    stat = stat_tests or {}

    # E4 — Novelty/Hawthorne: flagged in source data
    if exp.get("novelty_effect_suspected"):
        signals["E4"] = {
            "pre_screened": True,
            "evidence": "novelty_effect_suspected=True in experiment record",
            "severity": "HIGH",
        }

    # E9 — Peeking: SRM is a common peeking signature; also check proxy
    peeking_risk = stat.get("peeking", {}).get("risk_level", "LOW")
    if exp.get("srm_detected") or peeking_risk == "HIGH":
        signals["E9"] = {
            "pre_screened": True,
            "evidence": (
                "SRM detected — sample ratio mismatch is a canonical early-stopping signature"
                if exp.get("srm_detected")
                else f"Statistical pre-screen rated peeking risk {peeking_risk} based on p-value zone and sample size"
            ),
            "severity": "HIGH" if exp.get("srm_detected") else "MEDIUM",
        }

    # E3 — Confounding: significant result from underpowered design
    power = stat.get("power", {}).get("retrospective_power", 1.0)
    p_val = float(exp.get("p_value", 1.0))
    if p_val < 0.05 and power < 0.50:
        signals["E3"] = {
            "pre_screened": True,
            "evidence": (
                f"Statistically significant result (p={p_val:.4f}) from an underpowered "
                f"design (retrospective power={power:.3f}); confounding or publication "
                f"bias is a plausible explanation"
            ),
            "severity": "MEDIUM",
        }

    # E5 — always requires assessment; no assignment logs available
    signals["E5"] = {
        "pre_screened": False,
        "evidence": "Subgroup assignment logs unavailable; E5 requires manual review of tier/region split",
        "severity": "UNKNOWN",
    }

    return signals


class RedTeamAgent:
    """
    Phase 3 full implementation.

    run()                       — Phase 0 backward-compatible stub
    run_experiment_stress_test() — Phase 3 full E1–E12 adversarial evaluation
    """

    def __init__(self, phase: int = 3):
        self.phase = phase

    # ── Phase 0 stub (preserved for backward compatibility) ──────────────────
    def run(self, capability_bundle_id: str, evidence_bundle_id: str) -> dict:
        """Phase 0 stub. Validates inputs, emits skeleton red_team_report."""
        cb = read_artifact(capability_bundle_id)
        eb = read_artifact(evidence_bundle_id)
        validate_envelope(cb)
        validate_envelope(eb)

        task_id = cb["content"]["task_id"]
        reader = CDIReader(agent_name="red_team", task_id=task_id)
        _ = reader.get_reasoning_frameworks()

        report = create_artifact(
            artifact_type="red_team_report",
            producing_agent="red_team",
            phase=0,
            content={
                "task_id": task_id,
                "status": "STUB_PHASE_0",
                "note": "Full Red-Team Agent: call run_experiment_stress_test() (Phase 3).",
                "sandbox_confirmation": True,
                "verdict": "NOT_EVALUATED",
                "evasion_tests": [
                    {"code": code, "description": desc, "status": "NOT_EVALUATED"}
                    for code, desc in EVASION_CATALOGUE.items()
                ],
            },
            provenance=[capability_bundle_id, evidence_bundle_id],
            confidence_score=0.0,
            known_limitations=["Phase 0 stub — no adversarial testing performed"],
        )
        path = write_artifact(report)
        updater = CDIUpdater(agent_name="red_team", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())
        return {"red_team_report_id": report["artifact_id"], "path": str(path)}

    # ── Phase 3: full E1–E12 stress test ────────────────────────────────────
    def run_experiment_stress_test(
        self,
        experiment_id: str,
        capability_bundle_id: str,
        stat_tests: Optional[dict] = None,
    ) -> dict:
        """
        Stress-test one experiment from the experiments Parquet table.

        stat_tests: optional output of _run_experiment_analysis_tests() for
        deterministic pre-screening context only. This does NOT count as the
        Statistician running first — the ordering guarantee is preserved.

        Returns {red_team_report_id, path, verdict, primary_weakness,
                 hardening_steps, penetration_difficulty_score}
        """
        import duckdb

        print(f"\n[Red-Team] Stress-testing: {experiment_id}")

        # ── Read experiment (sandbox — synthetic dataset only) ──────────────
        conn = duckdb.connect()
        rows = conn.execute(
            f"SELECT * FROM '{DATA_DIR}/experiments.parquet' WHERE experiment_id = ?",
            [experiment_id],
        ).fetchall()
        cols = [d[0] for d in conn.description]
        conn.close()

        if not rows:
            raise ValueError(f"Experiment {experiment_id} not found")
        exp = dict(zip(cols, rows[0]))

        print(
            f"[Red-Team]   metric={exp.get('metric')}  "
            f"control_n={exp.get('control_n')}  treatment_n={exp.get('treatment_n')}  "
            f"p={exp.get('p_value'):.5f}  srm={exp.get('srm_detected')}  "
            f"novelty={exp.get('novelty_effect_suspected')}"
        )

        # ── CDI Layer query ─────────────────────────────────────────────────
        cb = read_artifact(capability_bundle_id)
        validate_envelope(cb)
        task_id = cb["content"]["task_id"]

        reader = CDIReader(agent_name="red_team", task_id=task_id)
        _ = reader.get_reasoning_frameworks()       # adversarial game trees mode
        _ = reader.get_all_analogues()              # cross-domain evasion analogues
        _ = reader.get_inference_layer_status("L1")

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[Red-Team] CDI Layer queried: {cdi_query_record['domains_queried']}")

        # ── Deterministic pre-screens ───────────────────────────────────────
        pre_screens = _deterministic_prescreens(exp, stat_tests)
        flagged_high = [k for k, v in pre_screens.items()
                        if v.get("pre_screened") and v.get("severity") == "HIGH"]
        print(f"[Red-Team] HIGH-severity pre-screens: {flagged_high or 'none'}")

        # ── LLM adversarial evaluation ──────────────────────────────────────
        print(f"[Red-Team] Calling LLM for E1–E12 adversarial evaluation...")
        llm = LLMWrapper(agent_name="red_team", task_id=task_id)
        t0 = time.time()

        llm_input = {
            "experiment_id": experiment_id,
            "experiment_metadata": {
                "metric": exp.get("metric"),
                "start_date": exp.get("start_date"),
                "end_date": exp.get("end_date"),
                "control_n": exp.get("control_n"),
                "treatment_n": exp.get("treatment_n"),
                "effect_size": exp.get("effect_size"),
                "p_value": exp.get("p_value"),
                "ci_lower": exp.get("ci_lower"),
                "ci_upper": exp.get("ci_upper"),
                "analyst_notes": exp.get("analyst_notes", ""),
            },
            "deterministic_prescreens": pre_screens,
            "statistical_context": stat_tests,
            "instructions": (
                "Apply maximum adversarial intelligence to all 12 categories. "
                "The deterministic_prescreens block contains HIGH-severity signals "
                "confirmed by formal tests — do not downgrade these. "
                "For remaining categories: assume a sophisticated actor with domain "
                "knowledge and full access to the experiment design. "
                "Self-assess: if you are returning Robust on every category, "
                "reconsider — you are likely not being adversarial enough."
            ),
        }

        llm_response = llm.generate(
            system_prompt=RED_TEAM_SYSTEM_PROMPT,
            user_message=json.dumps(llm_input, indent=2, default=str),
            max_tokens=6000,
        )
        llm_elapsed = round(time.time() - t0, 2)

        llm_content = llm_response["content"]
        try:
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            report = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError):
            worst = "Brittle" if flagged_high else "Conditionally Robust"
            primary = flagged_high[0] if flagged_high else "E5"
            report = {
                "experiment_id": experiment_id,
                "overall_verdict": worst,
                "verdict_rationale": f"LLM parse failed; deterministic fallback from pre-screens {flagged_high}",
                "primary_weakness": primary,
                "hardening_steps": [
                    f"Address {c}: {pre_screens[c]['evidence']}" for c in flagged_high
                ],
                "evasion_assessments": [],
                "penetration_difficulty_score": 0.25 if worst == "Brittle" else 0.60,
                "confidence_score": 0.40,
                "known_limitations": ["LLM parse failed; full E1–E12 unavailable"],
            }

        # L1 override: deterministic HIGH-severity pre-screens cannot be
        # overridden by the LLM's narrative assessment.
        if flagged_high:
            if report.get("overall_verdict") == "Robust":
                report["overall_verdict"] = "Conditionally Robust"
                report["verdict_rationale"] = (
                    f"L1 override: deterministic pre-screens found HIGH severity "
                    f"signals {flagged_high}; verdict floored at Conditionally Robust. "
                    + report.get("verdict_rationale", "")
                )

        verdict = report.get("overall_verdict", "Conditionally Robust")
        primary_weakness = report.get("primary_weakness", "UNKNOWN")
        pds = float(report.get("penetration_difficulty_score", 0.5))

        print(f"[Red-Team] Verdict: {verdict}  |  Primary weakness: {primary_weakness}  |  PDS: {pds:.2f}")

        # ── Emit red_team_report artifact ───────────────────────────────────
        result_content = {
            "task_id": task_id,
            "phase": self.phase,
            "experiment_id": experiment_id,
            "sandbox_confirmation": True,
            "overall_verdict": verdict,
            "primary_weakness": primary_weakness,
            "hardening_steps": report.get("hardening_steps", []),
            "evasion_assessments": report.get("evasion_assessments", []),
            "penetration_difficulty_score": pds,
            "verdict_rationale": report.get("verdict_rationale", ""),
            "deterministic_prescreens": pre_screens,
            "cdi_query_record": cdi_query_record,
            "lineage": {
                "capability_bundle_id": capability_bundle_id,
                "llm_elapsed_sec": llm_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
            },
        }

        confidence = float(report.get("confidence_score", 0.6))
        artifact = create_artifact(
            artifact_type="red_team_report",
            producing_agent="red_team",
            phase=self.phase,
            content=result_content,
            provenance=[capability_bundle_id],
            confidence_score=min(0.95, max(0.1, confidence)),
            known_limitations=report.get(
                "known_limitations",
                [
                    "Sandbox evaluation only — no live production signal available",
                    "E5 assessment is necessarily limited without assignment-level subgroup data",
                    "E8 assessment is theoretical without pipeline run history for this experiment",
                ],
            ),
        )
        path = write_artifact(artifact)
        print(f"[Red-Team] Report written: {artifact['artifact_id']}")

        # ── Vault write ─────────────────────────────────────────────────────
        write_red_team_entry(artifact)

        # ── CDI non-activation ──────────────────────────────────────────────
        updater = CDIUpdater(agent_name="red_team", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {
            "red_team_report_id": artifact["artifact_id"],
            "path": str(path),
            "verdict": verdict,
            "primary_weakness": primary_weakness,
            "hardening_steps": report.get("hardening_steps", []),
            "penetration_difficulty_score": pds,
        }

    # ── Phase 5: framework stress test ──────────────────────────────────────
    def run_framework_stress_test(
        self,
        framework_dict: dict,
        capability_bundle_id: str,
    ) -> dict:
        """
        Adversarial stress-test a proposed detection framework (not an experiment).

        Used by the Forge Agent — input is a framework specification dict rather than
        an experiment record from parquet. Evaluates E1–E12 in the context of:
        "Can a sophisticated abuse actor evade or undermine this detection approach?"

        Parameters
        ----------
        framework_dict       : dict with name, description, detection_principle,
                               mathematical_foundation, implementation_mechanism
        capability_bundle_id : Capability Bundle artifact ID for CDI lineage

        Returns
        -------
        dict with: red_team_report_id, path, verdict, primary_weakness,
                   hardening_steps, penetration_difficulty_score
        """
        framework_name = framework_dict.get("name", "Unnamed Framework")
        print(f"\n[Red-Team] Framework stress test: {framework_name}")

        # ── CDI Layer query ─────────────────────────────────────────────────
        cb = read_artifact(capability_bundle_id)
        validate_envelope(cb)
        task_id = cb["content"]["task_id"]

        reader = CDIReader(agent_name="red_team", task_id=task_id)
        _ = reader.get_reasoning_frameworks()    # adversarial game trees mode
        _ = reader.get_all_analogues()           # cross-domain evasion analogues
        _ = reader.get_inference_layer_status("L1")

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[Red-Team] CDI Layer queried: {cdi_query_record['domains_queried']}")

        # ── Deterministic pre-screens for detection frameworks ───────────────
        # E11 — Adaptive response: graph-based signals are structurally discoverable
        # E6  — Threshold gaming: any threshold-based gate is structurally gameable
        pre_screens: dict = {}
        detection_principle = framework_dict.get("detection_principle", "").lower()
        math_foundation = framework_dict.get("mathematical_foundation", "").lower()

        if any(t in detection_principle for t in ("threshold", "percolation", "cutoff", "limit")):
            pre_screens["E6"] = {
                "pre_screened": True,
                "evidence": "Threshold-based detection principle is structurally gameable (E6)",
                "severity": "MEDIUM",
            }

        if any(t in (detection_principle + math_foundation) for t in ("graph", "network", "cluster", "community")):
            pre_screens["E11"] = {
                "pre_screened": True,
                "evidence": (
                    "Graph-based detection signal is structurally observable to sophisticated actors "
                    "monitoring their own behavioral graph — E11 adaptive response is inherent"
                ),
                "severity": "MEDIUM",
            }

        flagged = [k for k, v in pre_screens.items() if v.get("pre_screened")]
        print(f"[Red-Team] Pre-screens flagged: {flagged or 'none'}")

        # ── LLM adversarial evaluation ──────────────────────────────────────
        print(f"[Red-Team] Calling LLM for framework E1–E12 adversarial evaluation...")
        llm = LLMWrapper(agent_name="red_team", task_id=task_id)
        t0 = time.time()

        llm_input = {
            "framework": {
                "name": framework_dict.get("name", ""),
                "description": framework_dict.get("description", ""),
                "detection_principle": framework_dict.get("detection_principle", ""),
                "mathematical_foundation": framework_dict.get("mathematical_foundation", ""),
                "implementation_mechanism": framework_dict.get("implementation_mechanism", ""),
            },
            "deterministic_prescreens": pre_screens,
            "instructions": (
                "Adversarially stress-test this DETECTION FRAMEWORK (not an experiment) "
                "against all 12 evasion categories. Reframe each category as: "
                "'Can a sophisticated abuse actor exploit this weakness in the detection design?' "
                "Apply maximum adversarial intelligence. For detection frameworks, "
                "E1/E6/E11 are typically highest risk; E4 and E9 are lower risk but still apply. "
                "The overall verdict equals the worst single-category finding. "
                "SPECIFICITY REQUIREMENT: Brittle requires BOTH (a) a concrete evasion path "
                "against THIS framework's specific detection mechanism AND (b) LOW or TRIVIAL "
                "adversary cost — meaning the evasion can be executed without significant "
                "operational overhead, cross-account coordination burden, or efficiency loss "
                "to the adversary's campaign. "
                "ADVERSARY COST ASSESSMENT FOR DETECTION FRAMEWORKS: "
                "Consider coordination complexity (how much cross-account synchronization is needed?), "
                "operational intelligence cost (must the adversary know the algorithm's parameters?), "
                "and campaign efficiency loss (does evading the detector require the adversary to "
                "reduce coordination effectiveness, spreading across more accounts, or slowing down?). "
                "If evasion requires the adversary to meaningfully reduce campaign efficiency "
                "or invest in significant operational complexity, that is MEDIUM cost = Conditionally Robust. "
                "Brittle is reserved for evasions that are cheap, invisible to the adversary's own goals, "
                "and require no meaningful coordination burden."
            ),
        }

        llm_response = llm.generate(
            system_prompt=RED_TEAM_SYSTEM_PROMPT,
            user_message=json.dumps(llm_input, indent=2, default=str),
            max_tokens=6000,
        )
        llm_elapsed = round(time.time() - t0, 2)

        llm_content = llm_response["content"]
        try:
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if "```" in clean:
                clean = clean.rsplit("```", 1)[0]
            report = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError):
            worst = "Conditionally Robust" if not flagged else "Conditionally Robust"
            report = {
                "framework_name": framework_name,
                "overall_verdict": worst,
                "verdict_rationale": f"LLM parse failed; deterministic fallback from pre-screens {flagged}",
                "primary_weakness": flagged[0] if flagged else "E11",
                "hardening_steps": [
                    f"Address {c}: {pre_screens[c]['evidence']}" for c in flagged
                ],
                "evasion_assessments": [],
                "penetration_difficulty_score": 0.55,
                "confidence_score": 0.40,
                "known_limitations": ["LLM parse failed; full E1–E12 unavailable"],
            }

        # L1 override: MEDIUM pre-screened signals floor verdict at Conditionally Robust
        if flagged and report.get("overall_verdict") == "Robust":
            report["overall_verdict"] = "Conditionally Robust"
            report["verdict_rationale"] = (
                f"L1 override: deterministic pre-screens flagged {flagged} at MEDIUM severity; "
                f"verdict floored at Conditionally Robust. "
                + report.get("verdict_rationale", "")
            )

        verdict = report.get("overall_verdict", "Conditionally Robust")
        primary_weakness = report.get("primary_weakness", "UNKNOWN")
        pds = float(report.get("penetration_difficulty_score", 0.55))

        print(
            f"[Red-Team] Framework verdict: {verdict} | "
            f"Primary: {primary_weakness} | PDS: {pds:.2f}"
        )

        # ── Emit red_team_report artifact ────────────────────────────────────
        result_content = {
            "task_id": task_id,
            "phase": self.phase,
            "evaluation_mode": "framework_stress_test",
            "framework_name": framework_name,
            "framework_dict": framework_dict,
            "sandbox_confirmation": True,
            "overall_verdict": verdict,
            "primary_weakness": primary_weakness,
            "hardening_steps": report.get("hardening_steps", []),
            "evasion_assessments": report.get("evasion_assessments", []),
            "penetration_difficulty_score": pds,
            "verdict_rationale": report.get("verdict_rationale", ""),
            "deterministic_prescreens": pre_screens,
            "cdi_query_record": cdi_query_record,
            "lineage": {
                "capability_bundle_id": capability_bundle_id,
                "llm_elapsed_sec": llm_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
            },
        }

        confidence = float(report.get("confidence_score", 0.65))
        artifact = create_artifact(
            artifact_type="red_team_report",
            producing_agent="red_team",
            phase=self.phase,
            content=result_content,
            provenance=[capability_bundle_id],
            confidence_score=min(0.95, max(0.1, confidence)),
            known_limitations=report.get(
                "known_limitations",
                [
                    "Sandbox evaluation only — no live production signal available",
                    "E5 assessment requires segment-level data not available in framework spec",
                    "E8 assessment is theoretical without pipeline run history",
                ],
            ),
        )
        path = write_artifact(artifact)
        print(f"[Red-Team] Framework report written: {artifact['artifact_id']}")

        write_red_team_entry(artifact)

        updater = CDIUpdater(agent_name="red_team", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {
            "red_team_report_id": artifact["artifact_id"],
            "path": str(path),
            "verdict": verdict,
            "primary_weakness": primary_weakness,
            "hardening_steps": report.get("hardening_steps", []),
            "penetration_difficulty_score": pds,
        }
