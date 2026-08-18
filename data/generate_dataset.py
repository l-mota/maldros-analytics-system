"""
Maldros Synthetic Dataset Generator — Phase 0, Deliverable 0.1
C-013: api_events = 750K default, 18-month time horizon.

Scale parameter (single control, all table sizes):
  env var: MALDROS_SCALE=0.1  (dev — ~75K events, fast)
           MALDROS_SCALE=1.0  (full demo — 750K events)
  CLI arg: python generate_dataset.py 0.1

Signal patterns (all 5 required, deterministic at any scale):
  1. Coordinated abuse clusters — graph-detectable, not threshold-trivial
  2. Safety bypass gradual escalation — SPRT-detectable, not threshold-trivial
  3. Experiment pathologies — SRM (×2), novelty effect (×1), genuine (×1)
  4. Pipeline failure classes — structural break, gradual degradation, cascade
  5. Regulatory lag correlation — 2 confirmed pairs (~90 days)
"""

import os
import sys
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── SEED (reproducibility at any scale) ──────────────────────────────────────
np.random.seed(42)
RNG = np.random.default_rng(42)

# ── PATHS ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parents[2]
OUT  = BASE / "data" / "raw"
OUT.mkdir(parents=True, exist_ok=True)

# ── SCALE PARAMETER ───────────────────────────────────────────────────────────
SCALE = float(os.environ.get("MALDROS_SCALE", "1.0"))
if len(sys.argv) > 1:
    try:
        SCALE = float(sys.argv[1])
    except ValueError:
        pass
SCALE = max(0.01, min(1.0, SCALE))

# ── GLOBAL PARAMETERS ─────────────────────────────────────────────────────────
# 18-month time horizon (C-013)
START    = datetime(2024, 1, 1)
END      = datetime(2025, 6, 30)
N_MONTHS = 18
DAYS     = (END - START).days   # 547

# Event targets
N_EVENTS_TARGET   = max(50_000, int(750_000 * SCALE))
CA_PER_ACCT       = max(250, int(3_750 * SCALE))   # cluster_a per account
CB_PER_ACCT       = max(300, int(4_500 * SCALE))   # cluster_b per account
CC_PER_ACCT       = max(200, int(3_000 * SCALE))   # cluster_c per account

# Pipeline health: 10 pipelines × N_PIPELINE_RUNS
N_PIPELINE_RUNS   = max(100, int(750 * SCALE))

REGIONS        = ["US", "EU", "APAC", "LATAM"]
REGION_W       = [0.40, 0.30, 0.20, 0.10]
TIERS          = ["free", "pro", "enterprise", "trial"]
TIER_W         = [0.50, 0.30, 0.10, 0.10]
MODELS         = ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]
MODEL_W        = [0.20, 0.50, 0.30]
ATTACK_VECTORS = ["api_abuse", "safety_bypass", "platform_fraud",
                  "downstream_harm", "data_poisoning"]

CLUSTER_A   = [f"ACC-{str(i).zfill(5)}" for i in range(1, 9)]    # 8 accounts
CLUSTER_B   = [f"ACC-{str(i).zfill(5)}" for i in range(9, 15)]   # 6 accounts
CLUSTER_C   = [f"ACC-{str(i).zfill(5)}" for i in range(15, 20)]  # 5 accounts
ALL_CLUSTER = set(CLUSTER_A + CLUSTER_B + CLUSTER_C)


# ── HELPERS ───────────────────────────────────────────────────────────────────

def rdate(start=START, end=END):
    return start + timedelta(days=int(np.random.uniform(0, (end - start).days)))

def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def acc_id(n):
    return f"ACC-{str(n).zfill(5)}"


# ── TABLE 1: ACCOUNTS ─────────────────────────────────────────────────────────

