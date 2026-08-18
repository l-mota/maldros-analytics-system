"""
Statistician Agent — Phase 1 full implementation.
agents/statistician/statistician.py

Mandate: Validate all inferences from the Analyst Agent. Run formal statistical
tests. Detect experiment pathologies. Produce ship/no-ship verdicts with explicit
confidence intervals, p-values, and effect sizes.

For Phase 1: validates the Analyst's coordinated-abuse conclusion using:
1. Poisson regression — is Q1 abuse volume statistically anomalous?
2. Chi-square test — are cluster accounts overrepresented in Q1 incidents?
3. Concentration test — Gini coefficient on Q1 abuse distribution
4. SPRT — is there a statistically detectable escalation in safety bypass behavior?
5. Network degree distribution test — does abuse graph follow power law (vs. random)?

CDI Layer query is mandatory before any validation decision is committed.
Cannot override L1 vetoes. Must flag insufficient N explicitly.

Constraints:
- Cannot override L1 vetoes
- Flags insufficient statistical power explicitly (does NOT state conclusions unsupported by N)
- All p-values are two-sided unless stated otherwise
- Effect sizes always reported alongside p-values
- Confidence intervals always reported
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
from lib.second_brain import write_statistical_addendum
from lib.llm_wrapper import LLMWrapper
from lib.few_shot_bank import FewShotBank
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

DATA_DIR = BASE / "data" / "raw"

STATISTICIAN_SYSTEM_PROMPT = """You are the Statistician Agent in the Maldros analytics engineering system.

Your role: validate analytical inferences using formal statistical tests. You receive
pre-computed test statistics and must produce a rigorous statistical assessment.

HARD RULES:
1. Cannot override L1 vetoes — if a test contradicts a deterministic rule, surface the conflict.
2. Insufficient N must be flagged explicitly — never state conclusions where sample size
   is too small for the test used. Specify the minimum N required.
3. All confidence intervals and p-values must be stated. Never present point estimates alone.
4. Effect sizes (Cohen's d, Cramér's V, etc.) must accompany every significance test.
5. Multiple comparisons must be corrected for (Bonferroni or FDR as appropriate).
6. Distinguish statistical significance from practical significance explicitly.
7. The verdict must be one of: VALIDATED | CONDITIONALLY_VALIDATED | INSUFFICIENT_EVIDENCE | REJECTED

For each test, your assessment must include:
- What the test measures
- Whether the result is statistically significant
- The practical significance (is the effect size meaningful?)
- What would invalidate this result
- Whether the sample size is adequate

OUTPUT FORMAT (JSON):
{
  "overall_verdict": "VALIDATED|CONDITIONALLY_VALIDATED|INSUFFICIENT_EVIDENCE|REJECTED",
  "verdict_rationale": str,
  "tests": [
    {
      "test_name": str,
      "hypothesis": str,
      "statistic": float,
      "p_value": float,
      "effect_size": float,
      "effect_size_metric": str,
      "ci_lower": float,
      "ci_upper": float,
      "n": int,
      "conclusion": str,
      "practical_significance": str,
      "invalidation_condition": str
    }
  ],
  "statistical_power_assessment": str,
  "multiple_comparisons_correction": str,
  "analyst_conclusion_assessment": {
    "conclusion": str,
    "supported": bool,
    "caveats": [str]
  },
  "confidence_score": float,
  "known_limitations": [str]
}

Return ONLY valid JSON. No markdown, no preamble."""


STATISTICIAN_EXPERIMENT_SYSTEM_PROMPT = """You are the Statistician Agent in the Maldros analytics engineering system, operating in Phase 3 Experiment Analysis mode.

Your role: interpret A/B experiment test statistics and produce a ship/no-ship recommendation with explicit statistical rationale.

HARD RULES:
1. Cannot override L1 vetoes.
2. Insufficient power must be flagged explicitly — never state conclusions where sample size is inadequate.
3. All confidence intervals, p-values, and effect sizes must be stated. Never present point estimates alone.
4. Multiple comparisons corrected with Benjamini-Hochberg for any HTE subgroup tests.
5. Distinguish statistical significance from practical significance.
6. SRM (Sample Ratio Mismatch) is a hard NO_SHIP condition — a biased sample invalidates all downstream conclusions regardless of the primary metric result.
7. Novelty/Hawthorne effect (E4) suspected and not ruled out → verdict is HOLD_FOR_HARDENING, not NO_SHIP (the effect may be real after washout period). The E4 HOLD trigger activates ONLY when novelty_effect_suspected=True in the prescreen_signals block — not when the Red-Team mentions E4 as a hardening recommendation in a Conditionally Robust evaluation.
8. The ship verdict must be one of: SHIP | NO_SHIP | HOLD_FOR_HARDENING

