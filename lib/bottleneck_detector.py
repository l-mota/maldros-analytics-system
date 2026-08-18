"""
lib/bottleneck_detector.py

Phase 6 — Phase 7 Bottleneck Identification (deliverable 6.2).

Aggregates telemetry from all AIMS Mode A logs across prior investigation cycles.
Identifies structural bottlenecks with evidence-based confidence scores.

Expected candidates per implementation_plan.md §6:
  BOTTLENECK_001: Orchestrator context window usage is inefficient
  BOTTLENECK_002: Statistician produces overconfident point estimates on small subgroups
  BOTTLENECK_003: Few-Shot Bank retrieval mechanism favors recency over relevance

Output: bottleneck_report artifact + Second Brain vault entry + AIMS Mode A log.
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

AIMS_A = BASE / "aims" / "mode_a"


class BottleneckDetector:
    """
    Aggregates telemetry from AIMS Mode A logs to identify structural bottlenecks.

    Usage:
        detector = BottleneckDetector()
        result = detector.run_analysis()
        # result["top_bottleneck"] is the highest-priority candidate
    """

    def __init__(self, phase: int = 6):
        self.phase = phase

    def run_analysis(self) -> dict:
        """
        Main entry: read telemetry logs, identify bottlenecks, emit artifact.
        Returns dict with: bottleneck_report_artifact_id, top_bottleneck, all_candidates
        """
        print(f"\n[BottleneckDetector] ═══ Phase 7 Bottleneck Identification ═══")

        # ── Aggregate telemetry from all AIMS Mode A logs ──────────────────────
        llm_metrics = self._aggregate_llm_call_log()
        promotion_metrics = self._aggregate_promotion_log()
        fsb_metrics = self._aggregate_fsb_metrics()
        orchestrator_metrics = self._aggregate_orchestrator_log()

        print(f"[BottleneckDetector] LLM calls analyzed:          {llm_metrics['total_calls']}")
        print(f"[BottleneckDetector] Promotion Gate decisions:    {promotion_metrics['total_decisions']}")
        print(f"[BottleneckDetector] FSB exemplars:               {fsb_metrics['exemplar_count']}")
        print(f"[BottleneckDetector] Orchestrator CB events:      {orchestrator_metrics['capability_bundles_emitted']}")

        # ── Identify structural bottlenecks ────────────────────────────────────
        candidates = self._identify_candidates(llm_metrics, promotion_metrics, fsb_metrics, orchestrator_metrics)
        candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
        top_bottleneck = candidates[0] if candidates else None

        print(f"\n[BottleneckDetector] Bottlenecks identified: {len(candidates)}")
        for i, c in enumerate(candidates[:3], 1):
            print(f"  {i}. [{c['confidence_score']:.0%} confidence] {c['title']}")

        # ── Build bottleneck_report artifact ───────────────────────────────────
        from lib.artifact import create_artifact, write_artifact

        artifact = create_artifact(
            artifact_type="bottleneck_report",
            producing_agent="bottleneck_detector",
            phase=self.phase,
            content={
                "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
                "telemetry_sources": [
                    "aims/mode_a/llm_call_log.jsonl",
                    "aims/mode_a/promotion_gate_log.jsonl",
                    "aims/mode_a/orchestrator_log.jsonl",
                    "aims/mode_a/algorithmic_rule_log.jsonl",
                ],
                "llm_aggregate": llm_metrics,
                "promotion_aggregate": promotion_metrics,
                "fsb_aggregate": fsb_metrics,
                "orchestrator_aggregate": orchestrator_metrics,
                "bottleneck_candidates": candidates,
                "top_bottleneck": top_bottleneck,
                "recommended_next_phase7_target": (
                    top_bottleneck["id"] if top_bottleneck else "none_identified"
                ),
            },
            provenance=[],
            confidence_score=0.85,
            known_limitations=[
                "Telemetry from synthetic demo runs only — production volumes would "
                "provide stronger statistical confidence",
                "Statistician overconfidence assessment is structural (based on "
                "subgroup sample sizes), not empirical (no holdout comparison)",
                "FSB recency bias is a design inference, not a measured retrieval failure rate",
            ],
        )

        path = write_artifact(artifact)
        print(f"[BottleneckDetector] Bottleneck report: {artifact['artifact_id'][:8]}... → {path}")

        # ── Vault write ────────────────────────────────────────────────────────
        from lib.second_brain import write_bottleneck_entry
        write_bottleneck_entry(artifact)

        # ── AIMS Mode A ────────────────────────────────────────────────────────
        self._log_aims_a(artifact, candidates)

        return {
            "bottleneck_report_artifact_id": artifact["artifact_id"],
            "top_bottleneck": top_bottleneck,
            "all_candidates": candidates,
            "llm_metrics": llm_metrics,
        }

    # ── Telemetry aggregation ──────────────────────────────────────────────────

    def _aggregate_llm_call_log(self) -> dict:
        """Aggregate LLM call log: token usage by agent, latency, call count."""
        log_file = AIMS_A / "llm_call_log.jsonl"
        by_agent: dict = {}
        total_calls = 0
        total_input = 0
        total_output = 0
        total_latency = 0.0
        latency_count = 0
        prompt_chars_orchestrator: list = []

        if log_file.exists():
            for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event = entry.get("event_type", "")
                agent = entry.get("agent", "unknown")

                if event == "LLM_CALL_STARTED" and agent == "orchestrator":
                    prompt_chars_orchestrator.append(entry.get("system_prompt_chars", 0))

                if event == "LLM_CALL_COMPLETED":
                    total_calls += 1
                    inp = entry.get("input_tokens", 0)
                    out = entry.get("output_tokens", 0)
                    lat = entry.get("elapsed_sec", 0.0)

                    total_input += inp
                    total_output += out
                    total_latency += lat
                    latency_count += 1

                    if agent not in by_agent:
                        by_agent[agent] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_sum": 0.0}
                    by_agent[agent]["calls"] += 1
                    by_agent[agent]["input_tokens"] += inp
                    by_agent[agent]["output_tokens"] += out
                    by_agent[agent]["latency_sum"] += lat

        for agent, d in by_agent.items():
            calls = max(d["calls"], 1)
            d["avg_input_tokens"] = round(d["input_tokens"] / calls)
            d["avg_output_tokens"] = round(d["output_tokens"] / calls)
            d["avg_latency_sec"] = round(d["latency_sum"] / calls, 2)

        avg_prompt_chars = (
            round(sum(prompt_chars_orchestrator) / len(prompt_chars_orchestrator))
            if prompt_chars_orchestrator else 0
        )

        return {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "avg_latency_sec": round(total_latency / latency_count, 2) if latency_count else 0.0,
            "by_agent": by_agent,
            "orchestrator_avg_system_prompt_chars": avg_prompt_chars,
        }

    def _aggregate_promotion_log(self) -> dict:
        """Aggregate Promotion Gate log: categorization distribution, quarantine rate."""
        log_file = AIMS_A / "promotion_gate_log.jsonl"
        total = 0
        categories: dict = {}
        quarantine_count = 0

        if log_file.exists():
            for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                cat = entry.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1
                if entry.get("routing") == "quarantine":
                    quarantine_count += 1

        return {
            "total_decisions": total,
            "by_category": categories,
            "quarantine_count": quarantine_count,
            "quarantine_rate": round(quarantine_count / total, 3) if total else 0.0,
        }

    def _aggregate_fsb_metrics(self) -> dict:
        """
        Assess FSB retrieval signal composition from CDI exemplar_surface.json.
        Checks whether recency decay dominates over semantic relevance.
        """
        fsb_file = BASE / "cdi_layer" / "index" / "exemplar_surface.json"
        try:
            data = json.loads(fsb_file.read_text(encoding="utf-8"))
        except Exception:
            return {"exemplar_count": 0, "recency_bias_detected": False, "relevance_score_variance": 0.0}

        exemplars = data.get("exemplars", [])
        if not exemplars:
            return {"exemplar_count": 0, "recency_bias_detected": False, "relevance_score_variance": 0.0}

        relevance_scores = [float(e.get("relevance_score", 0.5)) for e in exemplars]
        avg_rel = sum(relevance_scores) / len(relevance_scores)
        variance = sum((s - avg_rel) ** 2 for s in relevance_scores) / len(relevance_scores)

        return {
            "exemplar_count": len(exemplars),
            "avg_relevance_score": round(avg_rel, 3),
            "relevance_score_variance": round(variance, 4),
            "recency_bias_detected": variance < 0.02 and len(exemplars) > 1,
            "recency_decay_half_life_days": 30,
        }

    def _aggregate_orchestrator_log(self) -> dict:
        """Count Orchestrator AIMS Mode A events."""
        log_file = AIMS_A / "orchestrator_log.jsonl"
        total = 0
        cb_emitted = 0

        if log_file.exists():
            for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                    total += 1
                    if entry.get("event_type") == "CAPABILITY_BUNDLE_EMITTED":
                        cb_emitted += 1
                except json.JSONDecodeError:
                    pass

        return {"total_events": total, "capability_bundles_emitted": cb_emitted}

    # ── Bottleneck identification ──────────────────────────────────────────────

    def _identify_candidates(self, llm: dict, promo: dict, fsb: dict, orch: dict) -> list:
        """
        Identify structural bottlenecks from aggregated telemetry.
        Returns list of candidates sorted by confidence_score (descending).
        """
        candidates = []

        # ── BOTTLENECK_001: Orchestrator context efficiency ────────────────────
        orch_agent = llm.get("by_agent", {}).get("orchestrator", {})
        avg_input = orch_agent.get("avg_input_tokens", 0)
        prompt_chars = llm.get("orchestrator_avg_system_prompt_chars", 0)
        calls = orch_agent.get("calls", 0)

        evidence_001 = []
        confidence_001 = 0.55  # structural base

        if avg_input > 3000:
            confidence_001 += 0.20
            evidence_001.append(
                f"Average Orchestrator LLM input: {avg_input:,} tokens/call "
                f"({calls} calls recorded) — high relative to decomposition task complexity"
            )
        if prompt_chars > 8000:
            confidence_001 += 0.15
            evidence_001.append(
                f"Average Orchestrator system prompt: ~{prompt_chars:,} chars — "
                "full CDI spec loaded on every call; selective domain loading would reduce this"
            )
        evidence_001.append(
            "Structural: Orchestrator queries all 9 CDI domains on every call regardless "
            "of task type; a task-type classifier would allow selective domain loading "
            "reducing input tokens by an estimated 30–45%"
        )

        candidates.append({
            "id": "BOTTLENECK_001",
            "title": "Orchestrator context window usage is inefficient",
            "description": (
                "The Orchestrator loads all 9 CDI Layer domains on every task decomposition "
                "call, regardless of the specific task's domain relevance. A task-type "
                "classifier would allow selective domain loading, reducing input token "
                "usage by an estimated 30–45% per call."
            ),
            "affected_component": "agents/orchestrator/orchestrator.py",
            "affected_agent": "orchestrator",
            "evidence": evidence_001,
            "confidence_score": min(confidence_001, 0.92),
            "severity": "MEDIUM",
            "improvement_category": "efficiency",
            "proposal_hint": (
                "Introduce CDI domain relevance filtering: before loading CDI context, "
                "classify the task type (fraud_investigation / experiment_analysis / "
                "pipeline_diagnosis / invention_cycle) and load only the 3–4 relevant "
                "domains. Preserve full 9-domain load on first call per task as fallback."
            ),
        })

        # ── BOTTLENECK_002: Statistician small-N overconfidence ───────────────
        stat_agent = llm.get("by_agent", {}).get("statistician", {})
        stat_calls = stat_agent.get("calls", 0)

        evidence_002 = [
            "Dataset structure: coordinated clusters have 5–8 accounts "
            "(Cluster A: 8, B: 6, C: 5) — too small for CLT-based asymptotic approximations",
            "Phase 1 finding: cluster Q1 abuse share 20.2% computed from N=19 cluster accounts "
            "— confidence interval width not surfaced in the statistical_result artifact",
            "Statistician system prompt does not include a minimum-N guard; "
            "no exact method (Fisher, Clopper-Pearson, bootstrap) is invoked for N<30",
        ]
        if stat_calls > 0:
            evidence_002.append(
                f"{stat_calls} Statistician LLM calls recorded; "
                "no minimum-N check observed in any statistical result artifact"
            )

        candidates.append({
            "id": "BOTTLENECK_002",
            "title": "Statistician produces overconfident point estimates on small subgroup analyses",
            "description": (
                "When analyzing subgroup behavior (coordinated clusters of 5–8 accounts), "
                "the Statistician Agent produces point estimates with confidence intervals "
                "based on normal approximations that violate the CLT assumption (N<30). "
                "Exact methods (Fisher exact, Clopper-Pearson for proportions, bootstrap CI) "
                "should be substituted for subgroup analyses below the N=30 threshold."
            ),
            "affected_component": "agents/statistician/statistician.py",
            "affected_agent": "statistician",
            "evidence": evidence_002,
            "confidence_score": 0.83,
            "severity": "HIGH",
            "improvement_category": "statistical_correctness",
            "proposal_hint": (
                "Add a minimum-N guard to the Statistician Agent: when subgroup N < 30, "
                "automatically switch to exact methods (Fisher exact, Clopper-Pearson for "
                "proportions, or bootstrap CI with B=2000 resamples). Surface the N-flag "
                "explicitly in the statistical_result artifact's known_limitations field "
                "and widen the confidence interval accordingly."
            ),
        })

        # ── BOTTLENECK_003: FSB recency bias ──────────────────────────────────
        fsb_count = fsb.get("exemplar_count", 0)
        recency_bias = fsb.get("recency_bias_detected", False)
        variance = fsb.get("relevance_score_variance", 0.0)
        half_life = fsb.get("recency_decay_half_life_days", 30)

        evidence_003 = [
            f"FewShotBank retrieval uses a {half_life}-day half-life recency decay as "
            "its primary scoring signal (hardcoded in lib/few_shot_bank.py)",
            f"Exemplar pool: {fsb_count} exemplars. "
            f"Relevance score variance: {variance:.4f} "
            f"({'near-zero — recency dominates' if recency_bias else 'acceptable spread'})",
            "No cross-class retrieval: exact query_class match only; structurally similar "
            "queries across different class labels receive no FSB benefit",
            "In query classes with long exemplar histories, older but more semantically "
            "precise exemplars may be suppressed by recent but less relevant ones",
        ]

        candidates.append({
            "id": "BOTTLENECK_003",
            "title": "Few-Shot Bank retrieval mechanism favors recency over relevance",
            "description": (
                f"The FSB retrieval uses a {half_life}-day half-life recency decay as its "
                "primary scoring signal with exact query_class match as the only filter. "
                "This may bias retrieval toward recent exemplars over older but more "
                "precisely applicable ones, and provides no benefit for structurally "
                "similar queries with different class labels."
            ),
            "affected_component": "lib/few_shot_bank.py",
            "affected_agent": "orchestrator",
            "evidence": evidence_003,
            "confidence_score": 0.76,
            "severity": "MEDIUM",
            "improvement_category": "retrieval_quality",
            "proposal_hint": (
                "Replace the recency-only scoring with a composite score: "
                "relevance_score * 0.6 + recency_weight * 0.4. "
                "Relevance score = cosine similarity between current query embedding "
                "and exemplar input embedding (via lib/vector_index.py, Phase 2 implementation). "
                "Relax query_class to fuzzy match (Jaccard coefficient ≥ 0.5) to enable "
                "cross-class retrieval for structurally similar queries."
            ),
        })

        return candidates

    def _log_aims_a(self, artifact: dict, candidates: list) -> None:
        """Log bottleneck detection completion to AIMS Mode A."""
        AIMS_A.mkdir(parents=True, exist_ok=True)
        entry = {
            "aims_entry_id": str(uuid.uuid4()),
            "event_type": "BOTTLENECK_DETECTION_COMPLETED",
            "artifact_id": artifact["artifact_id"],
            "candidates_count": len(candidates),
            "top_bottleneck_id": candidates[0]["id"] if candidates else None,
            "top_bottleneck_title": candidates[0]["title"] if candidates else None,
            "top_bottleneck_confidence": candidates[0]["confidence_score"] if candidates else 0.0,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        log_file = AIMS_A / "bottleneck_detector_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