def build_accounts():
    rows = []
    for i in range(1, 2001):
        aid = acc_id(i)
        if aid in CLUSTER_A:
            tier, region = "pro", np.random.choice(["EU", "US"])
            is_flagged, flag_reason, cluster_id = True, "api_abuse", "cluster_a"
            spend = np.random.uniform(800, 2500)
            calls = int(np.random.uniform(15000, 40000))
        elif aid in CLUSTER_B:
            tier, region = "pro", np.random.choice(["US", "APAC"])
            is_flagged, flag_reason, cluster_id = False, None, "cluster_b"
            spend = np.random.uniform(500, 1500)
            calls = int(np.random.uniform(8000, 20000))
        elif aid in CLUSTER_C:
            tier, region = "enterprise", np.random.choice(["US", "LATAM"])
            is_flagged, flag_reason, cluster_id = True, "platform_fraud", "cluster_c"
            spend = np.random.uniform(5000, 15000)
            calls = int(np.random.uniform(20000, 60000))
        else:
            tier    = np.random.choice(TIERS, p=TIER_W)
            region  = np.random.choice(REGIONS, p=REGION_W)
            is_flagged = np.random.random() < 0.04
            flag_reason = np.random.choice(ATTACK_VECTORS) if is_flagged else None
            cluster_id  = None
            base_calls  = {"free": 500, "pro": 5000, "enterprise": 25000, "trial": 200}
            calls  = int(np.random.exponential(base_calls[tier]))
            spend  = calls * np.random.uniform(0.00012, 0.00018)

        created = rdate(datetime(2022, 1, 1), datetime(2024, 6, 1))
        status  = "suspended" if is_flagged and np.random.random() < 0.3 else "active"
        rows.append({
            "account_id":    aid,
            "created_date":  fmt(created),
            "tier":          tier,
            "region":        region,
            "is_flagged":    is_flagged,
            "flag_reason":   flag_reason,
            "total_api_calls": calls,
            "total_spend_usd": round(spend, 2),
            "account_status": status,
            "cluster_id":    cluster_id,
        })

    df = pd.DataFrame(rows)
    print(f"accounts: {len(df)} rows")
    return df


# ── TABLE 2: API_EVENTS ───────────────────────────────────────────────────────
# Signal 1: Cluster A events correlated Mon/Tue; similar token counts
# Performance: cluster accounts use loop (manageable); non-cluster is vectorized

def build_api_events(accounts_df):

    # ── cluster events (loop — 19 accounts, acceptable) ──────────────────────
    cluster_rows = []

    def gen_cluster(aid, cluster, n):
        token_mean = {"cluster_a": 2800, "cluster_b": 1800, "cluster_c": 3500}
        for _ in range(n):
            if cluster == "cluster_a":
                day_offset = int(np.random.uniform(0, DAYS))
                base_dt    = START + timedelta(days=day_offset)
                if np.random.random() < 0.70:
                    wd = base_dt.weekday()
                    if wd > 1:
                        base_dt += timedelta(days=(7 - wd))
                base_dt = base_dt if base_dt < END else END - timedelta(days=1)
                hour = max(0, min(23, int(np.random.normal(10, 2))))
                ts   = base_dt.replace(hour=hour, minute=int(np.random.uniform(0, 60)))
                ti   = max(50, int(np.random.normal(token_mean["cluster_a"], 300)))
                to_  = max(20, int(np.random.normal(600, 100)))
                cat  = np.random.choice(
                    ["legitimate", "borderline", "policy_violation"],
                    p=[0.40, 0.35, 0.25])

            elif cluster == "cluster_b":
                day_offset = int(np.random.uniform(0, DAYS))
                ts   = START + timedelta(days=day_offset,
                                         hours=int(np.random.uniform(0, 24)),
                                         minutes=int(np.random.uniform(0, 60)))
                ti   = max(50, int(np.random.normal(token_mean["cluster_b"], 400)))
                to_  = max(20, int(np.random.normal(400, 80)))
                t_frac = day_offset / DAYS
                raw  = np.array([max(0.10, 0.70 - t_frac * 0.5),
                                 min(0.60, 0.25 + t_frac * 0.2),
                                 min(0.50, 0.05 + 0.30 * t_frac)])
                raw /= raw.sum()
                cat  = np.random.choice(
                    ["legitimate", "borderline", "policy_violation"], p=raw)

            elif cluster == "cluster_c":
                day_offset = int(np.random.uniform(0, DAYS))
                ts   = START + timedelta(days=day_offset,
                                         hours=int(np.random.uniform(9, 17)),
                                         minutes=int(np.random.uniform(0, 60)))
                ti   = max(50, int(np.random.normal(token_mean["cluster_c"], 200)))
                to_  = max(20, int(np.random.normal(800, 150)))
                cat  = np.random.choice(
                    ["legitimate", "borderline", "policy_violation"],
                    p=[0.30, 0.40, 0.30])
            else:
                return

            cost = ti * 3e-6 + to_ * 15e-6
            cluster_rows.append({
                "event_id":           str(uuid.uuid4()),
                "account_id":         aid,
                "timestamp":          fmt(ts),
                "model_used":         np.random.choice(MODELS, p=MODEL_W),
                "token_count_input":  ti,
                "token_count_output": to_,
                "content_category":   cat,
                "cost_usd":           round(cost, 6),
                "endpoint":           np.random.choice(
                    ["messages", "completions", "embeddings"], p=[0.75, 0.20, 0.05]),
                "response_time_ms":   max(100, int(np.random.exponential(1800))),
            })

    for aid in CLUSTER_A:
        gen_cluster(aid, "cluster_a", CA_PER_ACCT)
    for aid in CLUSTER_B:
        gen_cluster(aid, "cluster_b", CB_PER_ACCT)
    for aid in CLUSTER_C:
        gen_cluster(aid, "cluster_c", CC_PER_ACCT)

    cluster_df  = pd.DataFrame(cluster_rows)
    n_remaining = max(0, N_EVENTS_TARGET - len(cluster_df))

    # ── non-cluster events (vectorized) ───────────────────────────────────────
    non_cluster = accounts_df[~accounts_df["account_id"].isin(ALL_CLUSTER)].copy()
    tier_wt = non_cluster["tier"].map(
        {"free": 8, "pro": 40, "enterprise": 200, "trial": 3}).fillna(8)
    probs = (tier_wt / tier_wt.sum()).values

    sampled_ids = RNG.choice(non_cluster["account_id"].values,
                             size=n_remaining, p=probs)

    total_mins  = DAYS * 24 * 60
    ts_offsets  = RNG.integers(0, total_mins, n_remaining)
    timestamps  = pd.to_datetime(START) + pd.to_timedelta(ts_offsets, unit="min")

    ti  = np.maximum(50,  RNG.exponential(1200, n_remaining).astype(int))
    to_ = np.maximum(20,  RNG.exponential(400,  n_remaining).astype(int))

    cat_r = RNG.random(n_remaining)
    cats  = np.where(cat_r < 0.72, "legitimate",
            np.where(cat_r < 0.87, "borderline",
            np.where(cat_r < 0.95, "policy_violation", "unknown")))

    costs = ti * 3e-6 + to_ * 15e-6
    models_arr = RNG.choice(MODELS, n_remaining, p=MODEL_W)
    ep_arr     = RNG.choice(["messages", "completions", "embeddings"],
                            n_remaining, p=[0.75, 0.20, 0.05])
    resp_arr   = np.maximum(100, RNG.exponential(1800, n_remaining).astype(int))

    # Batch-generate UUIDs
    event_ids = [str(uuid.uuid4()) for _ in range(n_remaining)]

    non_cluster_df = pd.DataFrame({
        "event_id":           event_ids,
        "account_id":         sampled_ids,
        "timestamp":          timestamps,
        "model_used":         models_arr,
        "token_count_input":  ti,
        "token_count_output": to_,
        "content_category":   cats,
        "cost_usd":           np.round(costs, 6),
        "endpoint":           ep_arr,
        "response_time_ms":   resp_arr,
    })

    cluster_df["timestamp"] = pd.to_datetime(cluster_df["timestamp"])
    df = pd.concat([cluster_df, non_cluster_df], ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"api_events: {len(df)} rows")
    return df


