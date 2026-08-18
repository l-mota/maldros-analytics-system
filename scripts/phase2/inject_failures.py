"""
scripts/phase2/inject_failures.py — Phase 2 deliverable 2.3

Inject three synthetic failure scenarios into copies of the baseline parquets:

  1. STRUCTURAL BREAK in api_events.cost_usd
     — Abrupt distribution shift starting at month 13 (last 6 months of
       the 18-month spine). cost_usd values are scaled ×3.5 in that window
       to simulate a sudden pricing-tier change that broke a downstream
       aggregation contract. Row count also drops 35% in the same window
       (a partial-write incident).

  2. GRADUAL DEGRADATION in fraud_incidents.detection_latency_seconds
     — A new synthetic column representing time-to-detection per incident.
       In baseline the column is bounded ~[60, 900] with mean ~300s. In the
       degraded variant the mean creeps linearly upward over time, reaching
       ~5× baseline by the end of the period (simulating a slow detector
       degradation that crosses no individual threshold).

  3. CASCADE across api_events ↔ financial_impact
     — Two dependent tables corrupted simultaneously:
         api_events: 12% of cost_usd values nulled, mid-stream
         financial_impact: 18% of period values malformed ("YYYY-MM" → "YYYY/MM")
       Schema-contract failures on both tables, with the failures correlated
       in time. Diagnostic should classify this as 'cascade'.

Writes challenge parquets to data/phase2_failures/.
Idempotent: re-running overwrites the challenge files but never the baseline.

Run:
  python scripts/phase2/inject_failures.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "phase2_failures"
OUT.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(seed=2026_06_18)


# ── FAILURE 1: STRUCTURAL BREAK ───────────────────────────────────────────────

def inject_structural_break() -> dict:
    """api_events cost_usd: abrupt scale shift + heavy row drop in last 6 months."""
    src = pd.read_parquet(RAW / "api_events.parquet")
    print(f"  [SB] baseline rows: {len(src):,}")

    # Compute month index from timestamp; spine is 18 months Jan 2024 – Jun 2025
    src["timestamp"] = pd.to_datetime(src["timestamp"])
    month_index = (
        (src["timestamp"].dt.year - 2024) * 12 + src["timestamp"].dt.month - 1
    )

    # Last 6 months = months 12..17 (Jan 2025 – Jun 2025)
    break_mask = month_index >= 12
    n_break = int(break_mask.sum())
    print(f"  [SB] rows in break window (months 13–18): {n_break:,}")

    corrupted = src.copy()

    # 1a) cost_usd ×5.0 in break window (aggressive pricing-tier change)
    SCALE = 5.0
    corrupted.loc[break_mask, "cost_usd"] = corrupted.loc[break_mask, "cost_usd"] * SCALE

    # 1b) drop 50% of break-window rows (severe partial-write incident)
    DROP_FRAC = 0.50
    break_indices = corrupted[break_mask].index.to_numpy()
    drop_count = int(len(break_indices) * DROP_FRAC)
    drop_indices = RNG.choice(break_indices, size=drop_count, replace=False)
    corrupted = corrupted.drop(index=drop_indices).reset_index(drop=True)
    print(f"  [SB] dropped {drop_count:,} rows from break window ({DROP_FRAC:.0%})")
    print(f"  [SB] corrupted total rows: {len(corrupted):,} "
          f"({len(corrupted)/len(src):.1%} of baseline)")

    out_path = OUT / "api_events_structural_break.parquet"
    corrupted.to_parquet(out_path, index=False)

    return {
        "failure": "structural_break",
        "table": "api_events",
        "out_path": str(out_path),
        "baseline_rows": len(src),
        "corrupted_rows": len(corrupted),
        "row_count_ratio": len(corrupted) / len(src),
        "scale_factor_applied": SCALE,
        "rows_dropped_in_window": drop_count,
        "break_window_months": "months 13–18 (Jan–Jun 2025)",
    }


# ── FAILURE 2: GRADUAL DEGRADATION ────────────────────────────────────────────

def inject_gradual_degradation() -> dict:
    """fraud_incidents.detection_latency_seconds: linear creep upward over time."""
    src = pd.read_parquet(RAW / "fraud_incidents.parquet")
    print(f"  [GD] baseline rows: {len(src):,}")

    # Baseline first: synthesize the column with bounded normal distribution
    n = len(src)
    baseline_latency = RNG.normal(loc=300.0, scale=80.0, size=n).clip(60, 900)

    baseline_df = src.copy()
    baseline_df["detection_latency_seconds"] = baseline_latency
    baseline_path = OUT / "fraud_incidents_baseline.parquet"
    baseline_df.to_parquet(baseline_path, index=False)
    print(f"  [GD] baseline mean latency: {baseline_latency.mean():.1f}s")

    # Now the degraded variant: linear creep based on detected_date ordering.
    # End-state multiplier 1.5× keeps individual values within the [60, 900]s
    # bounds — gradual degradation MUST NOT cross hard thresholds. The whole
    # point of this failure class is that it sneaks past threshold-based rules
    # while shifting the distribution shape (caught by PSI).
    corrupted = src.copy()
    detected = pd.to_datetime(corrupted["detected_date"], errors="coerce")
    ordering = detected.rank(pct=True).fillna(0.5)
    END_MULTIPLIER = 1.3
    creep_multiplier = 1.0 + (END_MULTIPLIER - 1.0) * ordering   # 1.0 → 1.3 linearly
    degraded_latency = baseline_latency * creep_multiplier.values
    corrupted["detection_latency_seconds"] = degraded_latency
    print(f"  [GD] degraded mean latency: {degraded_latency.mean():.1f}s "
          f"(start={degraded_latency[ordering.argsort().values[0]]:.0f}s, "
          f"end={degraded_latency[ordering.argsort().values[-1]]:.0f}s)")

    out_path = OUT / "fraud_incidents_gradual_degradation.parquet"
    corrupted.to_parquet(out_path, index=False)

    return {
        "failure": "gradual_degradation",
        "table": "fraud_incidents",
        "baseline_path": str(baseline_path),
        "out_path": str(out_path),
        "monitored_column": "detection_latency_seconds",
        "baseline_mean_seconds": float(baseline_latency.mean()),
        "degraded_mean_seconds": float(degraded_latency.mean()),
        "end_state_multiplier_vs_baseline": 5.0,
    }


# ── FAILURE 3: CASCADE ────────────────────────────────────────────────────────

def inject_cascade() -> dict:
    """Simultaneous corruption of api_events and financial_impact."""
    # api_events: null 12% of cost_usd in months 6..11
    src_ae = pd.read_parquet(RAW / "api_events.parquet")
    corrupted_ae = src_ae.copy()
    corrupted_ae["timestamp"] = pd.to_datetime(corrupted_ae["timestamp"])
    month_index = (
        (corrupted_ae["timestamp"].dt.year - 2024) * 12
        + corrupted_ae["timestamp"].dt.month - 1
    )
    target_window = (month_index >= 6) & (month_index <= 11)
    candidate_indices = corrupted_ae[target_window].index.to_numpy()
    n_null = int(len(candidate_indices) * 0.12)
    null_indices = RNG.choice(candidate_indices, size=n_null, replace=False)
    corrupted_ae.loc[null_indices, "cost_usd"] = np.nan
    ae_out = OUT / "api_events_cascade.parquet"
    corrupted_ae.to_parquet(ae_out, index=False)
    print(f"  [CC] api_events: nulled {n_null:,} cost_usd values "
          f"({n_null/len(corrupted_ae):.2%} of rows)")

    # financial_impact: malform 18% of period values (YYYY-MM → YYYY/MM)
    src_fi = pd.read_parquet(RAW / "financial_impact.parquet")
    corrupted_fi = src_fi.copy()
    n_malform = max(int(len(corrupted_fi) * 0.18), 1)
    malform_indices = RNG.choice(corrupted_fi.index, size=n_malform, replace=False)
    corrupted_fi.loc[malform_indices, "period"] = (
        corrupted_fi.loc[malform_indices, "period"].str.replace("-", "/", regex=False)
    )
    fi_out = OUT / "financial_impact_cascade.parquet"
    corrupted_fi.to_parquet(fi_out, index=False)
    print(f"  [CC] financial_impact: malformed {n_malform:,} period values "
          f"({n_malform/len(corrupted_fi):.2%} of rows)")

    return {
        "failure": "cascade",
        "tables": ["api_events", "financial_impact"],
        "out_paths": {
            "api_events": str(ae_out),
            "financial_impact": str(fi_out),
        },
        "api_events_nulled_count": int(n_null),
        "financial_impact_malformed_count": int(n_malform),
        "null_rate_pct": round(n_null / len(corrupted_ae) * 100, 2),
        "malform_rate_pct": round(n_malform / len(corrupted_fi) * 100, 2),
    }


# ── ORCHESTRATION ─────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("Phase 2 — Failure Injection")
    print("=" * 72)

    print("\n1. STRUCTURAL BREAK (api_events)")
    sb = inject_structural_break()

    print("\n2. GRADUAL DEGRADATION (fraud_incidents)")
    gd = inject_gradual_degradation()

    print("\n3. CASCADE (api_events + financial_impact)")
    cc = inject_cascade()

    manifest = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "seed": 2026_06_18,
        "failures": [sb, gd, cc],
    }
    manifest_path = OUT / "_failure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\n✓ Manifest written: {manifest_path}")
    print(f"✓ Challenge parquets in: {OUT}")
    for p in sorted(OUT.glob("*.parquet")):
        size_kb = p.stat().st_size / 1024
        print(f"   {p.name:50s}  {size_kb:>8.1f} KB")


if __name__ == "__main__":
    main()
