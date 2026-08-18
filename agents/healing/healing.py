"""
Healing Agent — agents/healing/healing.py

Phase 2 full implementation. Cross-domain pipeline repair via the canonical
five domains (Medicine, Materials Science, Systems Biology, Military Logistics,
Law) sourced from CDI Layer cross_domain_analogues with failure_classes tagging.

Five-step cycle:
  1. Characterize failure (read Diagnostic artifact)
  2. Retrieve repair strategies from CDI Layer (mandatory query)
  3. Score: prior_success × precondition_match × reversibility_weight × (1 / blast_radius)
  4. Select (or synthesize); apply lowest-blast-radius reversible first
  5. Verify against Diagnostic assertions; record telemetry triple

Draft PRs only — never production merge without Confirmation Gate sign-off.

Maximum-Capacity escalation: only escalate to operator when ALL SIX conditions
hold simultaneously (canonical from system prompt § Healing Agent).

Safety-class exception: Design Invariant violations, audit-trail corruption
risks, and L4 failures escalate IMMEDIATELY. MC gating does NOT apply.
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.artifact import create_artifact, write_artifact, read_artifact
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

BASE = Path(__file__).resolve().parents[2]
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
HEALING_LOG = AIMS_MODE_A_DIR / "healing_log.jsonl"
DRAFTS_DIR = BASE / "healing_drafts"

# ═══════════════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS — canonical from system prompt
# ═══════════════════════════════════════════════════════════════════════════════

REVERSIBILITY_WEIGHT = 1.5   # weighted heavily per spec
MAX_ATTEMPTS = 3
PER_FAILURE_BUDGET_SECONDS = 300
NO_PROGRESS_WINDOW = 2       # K = 2: last 2 attempts producing no improvement → no-progress
SAFETY_CLASS_LEVELS = {"L4"}


# ═══════════════════════════════════════════════════════════════════════════════
# HEALING AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class HealingAgent:
    """Cross-domain repair. Draft PRs only. MC-gated escalation."""

    def __init__(self, phase: int = 2):
        self.phase = phase
        self.attempts_per_failure: dict[str, list[dict]] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ──────────────────────────────────────────────────────────────────────────

    def run(
        self,
        capability_bundle_id: str,
        diagnostic_artifact_id: str,
        baseline_path: Optional[str] = None,
        current_path: Optional[str] = None,
        monitored_column: Optional[str] = None,
        diagnostic_agent=None,
    ) -> dict:
        """
        Execute the five-step healing cycle.

        Args:
            capability_bundle_id: Orchestrator-emitted bundle for this task
            diagnostic_artifact_id: the L1/L2 finding triggering healing
            baseline_path: parquet of last known good
            current_path: parquet of the failed pipeline output
            diagnostic_agent: live DiagnosticAgent instance for verify step
                              (passed in by the Phase 2 runner)

        Returns dict with:
            healing_record_id, verification_result, strategy_applied,
            attempts, mc_conditions, escalated
        """
        cb = read_artifact(capability_bundle_id)
        task_id = cb["content"]["task_id"]

        diagnostic = read_artifact(diagnostic_artifact_id)
        diag_content = diagnostic["content"]
        failure_class = diag_content.get("failure_class", "ambiguity")
        pipeline_id = diag_content.get("pipeline_id", "unknown")
        level = diag_content.get("level", "L0")

        # ── SAFETY-CLASS EXCEPTION ──
        if level in SAFETY_CLASS_LEVELS:
            return self._safety_class_escalate(
                capability_bundle_id, diagnostic_artifact_id, diagnostic, task_id,
            )

        # ── STEP 1: CHARACTERIZE ──
        characterization = self._characterize_failure(diagnostic)
        print(f"[Healing] Characterized: {characterization['failure_class']} "
              f"(pipeline={pipeline_id})")

        # ── STEP 2: RETRIEVE STRATEGIES (CDI Layer mandatory query) ──
        reader = CDIReader(agent_name="healing", task_id=task_id)
        strategies = reader.get_repair_strategies(failure_class)
        if not strategies:
            # Fallback to broader analogue search if no failure-class match
            analogues = reader.get_analogues_for_problem(
                f"pipeline {failure_class} repair"
            )
            strategies = []
            for a in analogues:
                for s in a.get("repair_strategies", []):
                    strategies.append({**s, "domain": a["source_domain"],
                                       "analogue_id": a["id"]})

        domains_consulted = sorted(set(s["domain"] for s in strategies))
        print(f"[Healing] Strategies retrieved: {len(strategies)} across {len(domains_consulted)} "
              f"domains: {domains_consulted}")

        # ── STEP 3: SCORE ──
        scored = self._score_strategies(strategies, characterization)
        if not scored:
            return self._escalate(
                reason="no_strategies_available",
                task_id=task_id, capability_bundle_id=capability_bundle_id,
                diagnostic_artifact_id=diagnostic_artifact_id,
                characterization=characterization,
                attempts=[], mc_conditions=self._mc_conditions(
                    attempts=[], failure_class=failure_class,
                    started_at=time.time(), root_chain_computed=True,
                    strategies_remaining=0,
                ),
            )

        # ── STEP 4 + 5: SELECT → APPLY → VERIFY (loop up to MAX_ATTEMPTS) ──
        started_at = time.time()
        attempts: list[dict] = []
        applied_strategy = None
        final_verify = None
        applied_paths: list[str] = []

        for attempt_idx in range(MAX_ATTEMPTS):
            if not scored:
                break

            # Sort by score; reversibility-weighted, lowest-blast-radius-first preference
            scored.sort(key=lambda s: (-s["score"], s["blast_radius"]))
            strategy = scored.pop(0)
            print(f"[Healing] Attempt {attempt_idx + 1}/{MAX_ATTEMPTS} → "
                  f"{strategy['name']} (domain={strategy['domain']}, "
                  f"score={strategy['score']:.3f})")

            # APPLY (draft mode)
            draft = self._apply_strategy_draft(
                strategy=strategy, pipeline_id=pipeline_id,
                baseline_path=baseline_path, current_path=current_path,
                attempt_idx=attempt_idx,
            )
            applied_paths.append(draft["draft_parquet_path"])

            # VERIFY — re-run Diagnostic against the draft
            verify = self._verify_against_diagnostic(
                pipeline_id=pipeline_id,
                baseline_path=baseline_path,
                draft_parquet_path=draft["draft_parquet_path"],
                schema_contract=diag_content.get("schema_contract"),
                monitored_column=monitored_column,
                diagnostic_agent=diagnostic_agent,
            )

            attempt = {
                "attempt_idx": attempt_idx,
                "strategy_name": strategy["name"],
                "domain": strategy["domain"],
                "analogue_id": strategy["analogue_id"],
                "score": strategy["score"],
                "draft_parquet_path": draft["draft_parquet_path"],
                "draft_pr_path": draft["draft_pr_path"],
                "verification": verify,
            }
            attempts.append(attempt)

            # Feedback the result to Diagnostic Agent (updates retry count)
            if diagnostic_agent is not None:
                diagnostic_agent.record_healing_attempt(
                    pipeline_id, verify["verification"]
                )

            if verify["verification"] == "PASS":
                applied_strategy = strategy
                final_verify = verify
                print(f"[Healing] PASS: {strategy['name']} reduced "
                      f"level {verify.get('initial_level')} → {verify['final_level']}")
                break

            print(f"[Healing] FAIL: {strategy['name']} did not restore nominal state "
                  f"(level still {verify['final_level']})")

        # ── MC CHECK ──
        elapsed = time.time() - started_at
        budget_exhausted = elapsed > PER_FAILURE_BUDGET_SECONDS
        mc = self._mc_conditions(
            attempts=attempts, failure_class=failure_class,
            started_at=started_at, root_chain_computed=True,
            strategies_remaining=len(scored), budget_exhausted=budget_exhausted,
        )

        # ── EMIT HEALING RECORD ──
        record_content = {
            "task_id": task_id,
            "pipeline_id": pipeline_id,
            "failure_class": failure_class,
            "characterization": characterization,
            "strategies_evaluated": (
                # Strategies still in the queue (un-tried)
                [
                    {"name": s["name"], "domain": s["domain"],
                     "score": s["score"], "analogue_id": s["analogue_id"],
                     "outcome": "not_attempted"}
                    for s in scored
                ]
                # Plus strategies that were tried
                + [
                    {"name": a["strategy_name"], "domain": a["domain"],
                     "score": a["score"], "analogue_id": a["analogue_id"],
                     "outcome": a["verification"]["verification"]}
                    for a in attempts
                ]
            ),
            "domains_consulted": domains_consulted,
            "attempts": attempts,
            "strategy_applied": applied_strategy["name"] if applied_strategy else None,
            "verification_result": final_verify["verification"] if final_verify else "FAIL",
            "draft_pr_path": attempts[-1]["draft_pr_path"] if attempts else None,
            "generation_mode": "ANALOGICAL",
            "mc_conditions": mc,
            "escalated": mc["all_six_hold"],
            "minimum_causal_chain": diag_content.get("minimum_causal_chain", []),
            "elapsed_seconds": elapsed,
        }
        confidence = (
            applied_strategy["score"] if applied_strategy
            else (max((s["score"] for s in scored), default=0.0))
        )
        limitations = [
            "Draft PR only — production merge requires Confirmation Gate sign-off.",
            "Reversibility scoring uses analogue-declared values; runtime reversibility not re-measured per attempt.",
        ]
        if mc["all_six_hold"]:
            limitations.append("All 6 MC conditions held — operator escalation triggered.")

        artifact = create_artifact(
            artifact_type="healing_record",
            producing_agent="healing",
            phase=self.phase,
            content=record_content,
            provenance=[capability_bundle_id, diagnostic_artifact_id],
            confidence_score=min(max(confidence, 0.0), 1.0),
            known_limitations=limitations,
        )
        path = write_artifact(artifact)

        try:
            from lib.second_brain import write_healing_entry
            write_healing_entry(artifact)
        except Exception as e:
            print(f"[Healing] Vault write failed (non-fatal): {e}")

        # CDI: record non-activation
        updater = CDIUpdater(agent_name="healing", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        # AIMS Mode A
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "event_type": "HEALING_CYCLE_COMPLETE",
            "healing_record_id": artifact["artifact_id"],
            "diagnostic_artifact_id": diagnostic_artifact_id,
            "pipeline_id": pipeline_id,
            "failure_class": failure_class,
            "strategy_applied": record_content["strategy_applied"],
            "verification_result": record_content["verification_result"],
            "attempts": len(attempts),
            "escalated": record_content["escalated"],
            "elapsed_seconds": round(elapsed, 2),
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        with open(HEALING_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return {
            "healing_record_id": artifact["artifact_id"],
            "path": str(path),
            "verification_result": record_content["verification_result"],
            "strategy_applied": record_content["strategy_applied"],
            "attempts": len(attempts),
            "mc_conditions": mc,
            "escalated": record_content["escalated"],
        }

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1 — CHARACTERIZE
    # ──────────────────────────────────────────────────────────────────────────

    def _characterize_failure(self, diagnostic: dict) -> dict:
        """Map Diagnostic finding to domain-neutral failure characterization."""
        c = diagnostic["content"]
        return {
            "failure_class": c.get("failure_class", "ambiguity"),
            "psi_score": c.get("psi_score"),
            "schema_passed": c.get("schema_passed", True),
            "schema_violations": c.get("schema_violations", []),
            "latency_ratio": c.get("latency_ratio"),
            "diagnostic_level": c.get("level"),
            "minimum_causal_chain": c.get("minimum_causal_chain", []),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 3 — SCORE
    # ──────────────────────────────────────────────────────────────────────────

    def _score_strategies(
        self, strategies: list[dict], characterization: dict,
    ) -> list[dict]:
        """
        Score each candidate strategy:
            score = prior_success × precondition_match × (reversibility ^ weight)
                    × (1 / max(blast_radius, 0.05))

        Returns list with new 'score' field added.
        """
        scored = []
        for s in strategies:
            prior = float(s.get("prior_success", 0.5))
            reversibility = float(s.get("reversibility", 0.5))
            blast = max(float(s.get("blast_radius", 0.5)), 0.05)
            precondition_match = self._precondition_match(s, characterization)

            score = (
                prior
                * precondition_match
                * (reversibility ** REVERSIBILITY_WEIGHT)
                * (1.0 / blast)
            )
            scored.append({**s, "score": score, "precondition_match": precondition_match})
        return scored

    def _precondition_match(self, strategy: dict, characterization: dict) -> float:
        """
        Score precondition fit on [0, 1].
        Phase 2 baseline: lightweight keyword-match against characterization signals.
        Phase 4 expansion: use Few-Shot Bank exemplars for finer calibration.
        """
        preconditions = strategy.get("preconditions", [])
        if not preconditions:
            return 0.5  # neutral if unspecified

        ctx_text = " ".join([
            str(characterization.get("failure_class", "")),
            "schema" if not characterization.get("schema_passed", True) else "",
            "latency" if characterization.get("latency_ratio") and characterization["latency_ratio"] > 1.5 else "",
            "drift" if (characterization.get("psi_score") or 0) > 0.10 else "",
            "single component" if characterization.get("failure_class") == "structural_break" else "",
            "historical baseline" if characterization.get("failure_class") != "ambiguity" else "",
            "isolable" if characterization.get("failure_class") in ("contamination", "gradual_degradation") else "",
            "log" if characterization.get("minimum_causal_chain") else "",
            "Few-Shot Bank" if characterization.get("failure_class") != "ambiguity" else "",
        ]).lower()

        match_count = 0
        for pc in preconditions:
            keywords = [w for w in pc.lower().split() if len(w) > 4]
            if any(kw in ctx_text for kw in keywords):
                match_count += 1
        return match_count / len(preconditions)

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 4 — APPLY (draft mode)
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_strategy_draft(
        self, strategy: dict, pipeline_id: str,
        baseline_path: Optional[str], current_path: Optional[str],
        attempt_idx: int,
    ) -> dict:
        """
        Apply the strategy in draft mode. Writes a corrected parquet to
        healing_drafts/<pipeline_id>/<attempt>_<strategy>.parquet, plus a
        markdown PR description.

        NEVER writes to production paths. Strategy dispatch by name.
        """
        import pandas as pd

        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        pipeline_drafts = DRAFTS_DIR / pipeline_id
        pipeline_drafts.mkdir(parents=True, exist_ok=True)

        draft_parquet = pipeline_drafts / f"attempt_{attempt_idx}_{strategy['name']}.parquet"
        draft_pr = pipeline_drafts / f"attempt_{attempt_idx}_{strategy['name']}_PR.md"

        if current_path is None:
            # Degenerate case — no data to transform; write empty marker
            draft_parquet.write_bytes(b"")
            draft_pr.write_text("# Healing draft\n\nNo current_path provided.\n", encoding="utf-8")
            return {"draft_parquet_path": str(draft_parquet),
                    "draft_pr_path": str(draft_pr)}

        df = pd.read_parquet(current_path)
        baseline_df = pd.read_parquet(baseline_path) if baseline_path else None

        applicator = self._strategy_applicators().get(strategy["name"])
        if applicator is None:
            # Unknown strategy — produce identity (no-op) draft + flag
            corrected = df.copy()
            note = f"No applicator registered for '{strategy['name']}'. Identity draft."
        else:
            corrected, note = applicator(df, baseline_df, strategy)

        corrected.to_parquet(draft_parquet, index=False)

        # PR description
        pr_text = self._build_pr_description(
            strategy=strategy, pipeline_id=pipeline_id,
            attempt_idx=attempt_idx, df_before=df, df_after=corrected,
            applicator_note=note,
        )
        draft_pr.write_text(pr_text, encoding="utf-8")

        return {
            "draft_parquet_path": str(draft_parquet),
            "draft_pr_path": str(draft_pr),
        }

    def _strategy_applicators(self) -> dict[str, Callable]:
        """Dispatch table: strategy_name → applicator(df, baseline_df, strategy)."""
        return {
            "differential_diagnosis_triage": self._apply_differential_diagnosis,
            "first_do_no_harm_observe":      self._apply_first_do_no_harm,
            "stress_concentrator_quarantine": self._apply_stress_concentrator,
            "fail_safe_default_substitution": self._apply_fail_safe_default,
            "homeostatic_smoothing_correction": self._apply_homeostatic_smoothing,
            "graceful_apoptosis_record_drop":   self._apply_graceful_apoptosis,
            "fallback_routing_degraded_mode":   self._apply_fallback_routing,
            "ooda_accelerated_monitoring":      self._apply_ooda_observation,
            "proximate_root_cause_tracing":     self._apply_proximate_root_tracing,
            "precedent_retrieval_remediation":  self._apply_precedent_retrieval,
        }

    # ── strategy applicators (data transformations) ───────────────────────────

    def _apply_differential_diagnosis(self, df, baseline_df, strategy):
        """Identify most-shifted column; replace its values with baseline distribution sample."""
        import numpy as np
        corrected = df.copy()
        if baseline_df is None or baseline_df.empty:
            return corrected, "no baseline; identity draft"
        # Find column with largest mean-shift
        numeric_cols = [c for c in df.columns
                        if c in baseline_df.columns
                        and df[c].dtype.kind in "fiu"]
        if not numeric_cols:
            return corrected, "no numeric columns; identity draft"
        shifts = {c: abs(df[c].mean() - baseline_df[c].mean()) /
                     max(abs(baseline_df[c].std()), 1e-6)
                  for c in numeric_cols}
        target = max(shifts, key=shifts.get)
        sample = baseline_df[target].dropna().sample(
            n=len(corrected), replace=True, random_state=42
        ).values
        corrected[target] = sample
        return corrected, f"resampled '{target}' from baseline (shift={shifts[target]:.2f}σ)"

    def _apply_first_do_no_harm(self, df, baseline_df, strategy):
        """Observe-only: identity draft with no transformation."""
        return df.copy(), "observe-only; no transformation applied"

    def _apply_stress_concentrator(self, df, baseline_df, strategy):
        """Quarantine the column with the most schema/null issues; substitute with baseline median."""
        corrected = df.copy()
        if baseline_df is None:
            return corrected, "no baseline; identity draft"
        worst_col = None
        worst_null_rate = 0.0
        for c in df.columns:
            null_rate = df[c].isna().mean()
            if null_rate > worst_null_rate:
                worst_null_rate = null_rate
                worst_col = c
        if worst_col and worst_null_rate > 0 and worst_col in baseline_df.columns:
            if df[worst_col].dtype.kind in "fiu":
                corrected[worst_col] = corrected[worst_col].fillna(baseline_df[worst_col].median())
            else:
                mode_val = baseline_df[worst_col].mode()
                if len(mode_val):
                    corrected[worst_col] = corrected[worst_col].fillna(mode_val.iloc[0])
            return corrected, f"quarantined '{worst_col}' (null_rate={worst_null_rate:.2%})"
        return corrected, "no quarantine target; identity draft"

    def _apply_fail_safe_default(self, df, baseline_df, strategy):
        """Replace nulls in all numeric columns with baseline medians; categorical with baseline mode."""
        corrected = df.copy()
        if baseline_df is None:
            corrected = corrected.fillna(0)
            return corrected, "no baseline; filled NaN with 0"
        substitutions = []
        for c in corrected.columns:
            if c not in baseline_df.columns:
                continue
            if corrected[c].isna().any():
                if corrected[c].dtype.kind in "fiu":
                    val = baseline_df[c].median()
                    corrected[c] = corrected[c].fillna(val)
                    substitutions.append(f"{c}=median")
                else:
                    mode_val = baseline_df[c].mode()
                    if len(mode_val):
                        corrected[c] = corrected[c].fillna(mode_val.iloc[0])
                        substitutions.append(f"{c}=mode")
        return corrected, f"fail-safe defaults: {', '.join(substitutions[:5])}"

    def _apply_homeostatic_smoothing(self, df, baseline_df, strategy):
        """For each numeric column, blend toward baseline mean with weight 0.5 (re-baselining)."""
        corrected = df.copy()
        if baseline_df is None:
            return corrected, "no baseline; identity draft"
        smoothed = []
        for c in corrected.columns:
            if c in baseline_df.columns and corrected[c].dtype.kind in "fiu":
                target_mean = baseline_df[c].mean()
                current_mean = corrected[c].mean()
                shift = target_mean - current_mean
                corrected[c] = corrected[c] + 0.5 * shift
                smoothed.append(c)
        return corrected, f"smoothed toward baseline mean: {smoothed[:5]}"

    def _apply_graceful_apoptosis(self, df, baseline_df, strategy):
        """Drop rows that contain nulls in any required column; preserves audit count."""
        n_before = len(df)
        # Drop rows where ALL values are null OR any string column has empty string
        corrected = df.dropna(how="all").copy()
        # Also drop rows with null in any column that has >50% non-null in baseline (i.e., normally required)
        if baseline_df is not None:
            for c in baseline_df.columns:
                if c not in corrected.columns:
                    continue
                baseline_non_null = 1.0 - baseline_df[c].isna().mean()
                if baseline_non_null > 0.5:
                    corrected = corrected[corrected[c].notna()]
        n_after = len(corrected)
        return corrected, f"graceful apoptosis: dropped {n_before - n_after} corrupted rows"

    def _apply_fallback_routing(self, df, baseline_df, strategy):
        """Substitute the entire dataframe with the baseline (degraded-mode operation)."""
        if baseline_df is None:
            return df.copy(), "no baseline available for fallback; identity draft"
        corrected = baseline_df.copy()
        corrected["_healing_degraded_mode"] = True
        return corrected, f"fallback-routed to baseline snapshot ({len(corrected)} rows)"

    def _apply_ooda_observation(self, df, baseline_df, strategy):
        """OODA: identity transform; the actual change is monitoring frequency, not data."""
        return df.copy(), "OODA cycle: monitoring increased; no data transformation"

    def _apply_proximate_root_tracing(self, df, baseline_df, strategy):
        """Walk back: find earliest row index where divergence from baseline begins; truncate after."""
        import numpy as np
        corrected = df.copy()
        if baseline_df is None or baseline_df.empty:
            return corrected, "no baseline; identity draft"
        # Use first numeric column as the trace target
        numeric_cols = [c for c in df.columns
                        if c in baseline_df.columns and df[c].dtype.kind in "fiu"]
        if not numeric_cols:
            return corrected, "no numeric trace column; identity draft"
        target = numeric_cols[0]
        baseline_mean = baseline_df[target].mean()
        baseline_std = max(baseline_df[target].std(), 1e-6)
        # Find first index where moving window mean exceeds 2σ from baseline
        window = max(min(50, len(corrected) // 10), 1)
        rolling = corrected[target].rolling(window=window, min_periods=1).mean()
        deviation = (rolling - baseline_mean).abs() / baseline_std
        breach_idx = deviation[deviation > 2.0].index
        if len(breach_idx) == 0:
            return corrected, f"no divergence found in '{target}'; identity draft"
        root_idx = breach_idx[0]
        # Replace divergent tail with baseline-mean values for the column
        corrected.loc[root_idx:, target] = baseline_mean
        return corrected, f"traced root to row {root_idx}; mean-substituted tail of '{target}'"

    def _apply_precedent_retrieval(self, df, baseline_df, strategy):
        """Replay baseline statistics as the corrected output (precedent = prior good state)."""
        if baseline_df is None:
            return df.copy(), "no precedent baseline available; identity draft"
        # Use baseline as the precedent template
        corrected = df.copy()
        for c in corrected.columns:
            if c in baseline_df.columns and corrected[c].dtype.kind in "fiu":
                target_mean = baseline_df[c].mean()
                target_std = baseline_df[c].std()
                if target_std > 0:
                    # Re-center current distribution on baseline
                    current_mean = corrected[c].mean()
                    corrected[c] = corrected[c] + (target_mean - current_mean)
        return corrected, "precedent-retrieved: recentered columns on baseline means"

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 5 — VERIFY
    # ──────────────────────────────────────────────────────────────────────────

    def _verify_against_diagnostic(
        self, pipeline_id: str, baseline_path: str, draft_parquet_path: str,
        schema_contract: Optional[dict], diagnostic_agent,
        monitored_column: Optional[str] = None,
    ) -> dict:
        """
        Re-run Diagnostic Agent against the corrected parquet.
        PASS if the verify run reduces to L0 (nominal) or L1 (post-healing
        residual). L2+ → FAIL → next strategy.
        """
        if diagnostic_agent is None:
            return {"verification": "FAIL",
                    "reason": "no diagnostic_agent provided for verify step",
                    "final_level": "L2"}

        result = diagnostic_agent.monitor_pipeline(
            pipeline_id=f"{pipeline_id}_verify",
            baseline_path=baseline_path,
            current_path=draft_parquet_path,
            monitored_column=monitored_column,
            schema_contract=schema_contract,
            emit=False,  # verification probe — don't pollute the log
        )

        verification = "PASS" if result["level"] in {"L0", "L1"} else "FAIL"
        return {
            "verification": verification,
            "final_level": result["level"],
            "final_status": result["status"],
            "psi_post": result.get("psi_score"),
            "schema_passed_post": result.get("schema_passed"),
            "failure_class_post": result.get("failure_class"),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # MAXIMUM-CAPACITY CONDITIONS (6 — all must hold to escalate)
    # ──────────────────────────────────────────────────────────────────────────

    def _mc_conditions(
        self, attempts: list[dict], failure_class: str,
        started_at: float, root_chain_computed: bool,
        strategies_remaining: int = 0, budget_exhausted: bool = False,
    ) -> dict:
        """
        Canonical 6 from the system prompt § Healing Agent:
          (a) Strategy exhaustion
          (b) Retry exhaustion
          (c) Synthesis exhaustion
          (d) Budget exhaustion
          (e) No-progress
          (f) Root reached or unreachable
        """
        # (a) strategy exhaustion — no more applicable strategies in queue
        strategy_exhaustion = (strategies_remaining == 0)

        # (b) retry exhaustion — at or above MAX_ATTEMPTS
        retry_exhaustion = (len(attempts) >= MAX_ATTEMPTS)

        # (c) synthesis exhaustion — Phase 2 baseline: any attempt counts as
        # a synthesis exploration; if all attempts fail, treat as exhausted
        synthesis_exhaustion = (
            len(attempts) >= 2
            and all(a["verification"]["verification"] != "PASS" for a in attempts)
        )

        # (d) budget exhaustion
        budget = (time.time() - started_at) > PER_FAILURE_BUDGET_SECONDS or budget_exhausted

        # (e) no-progress — last K attempts produced no measurable improvement
        no_progress = self._check_no_progress(attempts, K=NO_PROGRESS_WINDOW)

        # (f) root reached or unreachable — minimum causal chain was computed,
        # remediation at root attempted (or root outside system authority for ambiguity)
        root = root_chain_computed and (
            failure_class == "ambiguity"
            or any(a["verification"]["verification"] != "PASS" for a in attempts)
        )

        all_hold = all([
            strategy_exhaustion, retry_exhaustion, synthesis_exhaustion,
            budget, no_progress, root,
        ])

        return {
            "a_strategy_exhaustion": strategy_exhaustion,
            "b_retry_exhaustion": retry_exhaustion,
            "c_synthesis_exhaustion": synthesis_exhaustion,
            "d_budget_exhaustion": budget,
            "e_no_progress": no_progress,
            "f_root_reached_or_unreachable": root,
            "all_six_hold": all_hold,
        }

    def _check_no_progress(self, attempts: list[dict], K: int = 2) -> bool:
        """Last K attempts produced no PSI reduction."""
        if len(attempts) < K:
            return False
        recent = attempts[-K:]
        psis = [a["verification"].get("psi_post") for a in recent]
        psis = [p for p in psis if p is not None]
        if len(psis) < 2:
            return False
        # No measurable improvement if PSI did not strictly decrease across the window
        return not (psis[-1] < psis[0])

    # ──────────────────────────────────────────────────────────────────────────
    # ESCALATION PATHS
    # ──────────────────────────────────────────────────────────────────────────

    def _safety_class_escalate(
        self, capability_bundle_id: str, diagnostic_artifact_id: str,
        diagnostic: dict, task_id: str,
    ) -> dict:
        """L4 / safety-class: immediate escalation, MC gating BYPASSED."""
        content = {
            "task_id": task_id,
            "pipeline_id": diagnostic["content"].get("pipeline_id", "unknown"),
            "failure_class": diagnostic["content"].get("failure_class", "ambiguity"),
            "diagnostic_level": diagnostic["content"].get("level"),
            "escalation_reason": "safety_class_immediate",
            "mc_bypassed": True,
            "strategy_applied": None,
            "verification_result": "ESCALATED",
            "generation_mode": "ANALOGICAL",
            "attempts": [],
            "minimum_causal_chain": diagnostic["content"].get("minimum_causal_chain", []),
            "escalated": True,
        }
        artifact = create_artifact(
            artifact_type="healing_record",
            producing_agent="healing",
            phase=self.phase,
            content=content,
            provenance=[capability_bundle_id, diagnostic_artifact_id],
            confidence_score=1.0,
            known_limitations=[
                "Safety-class exception: MC gating bypassed per system prompt.",
                "Operator action required before any further autonomous action on this pipeline.",
            ],
        )
        path = write_artifact(artifact)
        try:
            from lib.second_brain import write_healing_entry
            write_healing_entry(artifact)
        except Exception as e:
            print(f"[Healing] Vault write failed (non-fatal): {e}")

        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "event_type": "HEALING_SAFETY_CLASS_ESCALATION",
            "healing_record_id": artifact["artifact_id"],
            "diagnostic_artifact_id": diagnostic_artifact_id,
            "pipeline_id": content["pipeline_id"],
            "diagnostic_level": content["diagnostic_level"],
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        with open(HEALING_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return {
            "healing_record_id": artifact["artifact_id"],
            "path": str(path),
            "verification_result": "ESCALATED",
            "strategy_applied": None,
            "attempts": 0,
            "escalated": True,
            "mc_bypassed": True,
        }

    def _escalate(
        self, reason: str, task_id: str, capability_bundle_id: str,
        diagnostic_artifact_id: str, characterization: dict,
        attempts: list, mc_conditions: dict,
    ) -> dict:
        """MC-gated operator escalation (all 6 conditions hold)."""
        content = {
            "task_id": task_id,
            "escalation_reason": reason,
            "characterization": characterization,
            "attempts": attempts,
            "mc_conditions": mc_conditions,
            "strategy_applied": None,
            "verification_result": "ESCALATED",
            "escalated": True,
        }
        artifact = create_artifact(
            artifact_type="healing_record",
            producing_agent="healing",
            phase=self.phase,
            content=content,
            provenance=[capability_bundle_id, diagnostic_artifact_id],
            confidence_score=0.0,
            known_limitations=[f"MC-gated escalation: {reason}"],
        )
        path = write_artifact(artifact)
        return {
            "healing_record_id": artifact["artifact_id"],
            "path": str(path),
            "verification_result": "ESCALATED",
            "escalated": True,
            "mc_conditions": mc_conditions,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PR DESCRIPTION
    # ──────────────────────────────────────────────────────────────────────────

    def _build_pr_description(
        self, strategy: dict, pipeline_id: str, attempt_idx: int,
        df_before, df_after, applicator_note: str,
    ) -> str:
        return (
            f"# Healing Draft PR — `{pipeline_id}` (attempt {attempt_idx + 1})\n\n"
            f"> **Summary:** {strategy['name']} ({strategy['domain']}) applied as draft repair.\n\n"
            f"## Strategy\n\n"
            f"- **Name:** `{strategy['name']}`\n"
            f"- **Source domain:** {strategy['domain']}\n"
            f"- **CDI analogue:** `{strategy.get('analogue_id', 'n/a')}`\n"
            f"- **Prior success:** {strategy.get('prior_success', 0):.2f}\n"
            f"- **Reversibility:** {strategy.get('reversibility', 0):.2f}\n"
            f"- **Blast radius:** {strategy.get('blast_radius', 0):.2f}\n"
            f"- **Score:** {strategy.get('score', 0):.3f}\n\n"
            f"## Applicator notes\n\n{applicator_note}\n\n"
            f"## Before/After\n\n"
            f"| metric | before | after |\n|---|---|---|\n"
            f"| rows | {len(df_before)} | {len(df_after)} |\n"
            f"| cols | {len(df_before.columns)} | {len(df_after.columns)} |\n\n"
            f"## Governance\n\n"
            f"- Generation mode: **ANALOGICAL**\n"
            f"- Production merge: **NOT PERFORMED** — Confirmation Gate sign-off required.\n"
            f"- This PR is a draft and may be replayed, rejected, or superseded.\n"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    h = HealingAgent(phase=2)
    print("Healing Agent — Phase 2 self-test")
    print(f"  Strategy applicators registered: {len(h._strategy_applicators())}")
    print(f"  MAX_ATTEMPTS={MAX_ATTEMPTS}, BUDGET={PER_FAILURE_BUDGET_SECONDS}s")
    print(f"  Reversibility weight: {REVERSIBILITY_WEIGHT}")
    print("  Ready.")