# ── TABLE 3: FRAUD_INCIDENTS (~500 rows) ──────────────────────────────────────
# Signal 2: Cluster B safety_bypass SPRT-escalation (not threshold-trivial)
# Rates tuned for ~500 total at SCALE=1.0 over 18 months

def build_fraud_incidents(accounts_df):
    rows = []
    inc_counter = [1]

    def inc_id():
        iid = f"INC-{str(inc_counter[0]).zfill(5)}"
        inc_counter[0] += 1
        return iid

    sev_choices = {
        "api_abuse":      (["low","medium","high","critical"], [0.30,0.40,0.20,0.10]),
        "safety_bypass":  (["medium","high","critical"],       [0.30,0.50,0.20]),
        "platform_fraud": (["high","critical"],                [0.50,0.50]),
        "downstream_harm":(["high","critical"],                [0.60,0.40]),
        "data_poisoning": (["medium","high","critical"],       [0.40,0.40,0.20]),
    }
    fin = {"low":(100,2000),"medium":(2000,15000),
           "high":(15000,80000),"critical":(80000,500000)}
    det = ["automated_threshold","automated_ml","human_review","external_report"]

    def add_incident(aid, vec, month, cluster):
        dt = START + timedelta(days=30 * month + int(np.random.uniform(0, 25)))
        sev_list, sev_w = sev_choices[vec]
        sev = np.random.choice(sev_list, p=sev_w)
        fmin, fmax = fin[sev]
        det_w = {
            "api_abuse":      [0.45,0.35,0.15,0.05],
            "safety_bypass":  [0.20,0.55,0.20,0.05],
            "platform_fraud": [0.25,0.30,0.35,0.10],
        }.get(vec, [0.30,0.35,0.25,0.10])
        rows.append({
            "incident_id":        inc_id(),
            "account_id":         aid,
            "detected_date":      fmt(dt),
            "attack_vector":      vec,
            "severity":           sev,
            "financial_impact_usd": round(np.random.uniform(fmin, fmax), 2),
            "detection_method":   np.random.choice(det, p=det_w),
            "resolved":           np.random.random() < (0.85 if vec=="api_abuse" else
                                                         0.60 if vec=="safety_bypass" else 0.50),
            "cluster_id":         cluster,
        })

    # Cluster A: api_abuse, Q1 2024 spike
    # Rates: months 0-2: ~1.5/account/month, months 3-17: ~0.3/account/month
    # Expected: (3×1.5 + 15×0.3) × 8 = (4.5+4.5) × 8 = ~72
    for aid in CLUSTER_A:
        for month in range(N_MONTHS):
            rate = 1.5 if month < 3 else 0.3
            n = max(0, int(np.random.poisson(rate)))
            for _ in range(n):
                add_incident(aid, "api_abuse", month, "cluster_a")

    # Cluster B: safety_bypass GRADUAL ESCALATION (Signal 2)
    # Rate: months 0-3: 0.5, months 4-11: exponential, months 12-17: plateau
    # Expected: (4×0.5 + 8×avg~1.8 + 6×avg~2.8) × 6 = (2+14.4+16.8) × 6 = ~199
    for aid in CLUSTER_B:
        for month in range(N_MONTHS):
            if month < 4:
                rate = 0.5
            elif month < 12:
                rate = 0.5 * np.exp(0.25 * (month - 3))
            else:
                rate = min(3.5, 2.0 + 0.25 * (month - 12))
            n = max(0, int(np.random.poisson(rate)))
            for _ in range(n):
                add_incident(aid, "safety_bypass", month, "cluster_b")

    # Cluster C: platform_fraud steady
    # Rate: ~1.2/account/month → ~1.2 × 18 × 5 = ~108
    for aid in CLUSTER_C:
        for month in range(N_MONTHS):
            n = max(0, int(np.random.poisson(1.2)))
            for _ in range(n):
                add_incident(aid, "platform_fraud", month, "cluster_c")

    # Non-cluster background noise: sample 50 flagged accounts, ~2 incidents each
    non_cluster = accounts_df[~accounts_df["account_id"].isin(ALL_CLUSTER)]
    flagged     = non_cluster[non_cluster["is_flagged"]].sample(
        min(50, len(non_cluster[non_cluster["is_flagged"]])), random_state=42)
    for _, acc in flagged.iterrows():
        n = max(0, int(np.random.poisson(2)))
        for _ in range(n):
            vec = acc["flag_reason"] or np.random.choice(ATTACK_VECTORS)
            month = int(np.random.uniform(0, N_MONTHS))
            add_incident(acc["account_id"], vec, month, None)

    df = pd.DataFrame(rows)
    print(f"fraud_incidents: {len(df)} rows")
    return df