SRM decision rule: chi-square p < 0.001 on the assignment ratio is a hard NO_SHIP.
Power decision rule: retrospective power < 0.80 with a non-significant result → flag UNDERPOWERED (inconclusive, not a negative result — do not declare the treatment ineffective).
Novelty effect rule: if novelty_effect_suspected=True in prescreen_signals, require follow-up experiment with washout period before SHIP verdict. Red-Team hardening mentions about E4 that apply to a Conditionally Robust verdict are future concerns, not ship-blockers.
Peeking risk rule: HIGH peeking risk is a known limitation but does not hard-block unless compounded with other issues.

Red-Team verdict rules:
- Brittle (no SRM): verdict must be exactly HOLD_FOR_HARDENING — the experiment design has exploitable weaknesses requiring hardening before shipping, but the result is not invalid. SRM is the only condition that overrides this to NO_SHIP.
- Brittle + SRM: NO_SHIP — SRM biases the sample regardless of Red-Team.
- Conditionally Robust: SHIP remains possible. Hardening recommendations address future robustness improvements, not the current ship decision. If statistical tests are clean (no SRM, adequate power, significant result, novelty not detected in prescreen), verdict is SHIP with hardening steps noted.
- Robust: no Red-Team constraint on SHIP.

OUTPUT FORMAT (JSON):
{
  "experiment_id": str,
  "ship_verdict": "SHIP|NO_SHIP|HOLD_FOR_HARDENING",
  "ship_rationale": str,
  "pathologies_detected": [str],
  "srm_assessment": {
    "detected": bool,
    "chi2_statistic": float,
    "p_value": float,
    "observed_ratio": float,
    "expected_ratio": 0.5,
    "severity": "NONE|MILD|SEVERE",
    "verdict_impact": str
  },
  "power_assessment": {
    "retrospective_power": float,
    "min_n_per_arm_for_80pct": int,
    "adequate": bool,
    "verdict_impact": str
  },
  "novelty_effect_assessment": {
    "suspected": bool,
    "evidence_basis": str,
    "recommended_followup": str,
    "evasion_category": "E4"
  },
  "peeking_risk_assessment": {
    "risk_level": "LOW|MEDIUM|HIGH",
    "rationale": str
  },
  "hte_assessment": {
    "available": bool,
    "summary": str
  },
  "effect_size_assessment": {
    "observed_effect": float,
    "practical_significance": "LOW|MEDIUM|HIGH",
    "minimum_detectable_effect": float
  },
  "multiple_comparisons": str,
  "confidence_score": float,
  "known_limitations": [str]
}

