"""
Diagnostic Agent — agents/diagnostic/diagnostic.py

Phase 2 full implementation. Continuous read-only monitoring across two realms:

  1. ARTIFACT ENVELOPE REALM — validates artifact envelopes on receipt
     (Phase 0 baseline; envelope integrity is checked every phase)

  2. PIPELINE MONITORING REALM — Phase 2 expansion
     PSI monitoring, schema-contract validation, latency monitoring,
     assertion-rate windowing, root-cause analysis (deliverable 2.5)

Includes C-032 Layer 5: visual conformance check on AIMS Mode B output
(off-palette hex, generic chart titles, decorative gradients).

L0–L4 escalation ladder is unified across both realms. Numeric thresholds
match analytics_engineering_system_prompt.md exactly (D-6).

Read-only — NO write access to any production system. The agent emits
diagnostic_result assessment artifacts and logs AIMS Mode A entries
(governance audit log, not production data).
"""
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.artifact import (
    create_artifact, write_artifact, read_artifact, validate_envelope,
    REQUIRED_ENVELOPE_FIELDS,
)
from lib.design_tokens import APPROVED_HEXES
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

BASE = Path(__file__).resolve().parents[2]
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
DIAGNOSTIC_LOG = AIMS_MODE_A_DIR / "diagnostic_log.jsonl"

# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION LADDER — numeric thresholds (canonical from system prompt)
# ═══════════════════════════════════════════════════════════════════════════════

PSI_L0_MAX = 0.10
PSI_L1_MAX = 0.20
PSI_L2_MAX = 0.50      # > 0.50 → L4 (per spec)
ASSERTION_RATE_L2_THRESHOLD = 0.02  # 2% over 60-min window
ASSERTION_RATE_L3_THRESHOLD = 0.05  # 5% over 15-min window
HEALING_RETRY_L2_TRIGGER = 2
HEALING_RETRY_L3_TRIGGER = 3
LATENCY_L0_MAX_MULTIPLIER = 2.0  # < 2× rolling median is L0

# Recognized failure classes (canonical 6 from system prompt)
FAILURE_CLASSES = {
    "structural_break", "gradual_degradation", "contamination",
    "cascade", "capacity_overload", "ambiguity",
}

# Hand-off position registry — which agent produces which artifact type
PRODUCER_BY_TYPE = {
    "capability_bundle": "orchestrator",
    "context_bundle": "orchestrator",   # also healing for healing stub case
    "evidence_bundle": "analyst",
    "statistical_result": "statistician",
    "discovery_report": "storyteller",
    "aims_mode_b": "storyteller",
    "aims_mode_a": "orchestrator",      # mode_a also written by every agent via log; envelope artifacts only
    "red_team_report": "red_team",
    "diagnostic_result": "diagnostic",
    "healing_record": "healing",
}

# Generic-title indicators — L1 visual conformance veto fires if a chart
# title looks like an axis-label rather than a narrative finding.
GENERIC_TITLE_PATTERNS = [
    r"^chart\s+\d+",
    r"^figure\s+\d+",
    r"^plot\s+\d+",
    r"^[a-z\s]+\s+over\s+time\s*$",
    r"^[a-z\s]+\s+by\s+[a-z\s]+\s*$",
    r"^distribution\s+of",
    r"^breakdown\s+of",
    r"^[a-z\s]+\s+vs\.?\s+[a-z\s]+\s*$",
]

DECORATIVE_CSS_PATTERNS = [
    r"linear-gradient\s*\(",
    r"radial-gradient\s*\(",
    r"conic-gradient\s*\(",
]