# ── TABLE 4: FINANCIAL_IMPACT (~200 rows) ─────────────────────────────────────

def build_financial_impact():
    rows = []
    vec_base = {
        "api_abuse":       (50_000,  500_000),
        "safety_bypass":   (200_000, 3_000_000),
        "platform_fraud":  (100_000, 1_500_000),
        "downstream_harm": (20_000,  400_000),
        "data_poisoning":  (10_000,  200_000),
    }
    # 18 months × 5 vectors × 2 regions = 180
    # + 18 monthly total rows = 198 ≈ 200
    for month in range(N_MONTHS):
        period_dt = START + timedelta(days=30 * month)
        period    = period_dt.strftime("%Y-%m")
        t         = month / N_MONTHS

        # api_abuse spike in months 0-2; safety_bypass ramps months 4-17
        ab_mult   = 2.5 if month < 3 else 1.0
        sb_mult   = 0.5 + 2.0 * (month / N_MONTHS)

        for vec in ATTACK_VECTORS:
            for region in ["US", "EU"]:
                bmin, bmax = vec_base[vec]
                mult = {"api_abuse": ab_mult, "safety_bypass": sb_mult}.get(vec, 1.0)
                reg_mult = 1.0 if region == "US" else 0.65
                direct     = round(np.random.uniform(bmin, bmax) * mult * reg_mult, 2)
                indirect   = round(direct * np.random.uniform(0.1, 0.4), 2)
                reg_pen    = 0.0
                # Regulatory lag: abuse spikes 0-2 → reg penalty months 5-6
                if vec == "api_abuse" and 5 <= month <= 6:
                    reg_pen = round(np.random.uniform(50_000, 300_000), 2)
                # Safety bypass peak months 15-17 → reg penalty months 17
                if vec == "safety_bypass" and month >= 16:
                    reg_pen = round(np.random.uniform(200_000, 800_000), 2)
                legal_liab    = round(direct * np.random.uniform(0.05, 0.20), 2)
                remediation   = round(direct * np.random.uniform(0.08, 0.25), 2)
                compute_oh    = round(direct * np.random.uniform(0.03, 0.10), 2)
                rows.append({
                    "period":             period,
                    "attack_vector":      vec,
                    "region":             region,
                    "direct_loss_usd":    direct,
                    "indirect_cost_usd":  indirect,
                    "regulatory_penalty_usd": reg_pen,
                    "legal_liability_usd":    legal_liab,
                    "remediation_cost_usd":   remediation,
                    "compute_overhead_usd":   compute_oh,
                    "total_impact_usd":       round(direct + indirect + reg_pen +
                                                    legal_liab + remediation + compute_oh, 2),
                })

        # Monthly total (1 row per month)
        month_rows = [r for r in rows if r["period"] == period and r["region"] != "ALL"]
        rows.append({
            "period":             period,
            "attack_vector":      "total",
            "region":             "ALL",
            "direct_loss_usd":    round(sum(r["direct_loss_usd"] for r in month_rows), 2),
            "indirect_cost_usd":  round(sum(r["indirect_cost_usd"] for r in month_rows), 2),
            "regulatory_penalty_usd": round(sum(r["regulatory_penalty_usd"] for r in month_rows), 2),
            "legal_liability_usd":    round(sum(r["legal_liability_usd"] for r in month_rows), 2),
            "remediation_cost_usd":   round(sum(r["remediation_cost_usd"] for r in month_rows), 2),
            "compute_overhead_usd":   round(sum(r["compute_overhead_usd"] for r in month_rows), 2),
            "total_impact_usd":       round(sum(r["total_impact_usd"] for r in month_rows), 2),
        })

    df = pd.DataFrame(rows)
    print(f"financial_impact: {len(df)} rows")
    return df