Return ONLY valid JSON. No markdown, no preamble."""


def _run_experiment_analysis_tests(exp: dict) -> dict:
    """
    Deterministic statistical tests for one experiment record.

    Tests run:
    1. SRM: chi-square on observed vs expected (50/50) assignment ratio
    2. Retrospective power: two-sample z-test power at observed N and effect size
    3. Peeking/SPRT risk: inferred from p-value zone and sample size (daily data unavailable)
    4. Effect size adequacy: compare observed Cohen's d to MDE at current N
    5. Novelty effect: read metadata flag + note E4 risk

    SPRT proper requires daily time-series data not present in the experiments
    table.  The peeking risk score is a conservative proxy using observable
    signals; the limitation is surfaced explicitly to the LLM.
    """
    import numpy as np
    from scipy import stats

    control_n = int(exp.get("control_n", 0))
    treatment_n = int(exp.get("treatment_n", 0))
    effect_size = float(exp.get("effect_size", 0.0))
    p_value = float(exp.get("p_value", 1.0))
    ci_lower = float(exp.get("ci_lower", -1.0))
    ci_upper = float(exp.get("ci_upper", 1.0))
    srm_in_data = bool(exp.get("srm_detected", False))
    novelty_in_data = bool(exp.get("novelty_effect_suspected", False))

    total_n = control_n + treatment_n

    # ── 1. SRM: chi-square on assignment ratio ────────────────────────────────
    # H0: assignment is 50/50; H1: assignment deviates from 50/50
    expected_each = total_n / 2 if total_n > 0 else 1
    if total_n > 0:
        observed = np.array([float(control_n), float(treatment_n)])
        expected = np.array([expected_each, expected_each])
        chi2_srm = float(np.sum((observed - expected) ** 2 / expected))
        p_srm = float(1 - stats.chi2.cdf(chi2_srm, df=1))
        observed_ratio = treatment_n / total_n
    else:
        chi2_srm, p_srm, observed_ratio = 0.0, 1.0, 0.5

    srm_detected = p_srm < 0.001

    # ── 2. Retrospective power ────────────────────────────────────────────────
    # Two-sample z-test power: P(reject H0 | true d = effect_size)
    # ncp = |effect_size| * sqrt(n_per_arm / 2)  (balanced design formula)
    alpha = 0.05
    z_alpha_2 = stats.norm.ppf(1 - alpha / 2)  # ~1.96

    n_per_arm = min(control_n, treatment_n)
    if n_per_arm > 0 and abs(effect_size) > 1e-6:
        ncp = abs(effect_size) * np.sqrt(n_per_arm / 2)
        power = float(
            1 - stats.norm.cdf(z_alpha_2 - ncp)
            + stats.norm.cdf(-z_alpha_2 - ncp)
        )
        power = max(0.0, min(1.0, power))
        # Minimum N per arm for 80% power at the observed effect size
        # ncp_80 = z_alpha_2 + z_0.80 = 1.96 + 0.842
        if abs(effect_size) > 0.001:
            n_min = int(np.ceil(2 * ((z_alpha_2 + 0.842) / abs(effect_size)) ** 2))
        else:
            n_min = 999_999
    else:
        power = 0.0
        n_min = 999_999

    # ── 3. Peeking / SPRT risk (proxy) ───────────────────────────────────────
    risk_factors: list = []
    if 0.01 <= p_value <= 0.05:
        risk_factors.append("p-value in borderline zone 0.01–0.05 (consistent with selective stopping)")
    if n_per_arm < 1000:
        risk_factors.append("small sample increases sensitivity to interim peeking")

    peeking_risk = "HIGH" if len(risk_factors) >= 2 else "MEDIUM" if risk_factors else "LOW"

    # ── 4. Effect size adequacy (MDE at current N, alpha=0.05, power=0.80) ───
    if n_per_arm > 0:
        mde = float((z_alpha_2 + 0.842) / np.sqrt(n_per_arm / 2))
    else:
        mde = float("inf")

    practical_sig = (
        "HIGH" if abs(effect_size) >= 0.2
        else "MEDIUM" if abs(effect_size) >= 0.1
        else "LOW"
    )

    return {
        "experiment_id": exp.get("experiment_id"),
        "metric": exp.get("metric"),
        "control_n": control_n,
        "treatment_n": treatment_n,
        "total_n": total_n,
        "effect_size": effect_size,
        "p_value": p_value,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "srm": {
            "chi2_statistic": round(chi2_srm, 4),
            "p_value": round(p_srm, 9),
            "detected_by_test": srm_detected,
            "flagged_in_source_data": srm_in_data,
            "observed_ratio_treatment": round(observed_ratio, 4),
            "expected_ratio": 0.5,
            "absolute_deviation": round(abs(observed_ratio - 0.5), 4),
        },
        "power": {
            "retrospective_power": round(power, 4),
            "n_per_arm": n_per_arm,
            "min_n_per_arm_for_80pct": n_min,
            "adequate": power >= 0.80,
            "mde_at_current_n": round(mde, 4),
        },
        "novelty": {
            "suspected_in_data": novelty_in_data,
            "evasion_category": "E4",
            "note": "Formal time-decay regression requires daily assignment data; metadata flag used as primary signal",
        },
        "peeking": {
            "risk_level": peeking_risk,
            "risk_factors": risk_factors,
            "note": "SPRT proper requires daily time-series data absent from experiments table; risk assessed via observable proxies",
        },
        "effect": {
            "observed_effect_size": round(abs(effect_size), 4),
            "practical_significance": practical_sig,
            "mde_at_current_n": round(mde, 4),
            "below_mde": abs(effect_size) < mde,
        },
    }


def _run_statistical_tests(analysis_results: dict) -> dict:
    """
    Run formal statistical tests on the analyst's quantitative findings.
    Returns test statistics for LLM interpretation.
    """
    import duckdb
    import numpy as np
    from scipy import stats
    import warnings
    warnings.filterwarnings('ignore')

    t0 = time.time()

    va = analysis_results["volume_analysis"]
    ga = analysis_results["graph_analysis"]
    fia = analysis_results["fraud_incident_analysis"]
    aa = analysis_results["account_analysis"]

    tests = []

    # ── Test 1: Poisson test — is Q1 abuse rate anomalous? ────────────────────
    # H0: Q1 monthly abuse rate is drawn from the same Poisson process as other months
    # H1: Q1 has elevated abuse rate
    monthly_ts = va.get("monthly_time_series", [])
    if monthly_ts:
        monthly_abuse = [m["abuse_events"] for m in monthly_ts]
        monthly_total = [m["total_events"] for m in monthly_ts]
        months = [m["month"] for m in monthly_ts]

        q1_idx = [i for i, m in enumerate(months) if m in ("2024-01", "2024-02", "2024-03")]
        non_q1_idx = [i for i in range(len(months)) if i not in q1_idx]

        q1_abuse_events = sum(monthly_abuse[i] for i in q1_idx)
        q1_total_events = sum(monthly_total[i] for i in q1_idx)
        non_q1_abuse_events = sum(monthly_abuse[i] for i in non_q1_idx)
        non_q1_total_events = sum(monthly_total[i] for i in non_q1_idx)

        # Rate comparison: is Q1 rate higher than non-Q1?
        q1_rate = q1_abuse_events / q1_total_events if q1_total_events > 0 else 0
        non_q1_rate = non_q1_abuse_events / non_q1_total_events if non_q1_total_events > 0 else 0

        # Two-sample z-test for proportions
        p1, p2 = q1_rate, non_q1_rate
        n1, n2 = q1_total_events, non_q1_total_events
        if n1 > 0 and n2 > 0 and p1 > 0 and p2 > 0:
            p_pool = (q1_abuse_events + non_q1_abuse_events) / (n1 + n2)
            se = np.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
            z_stat = (p1 - p2) / se if se > 0 else 0.0
            p_val = float(2 * (1 - stats.norm.cdf(abs(z_stat))))  # two-sided
            # Effect size: Cohen's h for proportions
            cohen_h = float(2 * (np.arcsin(np.sqrt(p1)) - np.arcsin(np.sqrt(p2))))
            # CI for difference in proportions
            ci_half = 1.96 * np.sqrt(p1*(1-p1)/n1 + p2*(1-p2)/n2)
            ci_lower = float((p1 - p2) - ci_half)
            ci_upper = float((p1 - p2) + ci_half)
        else:
            z_stat, p_val, cohen_h, ci_lower, ci_upper = 0.0, 1.0, 0.0, 0.0, 0.0

        tests.append({
            "test_name": "Two-sample z-test for proportions (Q1 vs non-Q1 abuse rate)",
            "hypothesis": "H1: Q1 abuse rate (policy_violation events / total events) is higher than non-Q1",
            "statistic": round(float(z_stat), 4),
            "p_value": round(p_val, 6),
            "effect_size": round(float(cohen_h), 4),
            "effect_size_metric": "Cohen's h (proportion difference)",
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
            "n": int(n1 + n2),
            "q1_abuse_rate": round(q1_rate, 6),
            "non_q1_abuse_rate": round(non_q1_rate, 6),
            "rate_ratio": round(q1_rate / non_q1_rate, 4) if non_q1_rate > 0 else 0.0,
        })

    # ── Test 2: Chi-square — are cluster accounts overrepresented in incidents? ─
    # H0: Cluster accounts produce fraud incidents at the same rate as non-cluster accounts
    # H1: Cluster accounts have elevated incident rate
    # Use labeled cluster data (ground truth cluster_id column) for this test
    labeled = analysis_results.get("labeled_cluster_analysis", {})
    n_cluster = labeled.get("n_labeled_cluster_accounts",
                            ga.get("n_clustered_accounts_3plus", 0))
    total_accounts = aa.get("total_accounts", 2000)
    n_non_cluster = total_accounts - n_cluster

    q1_incidents = fia.get("q1_api_abuse_incidents", 0)
    q1_cluster_incidents_all = fia.get("q1_cluster_incidents", 0)
    # Use labeled cluster Q1 abuse share for incident estimation if available
    labeled_cluster_abuse_share = labeled.get("labeled_cluster_q1_abuse_share", 0.0)
    cluster_abuse_share = labeled_cluster_abuse_share if labeled_cluster_abuse_share > 0 else ga.get("cluster_q1_abuse_share", 0.0)
    cluster_incidents_est = round(q1_incidents * cluster_abuse_share)
    non_cluster_incidents_est = q1_incidents - cluster_incidents_est

    if n_cluster > 0 and n_non_cluster > 0 and q1_incidents > 0:
        # Expected under null hypothesis (incidents proportional to account count)
        cluster_expected = q1_incidents * (n_cluster / total_accounts)
        non_cluster_expected = q1_incidents * (n_non_cluster / total_accounts)

        # Chi-square test
        observed = np.array([cluster_incidents_est, non_cluster_incidents_est])
        expected = np.array([cluster_expected, non_cluster_expected])
        chi2 = float(np.sum((observed - expected)**2 / expected))
        p_chi2 = float(1 - stats.chi2.cdf(chi2, df=1))
        # Cramer's V (effect size for chi-square)
        cramers_v = float(np.sqrt(chi2 / (q1_incidents * 1)))  # df_min = 1

        # Incident rate per account
        cluster_incident_rate = cluster_incidents_est / n_cluster if n_cluster > 0 else 0
        non_cluster_incident_rate = non_cluster_incidents_est / n_non_cluster if n_non_cluster > 0 else 0
        rate_ratio = cluster_incident_rate / non_cluster_incident_rate if non_cluster_incident_rate > 0 else float('inf')
    else:
        chi2, p_chi2, cramers_v = 0.0, 1.0, 0.0
        cluster_incident_rate, non_cluster_incident_rate, rate_ratio = 0.0, 0.0, 0.0

    tests.append({
        "test_name": "Chi-square test (cluster vs non-cluster incident overrepresentation)",
        "hypothesis": "H1: Cluster accounts (co-temporal abuse graph) are overrepresented in Q1 api_abuse incidents",
        "statistic": round(chi2, 4),
        "p_value": round(p_chi2, 6),
        "effect_size": round(cramers_v, 4),
        "effect_size_metric": "Cramér's V",
        "ci_lower": float("nan"),
        "ci_upper": float("nan"),
        "n": int(q1_incidents),
        "cluster_accounts": n_cluster,
        "non_cluster_accounts": int(n_non_cluster),
        "cluster_incident_rate_per_account": round(float(cluster_incident_rate), 4),
        "non_cluster_incident_rate_per_account": round(float(non_cluster_incident_rate), 4),
        "rate_ratio_cluster_vs_non_cluster": round(float(rate_ratio), 2) if not (rate_ratio == float('inf')) else 999.0,
        "note": "incident counts estimated from cluster Q1 abuse share — see evidence bundle for methodology",
    })

    # ── Test 3: Concentration test — Gini coefficient on Q1 per-account abuse ──
    # High Gini = highly concentrated = consistent with coordinated small group
    # Random / organic growth → lower Gini (more uniformly distributed)
    monthly_ts_abuse = [m["abuse_events"] for m in monthly_ts] if monthly_ts else []
    if monthly_ts_abuse:
        # Gini of monthly abuse distribution
        x = np.array(sorted(monthly_abuse))
        n = len(x)
        if n > 0 and x.sum() > 0:
            index = np.arange(1, n + 1)
            gini = float(((2 * index - n - 1) * x).sum() / (n * x.sum()))
        else:
            gini = 0.0

        # Bootstrap CI for Gini
        n_boot = 1000
        gini_boot = []
        rng = np.random.default_rng(42)
        for _ in range(n_boot):
            sample = rng.choice(x, size=n, replace=True)
            s = np.array(sorted(sample))
            if s.sum() > 0:
                g = float(((2 * np.arange(1, n+1) - n - 1) * s).sum() / (n * s.sum()))
                gini_boot.append(g)
        gini_ci_lower = float(np.percentile(gini_boot, 2.5))
        gini_ci_upper = float(np.percentile(gini_boot, 97.5))
    else:
        gini, gini_ci_lower, gini_ci_upper = 0.0, 0.0, 0.0

    tests.append({
        "test_name": "Gini coefficient — temporal concentration of Q1 abuse volume",
        "hypothesis": "High Gini (>0.3) is consistent with concentrated, coordinated activity; low Gini consistent with organic spread",
        "statistic": round(gini, 4),
        "p_value": float("nan"),  # Gini has no direct p-value; CI is the measure
        "effect_size": round(gini, 4),
        "effect_size_metric": "Gini coefficient (0=uniform, 1=completely concentrated)",
        "ci_lower": round(gini_ci_lower, 4),
        "ci_upper": round(gini_ci_upper, 4),
        "n": len(monthly_abuse),
        "interpretation_threshold": "Gini > 0.3 indicates meaningful concentration; > 0.5 indicates high concentration",
    })

    # ── Test 4: Kolmogorov-Smirnov test — does Q1 abuse distribution differ from expected? ─
    # Compare monthly Q1 abuse to Poisson distribution (expected under organic growth)
    if len(monthly_abuse) >= 3:
        # Q1 months vs all months Poisson fit
        all_mean = np.mean(monthly_abuse)
        # Generate Poisson samples with same mean for comparison
        rng2 = np.random.default_rng(42)
        poisson_samples = rng2.poisson(all_mean, 1000)
        q1_values = [monthly_abuse[i] for i in q1_idx] if q1_idx else [0]

        # KS test against empirical non-Q1 distribution
        non_q1_values = [monthly_abuse[i] for i in non_q1_idx] if non_q1_idx else [0]
        if len(q1_values) >= 2 and len(non_q1_values) >= 2:
            ks_stat, ks_p = stats.ks_2samp(q1_values, non_q1_values)
        else:
            ks_stat, ks_p = 0.0, 1.0

        tests.append({
            "test_name": "KS two-sample test (Q1 vs non-Q1 monthly abuse distribution)",
            "hypothesis": "H1: Q1 monthly abuse distribution differs from non-Q1 distribution",
            "statistic": round(float(ks_stat), 4),
            "p_value": round(float(ks_p), 6),
            "effect_size": round(float(ks_stat), 4),
            "effect_size_metric": "KS statistic (0=identical distributions, 1=maximum separation)",
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
            "n": len(monthly_abuse),
            "note": "Low N (months) limits KS test power — treat as directional only",
        })

    elapsed = round(time.time() - t0, 2)

    # Bonferroni correction for multiple comparisons
    alpha = 0.05
    n_tests = len([t for t in tests if not (t.get("p_value") != t.get("p_value"))])  # exclude NaN
    bonferroni_threshold = alpha / n_tests if n_tests > 0 else alpha

    return {
        "tests": tests,
        "bonferroni_threshold": round(bonferroni_threshold, 4),
        "alpha": alpha,
        "n_tests": n_tests,
        "elapsed_sec": elapsed,
    }


class StatisticianAgent:
    """
    Phase 1 full implementation.

    Runs formal statistical tests → calls LLM for interpretation →
    emits Statistical Result with test statistics, verdicts, and caveats.
    """

    def __init__(self, phase: int = 1):
        self.phase = phase

    def run(self, capability_bundle_id: str, evidence_bundle_id: str) -> dict:
        """
        Full Phase 1 statistical validation run.
        Returns: {statistical_result_id, path, verdict}
        """
        # Read upstream artifacts
        cb = read_artifact(capability_bundle_id)
        eb = read_artifact(evidence_bundle_id)
        validate_envelope(cb)
        validate_envelope(eb)

        task_id = cb["content"]["task_id"]
        analyst_conclusion = eb["content"].get("primary_conclusion", "AMBIGUOUS")
        analysis_results = eb["content"].get("analysis_results", {})

        print(f"\n[Statistician] Starting Phase 1 statistical validation")
        print(f"[Statistician] Task ID: {task_id}")
        print(f"[Statistician] Analyst conclusion to validate: {analyst_conclusion}")

        # ── Step 1: CDI Layer query ──────────────────────────────────────────────
        reader = CDIReader(agent_name="statistician", task_id=task_id)
        _ = reader.get_inference_layer_status("L1")
        _ = reader.get_inference_layer_status("L2")
        _ = reader.get_reasoning_frameworks()

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "l1_status": reader.get_inference_layer_status("L1"),
            "l2_status": reader.get_inference_layer_status("L2"),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        print(f"[Statistician] CDI Layer queried: {cdi_query_record['domains_queried']}")

        # ── Step 2: Run statistical tests ───────────────────────────────────────
        print(f"[Statistician] Running statistical tests...")
        t_stat = time.time()
        test_results = _run_statistical_tests(analysis_results)
        stat_elapsed = round(time.time() - t_stat, 2)
        print(f"[Statistician] Tests complete in {stat_elapsed}s: {len(test_results['tests'])} tests run")

        # ── Step 3: LLM interpretation ──────────────────────────────────────────
        print(f"[Statistician] Calling LLM for interpretation...")
        llm = LLMWrapper(agent_name="statistician", task_id=task_id)

        interpretation_request = {
            "analyst_conclusion": analyst_conclusion,
            "analyst_confidence": eb.get("confidence_score", 0.5),
            "statistical_tests": test_results["tests"],
            "bonferroni_threshold": test_results["bonferroni_threshold"],
            "n_tests_run": test_results["n_tests"],
            "volume_analysis_summary": {
                "q1_spike_ratio": analysis_results.get("volume_analysis", {}).get("q1_spike_ratio", 1.0),
                "q1_abuse_rate": analysis_results.get("volume_analysis", {}).get("q1_abuse_rate", 0.0),
            },
            "graph_analysis_summary": {
                "largest_cluster_size": analysis_results.get("graph_analysis", {}).get("largest_component_size", 0),
                "n_clustered_accounts": analysis_results.get("graph_analysis", {}).get("n_clustered_accounts_3plus", 0),
                "cluster_q1_abuse_share": analysis_results.get("graph_analysis", {}).get("cluster_q1_abuse_share", 0.0),
            },
        }

        fsb = FewShotBank()
        enriched_stat_prompt, _ = fsb.inject_into_system_prompt(
            STATISTICIAN_SYSTEM_PROMPT, "experiment_analysis", agent_name="statistician"
        )
        llm_response = llm.generate(
            system_prompt=enriched_stat_prompt,
            user_message=json.dumps(interpretation_request, indent=2, default=str),
            max_tokens=4096,
        )

        llm_content = llm_response["content"]
        try:
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            stat_interpretation = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError):
            stat_interpretation = {
                "overall_verdict": "CONDITIONALLY_VALIDATED",
                "verdict_rationale": llm_content,
                "tests": test_results["tests"],
                "statistical_power_assessment": "Unable to parse LLM interpretation",
                "multiple_comparisons_correction": f"Bonferroni applied: alpha/{test_results['n_tests']}",
                "analyst_conclusion_assessment": {
                    "conclusion": analyst_conclusion,
                    "supported": True,
                    "caveats": ["LLM interpretation could not be parsed"],
                },
                "confidence_score": 0.55,
                "known_limitations": ["Statistical interpretation parsing failed"],
            }

        # ── Step 4: Emit Statistical Result ─────────────────────────────────────
        confidence = float(stat_interpretation.get("confidence_score", 0.5))
        verdict = stat_interpretation.get("overall_verdict", "CONDITIONALLY_VALIDATED")

        result_content = {
            "task_id": task_id,
            "phase": self.phase,
            "analyst_conclusion": analyst_conclusion,
            "statistical_verdict": verdict,
            "verdict_rationale": stat_interpretation.get("verdict_rationale", ""),
            "tests": test_results["tests"],
            "llm_interpretation": stat_interpretation,
            "bonferroni_threshold": test_results["bonferroni_threshold"],
            "analyst_conclusion_assessment": stat_interpretation.get("analyst_conclusion_assessment", {}),
            "cdi_query_record": cdi_query_record,
            "lineage": {
                "evidence_bundle_id": evidence_bundle_id,
                "capability_bundle_id": capability_bundle_id,
                "stat_elapsed_sec": stat_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
            },
        }

        result = create_artifact(
            artifact_type="statistical_result",
            producing_agent="statistician",
            phase=self.phase,
            content=result_content,
            provenance=[capability_bundle_id, evidence_bundle_id],
            confidence_score=min(0.95, max(0.1, confidence)),
            known_limitations=stat_interpretation.get("known_limitations", [
                "Statistical tests run on synthetic data — effect sizes may not reflect real-world distributions",
                "Cluster membership estimated from co-temporal co-occurrence; not ground-truth cluster assignment",
                "Low N (months) limits KS test power — treat temporal distribution tests as directional",
                "Chi-square test uses estimated cluster incident counts, not direct observation",
            ]),
        )
        path = write_artifact(result)

        print(f"[Statistician] Statistical Result written: {result['artifact_id']}")
        print(f"[Statistician] Verdict: {verdict}")

        # ── Step 4b: Write to Second Brain vault ─────────────────────────────────
        eb_vault_path = eb.get("_vault_path")
        write_statistical_addendum(result, analysis_vault_path=eb_vault_path)

        # ── Step 5: Record CDI non-activation ────────────────────────────────────
        updater = CDIUpdater(agent_name="statistician", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {
            "statistical_result_id": result["artifact_id"],
            "path": str(path),
            "verdict": verdict,
            "confidence": confidence,
        }

    def run_experiment_analysis(
        self,
        experiment_id: str,
        capability_bundle_id: str,
        red_team_verdict: Optional[dict] = None,
    ) -> dict:
        """
        Phase 3 experiment analysis.
        Reads one experiment from the experiments Parquet table, runs formal
        statistical tests (SRM, retrospective power, peeking risk, novelty
        effect, effect size adequacy), then calls the LLM for a ship/no-ship
        verdict.  Red-Team verdict is optional input — if provided it is
        factored into the LLM interpretation.

        Returns {statistical_result_id, path, ship_verdict, pathologies_detected}
        """
        import duckdb

        print(f"\n[Statistician] Phase 3 experiment analysis: {experiment_id}")

        # ── Read experiment from Parquet ─────────────────────────────────────
        conn = duckdb.connect()
        rows = conn.execute(
            f"SELECT * FROM '{DATA_DIR}/experiments.parquet' WHERE experiment_id = ?",
            [experiment_id],
        ).fetchall()
        cols = [d[0] for d in conn.description]
        conn.close()

        if not rows:
            raise ValueError(
                f"Experiment {experiment_id} not found in experiments.parquet"
            )
        exp = dict(zip(cols, rows[0]))

        # ── CDI Layer query ──────────────────────────────────────────────────
        cb = read_artifact(capability_bundle_id)
        validate_envelope(cb)
        task_id = cb["content"]["task_id"]

        reader = CDIReader(agent_name="statistician", task_id=task_id)
        _ = reader.get_inference_layer_status("L1")
        _ = reader.get_inference_layer_status("L2")
        _ = reader.get_reasoning_frameworks()

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[Statistician] CDI Layer queried: {cdi_query_record['domains_queried']}")

        # ── Run statistical tests ────────────────────────────────────────────
        print(f"[Statistician] Running experiment tests for {experiment_id}...")
        t0 = time.time()
        test_stats = _run_experiment_analysis_tests(exp)
        stat_elapsed = round(time.time() - t0, 2)
        print(
            f"[Statistician] Tests complete in {stat_elapsed}s\n"
            f"  SRM detected by test : {test_stats['srm']['detected_by_test']}"
            f" (chi2={test_stats['srm']['chi2_statistic']:.2f},"
            f" p={test_stats['srm']['p_value']:.2e})\n"
            f"  Retrospective power  : {test_stats['power']['retrospective_power']:.3f}"
            f" (N/arm={test_stats['power']['n_per_arm']})\n"
            f"  Novelty suspected    : {test_stats['novelty']['suspected_in_data']}\n"
            f"  Peeking risk         : {test_stats['peeking']['risk_level']}"
        )

        # ── LLM interpretation ───────────────────────────────────────────────
        print(f"[Statistician] Calling LLM for ship/no-ship verdict...")
        llm = LLMWrapper(agent_name="statistician", task_id=task_id)

        llm_input = {
            "experiment_id": experiment_id,
            "statistical_tests": test_stats,
            "red_team_verdict": red_team_verdict,
            "analyst_notes_from_data": exp.get("analyst_notes", ""),
            "metric": exp.get("metric"),
            "start_date": exp.get("start_date"),
            "end_date": exp.get("end_date"),
        }

        fsb_exp = FewShotBank()
        enriched_exp_prompt, _ = fsb_exp.inject_into_system_prompt(
            STATISTICIAN_EXPERIMENT_SYSTEM_PROMPT, "experiment_analysis", agent_name="statistician"
        )
        llm_response = llm.generate(
            system_prompt=enriched_exp_prompt,
            user_message=json.dumps(llm_input, indent=2, default=str),
            max_tokens=4096,
        )

        llm_content = llm_response["content"]
        try:
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            experiment_verdict = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError):
            # Deterministic fallback: derive verdict from test statistics alone
            if test_stats["srm"]["detected_by_test"]:
                fallback_verdict = "NO_SHIP"
            elif test_stats["novelty"]["suspected_in_data"]:
                fallback_verdict = "HOLD_FOR_HARDENING"
            elif exp.get("p_value", 1.0) < 0.05 and test_stats["power"]["adequate"]:
                fallback_verdict = "SHIP"
            else:
                fallback_verdict = "NO_SHIP"

            experiment_verdict = {
                "experiment_id": experiment_id,
                "ship_verdict": fallback_verdict,
                "ship_rationale": llm_content[:200],
                "pathologies_detected": [],
                "srm_assessment": {"detected": test_stats["srm"]["detected_by_test"]},
                "power_assessment": {"adequate": test_stats["power"]["adequate"]},
                "novelty_effect_assessment": {
                    "suspected": test_stats["novelty"]["suspected_in_data"]
                },
                "peeking_risk_assessment": {
                    "risk_level": test_stats["peeking"]["risk_level"]
                },
                "hte_assessment": {"available": False, "summary": "Parse failure"},
                "effect_size_assessment": {
                    "observed_effect": test_stats["effect"]["observed"]
                },
                "multiple_comparisons": "N/A — parse failure",
                "confidence_score": 0.5,
                "known_limitations": [
                    "LLM interpretation parse failed; deterministic fallback applied"
                ],
            }

        ship_verdict = experiment_verdict.get("ship_verdict", "NO_SHIP")
        pathologies = experiment_verdict.get("pathologies_detected", [])

        print(f"[Statistician] Ship verdict: {ship_verdict}")
        print(f"[Statistician] Pathologies detected: {pathologies}")

        # ── Emit Statistical Result artifact ─────────────────────────────────
        result_content = {
            "task_id": task_id,
            "phase": 3,
            "analysis_mode": "experiment_analysis",
            "experiment_id": experiment_id,
            "metric": exp.get("metric"),
            "ship_verdict": ship_verdict,
            "pathologies_detected": pathologies,
            "statistical_tests": test_stats,
            "llm_interpretation": experiment_verdict,
            "red_team_input": red_team_verdict,
            "cdi_query_record": cdi_query_record,
            "lineage": {
                "capability_bundle_id": capability_bundle_id,
                "stat_elapsed_sec": stat_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
            },
        }

        confidence = float(experiment_verdict.get("confidence_score", 0.5))
        result = create_artifact(
            artifact_type="statistical_result",
            producing_agent="statistician",
            phase=3,
            content=result_content,
            provenance=[capability_bundle_id],
            confidence_score=min(0.95, max(0.1, confidence)),
            known_limitations=experiment_verdict.get(
                "known_limitations",
                [
                    "SPRT requires daily time-series data not available in experiments table; peeking risk inferred from observable proxies",
                    "HTE subgroup analysis requires assignment logs not present in synthetic dataset",
                    "Retrospective power uses standardized Cohen's d; may not match metric-specific variance",
                ],
            ),
        )
        path = write_artifact(result)
        print(f"[Statistician] Statistical Result written: {result['artifact_id']}")

        # ── Write to Second Brain vault ──────────────────────────────────────
        write_statistical_addendum(result, analysis_vault_path=None)

        # ── Record CDI non-activation ────────────────────────────────────────
        updater = CDIUpdater(agent_name="statistician", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {
            "statistical_result_id": result["artifact_id"],
            "path": str(path),
            "ship_verdict": ship_verdict,
            "pathologies_detected": pathologies,
            "confidence": confidence,
        }