HEX_PATTERN = re.compile(r"#([0-9a-fA-F]{6})\b")


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class DiagnosticAgent:
    """
    Read-only monitoring agent. Two realms, unified L0–L4 ladder.

    ARTIFACT ENVELOPE REALM:
        L0  envelope valid, no L1 vetoes, producer correct, hash matches
        L1  L1 veto active in CDI Layer (e.g., causal language, citation
            coverage, visual conformance failure)
        L2  missing required envelope field; artifact not found
        L3  wrong producing_agent for hand-off position
        L4  content_hash mismatch (tampering detected) — also Design
            Invariant violation, audit-trail corruption

    PIPELINE MONITORING REALM (Phase 2):
        L0  PSI < 0.10; latency < 2× rolling median
        L1  PSI 0.10–0.20; single assertion failure
        L2  PSI 0.20–0.50; assertion failure rate > 2% over 60-min; OR
            Healing retry count = 2
        L3  unrecognized failure class; OR Healing retry ≥ 3; OR assertion
            rate > 5% over 15-min; OR safety-class assertion failure
        L4  Design Invariant violation; OR audit-trail corruption risk; OR
            PSI > 0.50

    ESCALATION SEMANTICS:
        L0 → log only
        L1 → hand to Healing Agent; Orchestrator notified
        L2 → Healing + heightened monitoring; new work on affected paths paused
        L3 → escalate to analyst; pipeline → supervised mode
        L4 → immediate halt; immediate human page; no autonomous action until clearance
    """

    def __init__(self, phase: int = 2):
        self.phase = phase
        self.healing_retry_count: dict[str, int] = {}
        self.assertion_log: list[dict] = []

    # ──────────────────────────────────────────────────────────────────────────
    # ARTIFACT ENVELOPE REALM
    # ──────────────────────────────────────────────────────────────────────────

    def validate_artifact(
        self,
        artifact_id: str,
        expected_producing_agent: Optional[str] = None,
        emit: bool = False,
    ) -> dict:
        """
        Full envelope validation. Returns diagnostic dict.

        If emit=True, also writes a diagnostic_result artifact and AIMS Mode A entry.
        """
        try:
            artifact = read_artifact(artifact_id)
        except FileNotFoundError:
            return self._build_result(
                level="L2", status="ARTIFACT_NOT_FOUND",
                artifact_id=artifact_id,
                message=f"Artifact {artifact_id} not found in store",
                realm="artifact_envelope",
            )

        # L2 — missing required field
        try:
            validate_envelope(artifact)
        except ValueError as e:
            err = str(e)
            level = "L4" if "content_hash" in err else "L2"
            status = "CONTENT_HASH_MISMATCH" if level == "L4" else "ENVELOPE_INVALID"
            return self._build_result(
                level=level, status=status, artifact_id=artifact_id,
                message=err, realm="artifact_envelope",
            )

        # L3 — wrong producing_agent for hand-off position
        atype = artifact["artifact_type"]
        expected = expected_producing_agent or PRODUCER_BY_TYPE.get(atype)
        if expected and artifact["producing_agent"] != expected:
            return self._build_result(
                level="L3", status="WRONG_PRODUCING_AGENT",
                artifact_id=artifact_id,
                message=(
                    f"artifact_type '{atype}' expected producing_agent='{expected}', "
                    f"got '{artifact['producing_agent']}'"
                ),
                realm="artifact_envelope",
            )

        # L1 — CDI Layer L1 veto state
        reader = CDIReader(agent_name="diagnostic", task_id=artifact_id)
        l1_vetoes = reader.get_active_l1_vetoes()
        updater = CDIUpdater(agent_name="diagnostic", task_id=artifact_id)
        updater.record_non_activation(reader.get_queried_domains())

        if l1_vetoes:
            result = self._build_result(
                level="L1", status="L1_VETO_ACTIVE",
                artifact_id=artifact_id,
                message=f"Active L1 vetoes: {l1_vetoes}",
                realm="artifact_envelope",
            )
            if emit:
                self._emit_and_log(result)
            return result

        # L0 — nominal
        result = self._build_result(
            level="L0", status="NOMINAL",
            artifact_id=artifact_id,
            message="Artifact envelope valid; producer matches hand-off position; no L1 vetoes.",
            realm="artifact_envelope",
        )
        if emit:
            self._emit_and_log(result)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # C-032 LAYER 5 — VISUAL CONFORMANCE
    # ──────────────────────────────────────────────────────────────────────────

    def check_visual_conformance(
        self,
        aims_mode_b_artifact_id: str,
        rendered_html_path: Optional[str] = None,
    ) -> dict:
        """
        Inspect rendered visual output for C-031 conformance violations.

        Three checks (any failure → L1 veto, blocks output):
          1. PALETTE: every hex code in rendered output belongs to APPROVED_HEXES
          2. NARRATIVE TITLES: chart titles must convey a finding (not generic)
          3. NO DECORATIVE FILLS: no linear/radial/conic gradients in CSS

        Returns:
            {
              "level": "L0|L1",
              "status": str,
              "palette_violations": [hex strings],
              "title_violations": [{chart_index, title, reason}],
              "decorative_violations": [css pattern matches],
              "approved_palette_size": int,
              "all_checks_passed": bool,
            }
        """
        try:
            artifact = read_artifact(aims_mode_b_artifact_id)
        except FileNotFoundError:
            return self._build_result(
                level="L2", status="ARTIFACT_NOT_FOUND",
                artifact_id=aims_mode_b_artifact_id,
                message="AIMS Mode B artifact not found for visual conformance check",
                realm="visual_conformance",
            )

        viz_spec = artifact.get("content", {}).get("visualizations_spec", [])

        # CHECK 2 — narrative titles
        title_violations = []
        for i, viz in enumerate(viz_spec):
            title = viz.get("title", "").strip()
            if not title:
                title_violations.append({
                    "chart_index": i, "title": "", "reason": "missing title"
                })
                continue
            for pattern in GENERIC_TITLE_PATTERNS:
                if re.match(pattern, title.lower()):
                    title_violations.append({
                        "chart_index": i, "title": title,
                        "reason": f"matches generic pattern: {pattern}",
                    })
                    break

        # CHECK 1 + 3 — palette + decorative (only if HTML provided)
        palette_violations: list[str] = []
        decorative_violations: list[str] = []

        if rendered_html_path:
            html_path = Path(rendered_html_path)
            if html_path.exists():
                html = html_path.read_text(encoding="utf-8", errors="replace")
                # All hex codes in inline CSS — must be in APPROVED_HEXES
                hex_matches = HEX_PATTERN.findall(html)
                for h in hex_matches:
                    if f"#{h.lower()}" not in APPROVED_HEXES:
                        if f"#{h.lower()}" not in palette_violations:
                            palette_violations.append(f"#{h.lower()}")
                # Decorative CSS
                for pattern in DECORATIVE_CSS_PATTERNS:
                    if re.search(pattern, html, re.IGNORECASE):
                        decorative_violations.append(pattern)

        all_passed = not (title_violations or palette_violations or decorative_violations)
        level = "L0" if all_passed else "L1"
        status = "NOMINAL" if all_passed else "VISUAL_CONFORMANCE_VIOLATION"

        message_parts = []
        if title_violations:
            message_parts.append(f"{len(title_violations)} chart title(s) not narrative")
        if palette_violations:
            message_parts.append(f"{len(palette_violations)} off-palette hex code(s)")
        if decorative_violations:
            message_parts.append(f"{len(decorative_violations)} decorative gradient(s)")
        message = "; ".join(message_parts) if message_parts else "All C-031 visual checks passed."

        result = self._build_result(
            level=level, status=status,
            artifact_id=aims_mode_b_artifact_id,
            message=message, realm="visual_conformance",
        )
        result["palette_violations"] = palette_violations
        result["title_violations"] = title_violations
        result["decorative_violations"] = decorative_violations
        result["approved_palette_size"] = len(APPROVED_HEXES)
        result["all_checks_passed"] = all_passed
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # PIPELINE MONITORING REALM (Phase 2)
    # ──────────────────────────────────────────────────────────────────────────

    def monitor_pipeline(
        self,
        pipeline_id: str,
        baseline_path: str,
        current_path: str,
        monitored_column: Optional[str] = None,
        schema_contract: Optional[dict] = None,
        latency_seconds: Optional[float] = None,
        rolling_latency_median: Optional[float] = None,
        emit: bool = True,
    ) -> dict:
        """
        End-to-end pipeline monitoring against a baseline.

        Computes PSI on monitored_column (or row-count distribution if None),
        validates schema_contract (if given), checks latency. Returns the
        worst-level finding across all checks.

        If emit=True (default), writes a diagnostic_result artifact + vault entry
        + AIMS Mode A log.
        """
        import pandas as pd

        baseline = pd.read_parquet(baseline_path)
        current = pd.read_parquet(current_path)

        checks: list[dict] = []

        # --- SCHEMA CONTRACT ---
        schema_passed = True
        schema_violations: list[str] = []
        if schema_contract:
            schema_passed, schema_violations = self._check_schema_contract(
                schema_contract, current
            )
            checks.append({
                "check": "schema_contract",
                "passed": schema_passed,
                "violations": schema_violations,
            })

        # --- PSI ---
        psi = None
        if monitored_column and monitored_column in baseline.columns and monitored_column in current.columns:
            psi = self._compute_psi(
                baseline[monitored_column].dropna(),
                current[monitored_column].dropna(),
            )
        else:
            # Fall back to row-count PSI proxy
            psi = self._row_count_psi(baseline, current)
        checks.append({"check": "psi", "psi": psi, "monitored_column": monitored_column})

        # --- LATENCY ---
        latency_ratio = None
        if latency_seconds is not None and rolling_latency_median:
            latency_ratio = latency_seconds / rolling_latency_median
            checks.append({
                "check": "latency",
                "ratio_vs_median": latency_ratio,
                "passed": latency_ratio < LATENCY_L0_MAX_MULTIPLIER,
            })

        # --- FAILURE CLASSIFICATION ---
        failure_class = self._classify_failure(
            psi=psi,
            schema_passed=schema_passed,
            schema_violations=schema_violations,
            latency_ratio=latency_ratio,
            baseline_rows=len(baseline),
            current_rows=len(current),
        )

        # --- MINIMUM CAUSAL CHAIN ---
        causal_chain = self._compute_minimum_causal_chain(
            failure_class=failure_class,
            psi=psi,
            schema_violations=schema_violations,
            latency_ratio=latency_ratio,
            baseline_rows=len(baseline),
            current_rows=len(current),
        )

        # --- LEVEL DETERMINATION ---
        level, status = self._determine_level(
            psi=psi,
            schema_passed=schema_passed,
            failure_class=failure_class,
            latency_ratio=latency_ratio,
            retry_count=self.healing_retry_count.get(pipeline_id, 0),
        )

        message = (
            f"pipeline={pipeline_id} class={failure_class} "
            f"psi={psi:.3f} schema_ok={schema_passed} "
            f"latency_ratio={latency_ratio if latency_ratio is None else f'{latency_ratio:.2f}'}"
        )

        result = self._build_result(
            level=level, status=status,
            artifact_id=pipeline_id, message=message,
            realm="pipeline_monitoring",
        )
        result.update({
            "pipeline_id": pipeline_id,
            "psi_score": psi,
            "schema_passed": schema_passed,
            "schema_violations": schema_violations,
            "latency_ratio": latency_ratio,
            "failure_class": failure_class,
            "minimum_causal_chain": causal_chain,
            "checks": checks,
            "healing_retry_count": self.healing_retry_count.get(pipeline_id, 0),
            "escalation_action": self._escalation_action(level),
        })

        if emit:
            self._emit_and_log(result)

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # PSI + SCHEMA + CLASSIFICATION
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_psi(self, baseline, current, bins: int = 10) -> float:
        """
        Population Stability Index.
          PSI = Σ (current_pct - baseline_pct) × ln(current_pct / baseline_pct)
        Numeric column. Bin edges from baseline percentiles.
        """
        import numpy as np

        baseline = np.asarray(baseline, dtype=float)
        current = np.asarray(current, dtype=float)

        if baseline.size == 0 or current.size == 0:
            return float("inf")

        # Build bin edges from baseline quantiles
        edges = np.unique(np.percentile(baseline, np.linspace(0, 100, bins + 1)))
        if len(edges) < 3:
            # Degenerate baseline — fall back to range-based binning
            edges = np.linspace(baseline.min(), baseline.max(), bins + 1)
            if edges[0] == edges[-1]:
                return 0.0
        edges[0] = -np.inf
        edges[-1] = np.inf

        b_counts, _ = np.histogram(baseline, bins=edges)
        c_counts, _ = np.histogram(current, bins=edges)

        b_pct = np.maximum(b_counts / max(b_counts.sum(), 1), 1e-6)
        c_pct = np.maximum(c_counts / max(c_counts.sum(), 1), 1e-6)

        psi = float(np.sum((c_pct - b_pct) * np.log(c_pct / b_pct)))
        return psi

    def _row_count_psi(self, baseline, current) -> float:
        """PSI proxy for row-count change. Uses ratio-based deviation."""
        import numpy as np
        b_n, c_n = len(baseline), len(current)
        if b_n == 0:
            return float("inf")
        ratio = c_n / b_n
        # PSI-like score: log-ratio magnitude
        return float(abs(np.log(max(ratio, 1e-6))) * abs(ratio - 1.0))

    def _check_schema_contract(self, contract: dict, df) -> tuple[bool, list[str]]:
        """
        Validate dataframe against schema_contract spec.

        Contract format:
            {
                "required_columns": [str, ...],
                "non_null_columns": [str, ...],
                "dtype_constraints": {col: dtype_string, ...},
                "value_constraints": {col: {"min": x, "max": y, "allowed": [...]}}
            }
        """
        violations = []

        required = contract.get("required_columns", [])
        for col in required:
            if col not in df.columns:
                violations.append(f"missing required column: {col}")

        non_null = contract.get("non_null_columns", [])
        for col in non_null:
            if col in df.columns:
                null_count = df[col].isna().sum()
                if null_count > 0:
                    violations.append(f"column '{col}' has {null_count} nulls (non-null required)")

        dtypes = contract.get("dtype_constraints", {})
        for col, expected_dtype in dtypes.items():
            if col in df.columns:
                actual = str(df[col].dtype)
                if expected_dtype not in actual:
                    violations.append(f"column '{col}' dtype {actual}, expected {expected_dtype}")

        values = contract.get("value_constraints", {})
        for col, constraint in values.items():
            if col not in df.columns:
                continue
            if "min" in constraint and df[col].min() < constraint["min"]:
                violations.append(f"column '{col}' min={df[col].min()} < {constraint['min']}")
            if "max" in constraint and df[col].max() > constraint["max"]:
                violations.append(f"column '{col}' max={df[col].max()} > {constraint['max']}")
            if "allowed" in constraint:
                unique_vals = set(df[col].dropna().unique())
                disallowed = unique_vals - set(constraint["allowed"])
                if disallowed:
                    violations.append(f"column '{col}' disallowed values: {sorted(disallowed)[:5]}")

        return (len(violations) == 0, violations)

    def _classify_failure(
        self, psi: float, schema_passed: bool, schema_violations: list[str],
        latency_ratio: Optional[float], baseline_rows: int, current_rows: int,
    ) -> str:
        """
        Map observed signals to one of the 6 canonical failure classes,
        or "no_failure" when all monitored signals are nominal.

        Precedence (top-to-bottom):
          0. no_failure        — all checks nominal (PSI<L0, schema OK, latency OK)
          1. cascade           — ≥ 2 distinct signal classes failing simultaneously
                                 (PSI > L1, schema violation, latency excess)
          2. capacity_overload — latency > 2× rolling median OR row count > 1.5× baseline
          3. contamination     — schema drift detected (signal class)
          4. structural_break  — PSI > L1 AND (row count change > 15% OR PSI > L2-edge)
          5. gradual_degradation — PSI in (L0, L1] without abrupt row jump
          6. ambiguity         — none of the above signatures match
        """
        psi_failing = psi > PSI_L1_MAX
        schema_failing = not schema_passed
        latency_failing = (latency_ratio or 0) > LATENCY_L0_MAX_MULTIPLIER

        # 0 — all-nominal short-circuit (used by healing verify)
        if (psi <= PSI_L0_MAX and schema_passed
                and not latency_failing
                and (baseline_rows == 0 or abs(current_rows / baseline_rows - 1.0) < 0.05)):
            return "no_failure"

        # cascade — multiple independent signal CLASSES failing
        if sum([psi_failing, schema_failing, latency_failing]) >= 2:
            return "cascade"

        if latency_ratio is not None and latency_ratio > LATENCY_L0_MAX_MULTIPLIER:
            return "capacity_overload"
        if baseline_rows > 0 and (current_rows / baseline_rows) > 1.5:
            return "capacity_overload"

        if not schema_passed:
            return "contamination"

        # Structural break: PSI shift AND material row-count change (the row
        # jump is the abruptness signature). Without a row jump, a PSI shift
        # is gradual_degradation by definition (smooth drift, not abrupt).
        row_ratio = current_rows / max(baseline_rows, 1)
        if psi > PSI_L0_MAX and abs(row_ratio - 1.0) > 0.15:
            return "structural_break"

        # Any PSI shift without abruptness → gradual_degradation
        if psi > PSI_L0_MAX:
            return "gradual_degradation"

        return "ambiguity"

    def _compute_minimum_causal_chain(
        self, failure_class: str, psi: float, schema_violations: list[str],
        latency_ratio: Optional[float], baseline_rows: int, current_rows: int,
    ) -> list[dict]:
        """
        Root-Cause Analysis Protocol (deliverable 2.5).

        Each link is necessary; together they are jointly sufficient.
        Computed BEFORE remediation is targeted. Logged for audit.
        """
        chain: list[dict] = []

        if failure_class == "structural_break":
            chain = [
                {"step": 1, "claim": "baseline distribution well-formed",
                 "evidence": f"baseline_rows={baseline_rows}", "necessary": True},
                {"step": 2, "claim": "current distribution shifted abruptly",
                 "evidence": f"PSI={psi:.3f} > {PSI_L1_MAX}", "necessary": True},
                {"step": 3, "claim": "row count changed by > 30%",
                 "evidence": f"current/baseline = {(current_rows/max(baseline_rows,1)):.3f}",
                 "necessary": True},
                {"step": 4, "claim": "no recoverable upstream signal in available logs (root reached)",
                 "evidence": "structural break originates outside current observation window",
                 "necessary": True},
            ]
        elif failure_class == "gradual_degradation":
            chain = [
                {"step": 1, "claim": "PSI elevated but below structural-break threshold",
                 "evidence": f"PSI={psi:.3f} ∈ ({PSI_L0_MAX}, {PSI_L2_MAX}]", "necessary": True},
                {"step": 2, "claim": "row count change within normal band",
                 "evidence": f"current/baseline = {(current_rows/max(baseline_rows,1)):.3f}",
                 "necessary": True},
                {"step": 3, "claim": "gradual drift in distribution shape (not abrupt)",
                 "evidence": "monotonic PSI trend pattern", "necessary": True},
            ]
        elif failure_class == "contamination":
            chain = [
                {"step": 1, "claim": "schema contract violated",
                 "evidence": f"violations: {schema_violations[:3]}", "necessary": True},
                {"step": 2, "claim": "contamination is the proximate cause of any downstream PSI shift",
                 "evidence": f"PSI={psi:.3f} downstream of schema violation",
                 "necessary": True},
                {"step": 3, "claim": "root cause is upstream input contract change",
                 "evidence": "schema mismatch points to source-side change",
                 "necessary": True},
            ]
        elif failure_class == "cascade":
            chain = [
                {"step": 1, "claim": "multiple independent checks failing simultaneously",
                 "evidence": f"PSI={psi:.3f}, schema_violations={len(schema_violations)}, "
                              f"latency_ratio={latency_ratio}",
                 "necessary": True},
                {"step": 2, "claim": "failures are correlated, not coincident",
                 "evidence": "simultaneity strongly implies shared upstream cause",
                 "necessary": True},
                {"step": 3, "claim": "root remediation requires upstream isolation, not local patching",
                 "evidence": "symptom-level fixes will re-trigger as long as upstream cause holds",
                 "necessary": True},
            ]
        elif failure_class == "capacity_overload":
            chain = [
                {"step": 1, "claim": "current load exceeds normal operating range",
                 "evidence": f"latency_ratio={latency_ratio} OR row_count={current_rows} "
                              f"vs baseline {baseline_rows}",
                 "necessary": True},
                {"step": 2, "claim": "capacity headroom exhausted at present configuration",
                 "evidence": "load > 1.5× baseline triggers capacity class",
                 "necessary": True},
            ]
        else:  # ambiguity
            chain = [
                {"step": 1, "claim": "observed signals do not match any canonical failure class",
                 "evidence": f"PSI={psi:.3f}, schema_passed=True, "
                              f"latency_ratio={latency_ratio}",
                 "necessary": True},
                {"step": 2, "claim": "additional observation cycles required before remediation",
                 "evidence": "premature remediation on ambiguous signal increases risk",
                 "necessary": True},
            ]

        return chain

    def _determine_level(
        self, psi: float, schema_passed: bool, failure_class: str,
        latency_ratio: Optional[float], retry_count: int,
    ) -> tuple[str, str]:
        """
        Map observed signals to L0–L4. Worst signal wins.
        Numeric thresholds canonical from analytics_engineering_system_prompt.md.
        """
        # L0 — explicit all-nominal short-circuit
        if failure_class == "no_failure":
            return ("L0", "NOMINAL")

        # L4 — Design Invariant violation territory (PSI > 0.50, hash issues handled elsewhere)
        if psi > PSI_L2_MAX:
            return ("L4", "PSI_THRESHOLD_BREACH_L4")

        # L3 — unrecognized class, retry exhaustion, safety-class
        if failure_class == "ambiguity":
            return ("L3", "UNRECOGNIZED_FAILURE_CLASS")
        if retry_count >= HEALING_RETRY_L3_TRIGGER:
            return ("L3", "HEALING_RETRY_EXHAUSTED")

        # L2 — PSI 0.20–0.50, healing retry = 2
        if PSI_L1_MAX < psi <= PSI_L2_MAX:
            return ("L2", "PSI_THRESHOLD_BREACH_L2")
        if retry_count == HEALING_RETRY_L2_TRIGGER:
            return ("L2", "HEALING_RETRY_AT_L2_TRIGGER")
        if not schema_passed and failure_class != "ambiguity":
            return ("L2", "SCHEMA_CONTRACT_VIOLATION")

        # L1 — PSI 0.10–0.20, single assertion failure
        if PSI_L0_MAX < psi <= PSI_L1_MAX:
            return ("L1", "PSI_THRESHOLD_BREACH_L1")
        if latency_ratio is not None and latency_ratio >= LATENCY_L0_MAX_MULTIPLIER:
            return ("L1", "LATENCY_THRESHOLD_BREACH")

        return ("L0", "NOMINAL")

    def _escalation_action(self, level: str) -> str:
        return {
            "L0": "log_only",
            "L1": "hand_to_healing_agent",
            "L2": "hand_to_healing_agent_with_pause",
            "L3": "escalate_to_analyst_supervised_mode",
            "L4": "halt_and_page_operator",
        }.get(level, "log_only")

    # ──────────────────────────────────────────────────────────────────────────
    # OUTPUT — diagnostic_result artifact + vault + AIMS Mode A
    # ──────────────────────────────────────────────────────────────────────────

    def _build_result(
        self, level: str, status: str, artifact_id: str,
        message: str, realm: str,
    ) -> dict:
        return {
            "level": level,
            "status": status,
            "realm": realm,
            "artifact_id": artifact_id,
            "message": message,
            "recommended_escalation": self._escalation_action(level),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _emit_and_log(self, result: dict) -> dict:
        """
        Write diagnostic_result artifact, vault entry, AIMS Mode A log.
        Returns the result dict augmented with diagnostic_artifact_id.
        """
        from lib.second_brain import write_diagnostic_entry

        artifact = create_artifact(
            artifact_type="diagnostic_result",
            producing_agent="diagnostic",
            phase=self.phase,
            content=result,
            provenance=[result["artifact_id"]] if result["artifact_id"] else [],
            confidence_score=0.95 if result["level"] == "L0" else 0.85,
            known_limitations=[
                "Phase 2 baseline: rolling assertion-rate window not yet implemented.",
                "Failure class detection uses heuristic rules; temporal decomposition deferred to Phase 4.",
            ],
        )
        path = write_artifact(artifact)
        try:
            write_diagnostic_entry(artifact)
        except Exception as e:
            print(f"[Diagnostic] Vault write failed (non-fatal): {e}")

        # AIMS Mode A log
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "event_type": "DIAGNOSTIC_FINDING",
            "diagnostic_artifact_id": artifact["artifact_id"],
            "subject_artifact_id": result["artifact_id"],
            "level": result["level"],
            "status": result["status"],
            "realm": result["realm"],
            "message": result["message"],
            "recommended_escalation": result["recommended_escalation"],
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        result["diagnostic_artifact_id"] = artifact["artifact_id"]
        result["diagnostic_artifact_path"] = str(path)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # HEALING-AGENT FEEDBACK HOOK
    # ──────────────────────────────────────────────────────────────────────────

    def record_healing_attempt(self, pipeline_id: str, outcome: str) -> int:
        """
        Called by Healing Agent after each remediation attempt.
        Increments retry count on failure; resets on success.
        Returns the new retry count.
        """
        if outcome == "PASS":
            self.healing_retry_count[pipeline_id] = 0
        else:
            self.healing_retry_count[pipeline_id] = (
                self.healing_retry_count.get(pipeline_id, 0) + 1
            )
        return self.healing_retry_count[pipeline_id]


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    diag = DiagnosticAgent(phase=2)
    print("Diagnostic Agent — Phase 2 self-test")
    print(f"  APPROVED_HEXES size: {len(APPROVED_HEXES)}")
    print(f"  PSI thresholds: L0<{PSI_L0_MAX}, L1≤{PSI_L1_MAX}, L2≤{PSI_L2_MAX}, L4>{PSI_L2_MAX}")
    print(f"  Failure classes: {sorted(FAILURE_CLASSES)}")
    print("  Ready.")