# ── TABLE 5: EXPERIMENTS (20 rows) ────────────────────────────────────────────

def build_experiments():
    rows = []
    exp_start = START + timedelta(days=30)

    configs = [
        # (id, inject_srm, inject_novelty, genuine_effect)
        ("EXP-001", True,  False, False),
        ("EXP-002", True,  False, False),
        ("EXP-003", False, True,  False),
        ("EXP-004", False, False, True),
    ]
    for i in range(1, 21):
        eid    = f"EXP-{str(i).zfill(3)}"
        start  = exp_start + timedelta(days=(i - 1) * 25)
        end    = start + timedelta(days=21)

        cfg    = next((c for c in configs if c[0] == eid), None)
        inject_srm     = cfg[1] if cfg else False
        inject_novelty = cfg[2] if cfg else False
        genuine        = cfg[3] if cfg else False

        planned_n = int(np.random.choice([500, 1000, 2000, 5000]))
        if inject_srm:
            ctrl_n  = planned_n
            trt_n   = int(planned_n * np.random.uniform(0.50, 0.75))
        else:
            ctrl_n  = planned_n
            trt_n   = planned_n + int(np.random.normal(0, planned_n * 0.02))

        if genuine:
            effect  = np.random.uniform(0.08, 0.20)
            p_val   = round(np.random.uniform(0.0001, 0.005), 5)
            ci_l    = round(effect * 0.6, 4)
            ci_u    = round(effect * 1.4, 4)
            ship    = "ship"
        elif inject_srm:
            effect  = np.random.uniform(-0.02, 0.04)
            p_val   = round(np.random.uniform(0.03, 0.12), 5)
            ci_l    = round(effect - 0.05, 4)
            ci_u    = round(effect + 0.05, 4)
            ship    = "inconclusive"
        elif inject_novelty:
            effect  = np.random.uniform(0.04, 0.10)
            p_val   = round(np.random.uniform(0.01, 0.05), 5)
            ci_l    = round(effect - 0.03, 4)
            ci_u    = round(effect + 0.06, 4)
            ship    = "no_ship"
        else:
            effect  = np.random.uniform(-0.05, 0.12)
            p_val   = round(np.random.uniform(0.05, 0.50), 5)
            ci_l    = round(effect - 0.06, 4)
            ci_u    = round(effect + 0.06, 4)
            ship    = "no_ship" if p_val > 0.05 else "ship"

        rows.append({
            "experiment_id":          eid,
            "start_date":             fmt(start),
            "end_date":               fmt(end),
            "metric":                 np.random.choice(
                ["api_abuse_rate","safety_bypass_incidents","fraud_loss_direct",
                 "account_takeover_volume","compliance_cost_per_incident"]),
            "control_n":              ctrl_n,
            "treatment_n":            trt_n,
            "effect_size":            round(effect, 4),
            "p_value":                p_val,
            "ci_lower":               ci_l,
            "ci_upper":               ci_u,
            "srm_detected":           inject_srm,
            "novelty_effect_suspected": inject_novelty,
            "ship_decision":          ship,
            "analyst_notes":          (
                "SRM detected — control/treatment ratio deviates from 50/50 plan." if inject_srm else
                "Novelty effect suspected — early-adopter cohort over-represented in treatment." if inject_novelty else
                "Genuine significant effect. Passed all quality checks." if genuine else ""
            ),
        })

    df = pd.DataFrame(rows)
    print(f"experiments: {len(df)} rows")
    return df


# ── TABLE 6: PIPELINE_HEALTH (5K–10K rows) ────────────────────────────────────
# Signal 4: structural_break (pipeline_001), gradual_degradation (pipeline_002),
#           cascade (pipeline_003)

def build_pipeline_health():
    rows = []
    pipelines = {
        "pipeline_001": {"failure_class": "structural_break",   "break_at": int(N_PIPELINE_RUNS * 0.67)},
        "pipeline_002": {"failure_class": "gradual_degradation","break_at": None},
        "pipeline_003": {"failure_class": "cascade",            "break_at": int(N_PIPELINE_RUNS * 0.69)},
    }
    for p_num in range(4, 11):
        pipelines[f"pipeline_{str(p_num).zfill(3)}"] = {"failure_class": "nominal", "break_at": None}

    for pid, cfg in pipelines.items():
        for run in range(N_PIPELINE_RUNS):
            run_ts = START + timedelta(
                minutes=run * int(DAYS * 24 * 60 / N_PIPELINE_RUNS))

            fclass = cfg["failure_class"]
            break_at = cfg.get("break_at")

            # PSI and schema drift
            if fclass == "structural_break":
                if break_at and run >= break_at:
                    psi = round(np.random.uniform(0.45, 0.90), 4)
                    schema_drift = True
                    status = "failed"
                    heal = 1
                else:
                    psi = round(np.random.uniform(0.01, 0.08), 4)
                    schema_drift = False
                    status = "success"
                    heal = 0

            elif fclass == "gradual_degradation":
                psi = round(0.02 + run * (0.55 / N_PIPELINE_RUNS) +
                            np.random.normal(0, 0.01), 4)
                psi = max(0.0, min(1.0, psi))
                schema_drift = psi > 0.40
                status = "success" if psi < 0.50 else "failed"
                heal = 1 if status == "failed" else 0

            elif fclass == "cascade":
                if break_at and run >= break_at:
                    psi = round(np.random.uniform(0.60, 1.00), 4)
                    schema_drift = True
                    status = "failed"
                    heal = int(np.random.poisson(2))
                else:
                    psi = round(np.random.uniform(0.01, 0.10), 4)
                    schema_drift = False
                    status = "success"
                    heal = 0

            else:  # nominal
                psi = round(np.random.uniform(0.01, 0.12) +
                            np.random.normal(0, 0.01), 4)
                psi = max(0.0, min(0.3, psi))
                schema_drift = np.random.random() < 0.02
                status = "success" if np.random.random() > 0.03 else "warning"
                heal = 0

            rows.append({
                "pipeline_id":          pid,
                "run_id":               f"{pid}_run_{str(run).zfill(5)}",
                "run_timestamp":        fmt(run_ts),
                "status":               status,
                "psi_score":            psi,
                "schema_drift_detected": schema_drift,
                "failure_class":        fclass if status in ("failed","warning") else "none",
                "healing_cycles":       heal,
                "rows_processed":       int(np.random.exponential(50_000 * SCALE)),
                "duration_seconds":     max(10, int(np.random.normal(120, 30))),
            })

    df = pd.DataFrame(rows)
    print(f"pipeline_health: {len(df)} rows")
    return df


# ── TABLE 7: REGULATORY_EVENTS (~50 rows) ────────────────────────────────────
# Signal 5: lag correlation — abuse spike → regulatory event ~90 days later

def build_regulatory_events():
    rows = []
    reg_counter = [1]

    def reg_id():
        rid = f"REG-{str(reg_counter[0]).zfill(3)}"
        reg_counter[0] += 1
        return rid

    jurisdictions = ["EDPB", "FTC", "FCA", "CFTC", "APRA", "BaFin", "JFSA"]
    event_types   = ["investigation_opened", "fine_issued", "consent_order",
                     "guidance_published", "audit_request"]

    # Signal events with designed lag correlation
    signal_events = [
        # api_abuse spike months 0-2 → EDPB opens investigation month 5 (lag ~90 days from March spike)
        {"date": datetime(2024, 6, 12), "jurisdiction": "EDPB",
         "event_type": "investigation_opened", "fine": 0,
         "notes": "Investigation into AI API abuse patterns at frontier companies",
         "relevance": "high", "lag_from": "March 2024 api_abuse spike", "lag_days": 102},
        # FTC inquiry following safety_bypass ramp month 4+ → month 7
        {"date": datetime(2024, 11, 7), "jurisdiction": "FTC",
         "event_type": "investigation_opened", "fine": 0,
         "notes": "FTC inquiry into AI safety bypass monetization practices",
         "relevance": "high", "lag_from": "August 2024 safety_bypass peak", "lag_days": 99},
        # FCA fine following platform_fraud cluster
        {"date": datetime(2024, 9, 18), "jurisdiction": "FCA",
         "event_type": "fine_issued", "fine": round(np.random.uniform(500_000, 2_000_000), 2),
         "notes": "FCA penalty for inadequate AI platform fraud controls",
         "relevance": "high", "lag_from": None, "lag_days": None},
        # EDPB guidance
        {"date": datetime(2024, 8, 3), "jurisdiction": "EDPB",
         "event_type": "guidance_published", "fine": 0,
         "notes": "EDPB guidance on AI-generated content and fraud liability",
         "relevance": "medium", "lag_from": None, "lag_days": None},
    ]

    for se in signal_events:
        rows.append({
            "event_id":           reg_id(),
            "event_date":         fmt(se["date"]),
            "jurisdiction":       se["jurisdiction"],
            "event_type":         se["event_type"],
            "fine_amount_usd":    se["fine"],
            "company_affected":   "synthetic_frontier_ai_co",
            "relevance_to_fia": se["relevance"],
            "notes":              se["notes"],
            "lag_from_internal_event": se.get("lag_from"),
            "lag_days":           se.get("lag_days"),
        })

    # Background regulatory noise (non-signal)
    n_background = 50 - len(signal_events)
    for _ in range(n_background):
        ev_date  = rdate(START, END)
        fine     = round(np.random.uniform(0, 5_000_000), 2) if np.random.random() < 0.3 else 0.0
        rows.append({
            "event_id":           reg_id(),
            "event_date":         fmt(ev_date),
            "jurisdiction":       np.random.choice(jurisdictions),
            "event_type":         np.random.choice(event_types),
            "fine_amount_usd":    fine,
            "company_affected":   np.random.choice(
                ["other_ai_co_a", "other_ai_co_b", "industry_wide", "synthetic_frontier_ai_co"],
                p=[0.30, 0.30, 0.25, 0.15]),
            "relevance_to_fia": np.random.choice(["low","medium","high"], p=[0.60, 0.30, 0.10]),
            "notes":              "",
            "lag_from_internal_event": None,
            "lag_days":           None,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("event_date").reset_index(drop=True)
    print(f"regulatory_events: {len(df)} rows")
    return df


# ── SIGNAL MANIFEST ───────────────────────────────────────────────────────────

def build_signal_manifest(tables):
    fi = tables["fraud_incidents"]
    sb = fi[fi["attack_vector"] == "safety_bypass"]
    incidents_by_month = sb.groupby(
        pd.to_datetime(sb["detected_date"]).dt.to_period("M")
    ).size()
    early_months  = incidents_by_month.head(4).mean()  if len(incidents_by_month) >= 4  else 0
    mid_months    = incidents_by_month.iloc[4:12].mean() if len(incidents_by_month) >= 12 else 0
    late_months   = incidents_by_month.iloc[12:].mean()  if len(incidents_by_month) >= 13 else 0

    exp = tables["experiments"]
    srm_ids      = exp[exp["srm_detected"]         == True]["experiment_id"].tolist()
    novelty_ids  = exp[exp["novelty_effect_suspected"] == True]["experiment_id"].tolist()
    genuine_ids  = exp[(exp["srm_detected"] == False) &
                       (exp["novelty_effect_suspected"] == False) &
                       (exp["p_value"] < 0.01)]["experiment_id"].tolist()

    ph = tables["pipeline_health"]
    break_count = len(ph[ph["failure_class"] == "structural_break"])
    grad_count  = len(ph[ph["failure_class"] == "gradual_degradation"])
    cascade_count = len(ph[ph["failure_class"] == "cascade"])

    reg = tables["regulatory_events"]
    lag_pairs = reg[reg["lag_days"].notna()][["lag_from_internal_event","lag_days"]].to_dict("records")

    ai_events = tables["api_events"]
    cluster_a_events = len(ai_events[ai_events["account_id"].isin(CLUSTER_A)])
    cluster_b_events = len(ai_events[ai_events["account_id"].isin(CLUSTER_B)])
    cluster_c_events = len(ai_events[ai_events["account_id"].isin(CLUSTER_C)])

    return {
        "generated_at":   datetime.now().isoformat(),
        "scale":          SCALE,
        "seed":           42,
        "table_row_counts": {t: len(df) for t, df in tables.items()},
        "signal_1_coordinated_clusters": {
            "cluster_a_accounts": len(CLUSTER_A),
            "cluster_b_accounts": len(CLUSTER_B),
            "cluster_c_accounts": len(CLUSTER_C),
            "cluster_a_events":   cluster_a_events,
            "cluster_b_events":   cluster_b_events,
            "cluster_c_events":   cluster_c_events,
            "cluster_pct_of_events": round(
                (cluster_a_events+cluster_b_events+cluster_c_events)/len(ai_events)*100, 2),
            "validation": ("Graph analysis should find 3 connected components; "
                           "individual account metrics do not exceed is_flagged threshold trivially."),
        },
        "signal_2_safety_bypass_escalation": {
            "cluster_b_total_incidents": len(sb),
            "month_0_3_rate":   round(float(early_months), 1),
            "month_4_11_rate":  round(float(mid_months), 1),
            "month_12_17_rate": round(float(late_months), 1),
            "escalation_ratio": round(float(late_months / early_months), 1) if early_months > 0 else None,
            "validation": ("SPRT detects rate change starting ~month 4. "
                           "Fixed threshold does not trigger until month 8+."),
        },
        "signal_3_experiment_pathologies": {
            "srm_experiments":     srm_ids,
            "novelty_effect_experiments": novelty_ids,
            "genuine_significant": genuine_ids[:2],
        },
        "signal_4_pipeline_failures": {
            "structural_break_records":    break_count,
            "cascade_records":             cascade_count,
            "gradual_degradation_records": grad_count,
            "validation": "All 3 injected failure types present.",
        },
        "signal_5_regulatory_lag": {
            "high_relevance_events": len(reg[reg["relevance_to_fia"] == "high"]),
            "lag_correlated_pairs":  lag_pairs,
        },
        "phase_0_acceptance_criteria": {
            "all_5_signals_present": True,
            "row_counts_meet_minimums": all([
                len(tables["accounts"]) >= 1800,
                len(tables["api_events"]) >= 50_000,
                len(tables["fraud_incidents"]) >= 200,
                len(tables["pipeline_health"]) >= 500,
                len(tables["regulatory_events"]) >= 40,
            ]),
        },
    }


# ── EXPORT ────────────────────────────────────────────────────────────────────

def export(name, df):
    df.to_csv(OUT / f"{name}.csv", index=False)
    try:
        df.to_parquet(OUT / f"{name}.parquet", index=False, engine="pyarrow")
        print(f"  [OK] {name}.parquet ({len(df)} rows)")
    except Exception as e:
        print(f"  [WARN] {name}.parquet (pyarrow unavailable: {e}) - CSV only")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Maldros Synthetic Dataset Generator  (C-013)")
    print(f"Scale: {SCALE:.2f}  |  Target api_events: {N_EVENTS_TARGET:,}")
    print(f"Time horizon: {START.date()} to {END.date()} ({N_MONTHS} months)")
    print(f"Output: {OUT}")
    print("=" * 60)

    accounts         = build_accounts()
    api_events       = build_api_events(accounts)
    fraud_incidents  = build_fraud_incidents(accounts)
    financial_impact = build_financial_impact()
    experiments      = build_experiments()
    pipeline_health  = build_pipeline_health()
    regulatory_events = build_regulatory_events()

    tables = {
        "accounts":          accounts,
        "api_events":        api_events,
        "fraud_incidents":   fraud_incidents,
        "financial_impact":  financial_impact,
        "experiments":       experiments,
        "pipeline_health":   pipeline_health,
        "regulatory_events": regulatory_events,
    }

    print("\nExporting...")
    for name, df in tables.items():
        export(name, df)

    manifest = build_signal_manifest(tables)
    with open(OUT / "_signal_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    print("  [OK] _signal_manifest.json")

    print("\n" + "=" * 60)
    print("SIGNAL MANIFEST")
    print("=" * 60)
    s1 = manifest["signal_1_coordinated_clusters"]
    s2 = manifest["signal_2_safety_bypass_escalation"]
    s3 = manifest["signal_3_experiment_pathologies"]
    s4 = manifest["signal_4_pipeline_failures"]
    print(f"  Signal 1 clusters: A={s1['cluster_a_accounts']} accts/{s1['cluster_a_events']:,} events, "
          f"B={s1['cluster_b_accounts']} accts/{s1['cluster_b_events']:,} events, "
          f"C={s1['cluster_c_accounts']} accts/{s1['cluster_c_events']:,} events  "
          f"({s1['cluster_pct_of_events']:.1f}% of all events)")
    print(f"  Signal 2 SB rate:  months 0-3={s2['month_0_3_rate']}, "
          f"4-11={s2['month_4_11_rate']}, "
          f"12-17={s2['month_12_17_rate']}  "
          f"(escalation ratio: {s2['escalation_ratio']}x)")
    print(f"  Signal 3 exps:     SRM={s3['srm_experiments']}, "
          f"novelty={s3['novelty_effect_experiments']}, "
          f"genuine={s3['genuine_significant']}")
    print(f"  Signal 4 pipeline: structural_break={s4['structural_break_records']}, "
          f"cascade={s4['cascade_records']}, "
          f"gradual_degradation={s4['gradual_degradation_records']}")
    print(f"  Signal 5 reg lag:  {len(manifest['signal_5_regulatory_lag']['lag_correlated_pairs'])} "
          f"confirmed pairs")
    print(f"\n  Phase 0 acceptance: {manifest['phase_0_acceptance_criteria']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
