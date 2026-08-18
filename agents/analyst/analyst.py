"""
Analyst Agent — Phase 1 full implementation.
agents/analyst/analyst.py

Mandate: End-to-end investigation. Forms hypotheses, executes data queries,
runs Python analysis, interprets results, drafts recommendations.

Phase 1 investigation: "Is the spike in API abuse volume in Q1 driven by
coordinated multi-account behavior, or is it organic growth? If coordinated,
what is the estimated financial impact and what countermeasure is indicated?"

CDI Layer query is mandatory before any analytical decision is committed.
An agent that produces output without a recorded CDI Layer query in its
lineage trace is a Diagnostic Agent L1 failure.

Constraints:
- No causal claims without causal evidence (L1 veto enforced by Storyteller)
- Generation mode must be declared
- Known Limitations section is concrete, not perfunctory
"""
import sys
import json
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.artifact import create_artifact, write_artifact, read_artifact, validate_envelope
from lib.second_brain import write_analysis_entry
from lib.llm_wrapper import LLMWrapper
from lib.few_shot_bank import FewShotBank
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater

DATA_DIR = BASE / "data" / "raw"

ANALYST_SYSTEM_PROMPT = """You are the Analyst Agent in the Maldros analytics engineering system.

Your role: interpret quantitative analytical results and produce an evidence-based assessment.
You receive pre-computed statistics, graph metrics, and data summaries. Your job is to
synthesize these into a coherent analytical narrative.

HARD RULES:
1. NO causal claims without causal evidence. Use "associated with", "correlated with",
   "consistent with", not "caused by" or "drove". The Statistician Agent validates inference.
2. Declare your generation mode: ABDUCTIVE (what process explains this pattern?) or
   FIRST_PRINCIPLES or ANALOGICAL.
3. For every finding, state what specific observation would INVALIDATE it.
4. Map your finding to a concrete, implementable countermeasure with an explicit
   implementation path.
5. Your confidence score must reflect the evidence quality, not optimism.

OUTPUT FORMAT (JSON):
{
  "hypothesis_assessment": {
    "coordinated_abuse": {"probability": float, "evidence_points": [str], "against_points": [str]},
    "organic_growth": {"probability": float, "evidence_points": [str], "against_points": [str]}
  },
  "primary_conclusion": "COORDINATED_ABUSE|ORGANIC_GROWTH|AMBIGUOUS",
  "conclusion_rationale": str,
  "financial_impact_assessment": {
    "conservative_usd": float,
    "base_case_usd": float,
    "methodology": str,
    "confidence": "LOW|MEDIUM|HIGH"
  },
  "countermeasure": {
    "primary": str,
    "implementation_path": str,
    "secondary": str,
    "hardening_step": str
  },
  "generation_mode": "ABDUCTIVE|FIRST_PRINCIPLES|ANALOGICAL",
  "reasoning_chain": [str],
  "known_limitations": [str],
  "confidence_score": float
}

Return ONLY valid JSON. No markdown, no preamble."""


def _run_duckdb_analysis(task_id: str) -> dict:
    """
    Execute the core quantitative analysis using DuckDB + pandas + networkx.
    Returns a dict of numerical findings for the LLM to interpret.
    """
    import duckdb
    import pandas as pd
    import numpy as np

    t0 = time.time()

    api_path = str(DATA_DIR / "api_events.parquet")
    accounts_path = str(DATA_DIR / "accounts.parquet")
    incidents_path = str(DATA_DIR / "fraud_incidents.parquet")
    financial_path = str(DATA_DIR / "financial_impact.parquet")

    con = duckdb.connect()

    # ── 1. Monthly abuse volume ───────────────────────────────────────────────
    monthly_volume = con.execute(f"""
        SELECT
            strftime(timestamp, '%Y-%m') AS month,
            COUNT(*) AS total_events,
            SUM(CASE WHEN content_category = 'policy_violation' THEN 1 ELSE 0 END) AS abuse_events,
            SUM(CASE WHEN content_category = 'borderline' THEN 1 ELSE 0 END) AS borderline_events,
            COUNT(DISTINCT account_id) AS active_accounts
        FROM read_parquet('{api_path}')
        GROUP BY 1
        ORDER BY 1
    """).df()

    # Mark Q1 2024 (Jan–Mar)
    monthly_volume["is_q1_2024"] = monthly_volume["month"].isin(["2024-01","2024-02","2024-03"])
    monthly_volume["abuse_rate"] = monthly_volume["abuse_events"] / monthly_volume["total_events"]

    q1_abuse = monthly_volume[monthly_volume["is_q1_2024"]]["abuse_events"].sum()
    q2_abuse = monthly_volume[monthly_volume["month"].isin(["2024-04","2024-05","2024-06"])]["abuse_events"].sum()
    q3_abuse = monthly_volume[monthly_volume["month"].isin(["2024-07","2024-08","2024-09"])]["abuse_events"].sum()
    q4_abuse = monthly_volume[monthly_volume["month"].isin(["2024-10","2024-11","2024-12"])]["abuse_events"].sum()
    q1_total = monthly_volume[monthly_volume["is_q1_2024"]]["total_events"].sum()
    q1_rate   = float(q1_abuse / q1_total) if q1_total > 0 else 0.0

    # Average non-Q1 monthly abuse events
    non_q1 = monthly_volume[~monthly_volume["is_q1_2024"]]
    avg_non_q1_monthly = float(non_q1["abuse_events"].mean())
    q1_monthly_avg = float(monthly_volume[monthly_volume["is_q1_2024"]]["abuse_events"].mean())
    q1_spike_ratio = round(q1_monthly_avg / avg_non_q1_monthly, 3) if avg_non_q1_monthly > 0 else 1.0

    # ── 2. Per-account event rates ────────────────────────────────────────────
    account_rates = con.execute(f"""
        SELECT
            account_id,
            COUNT(*) AS total_events,
            SUM(CASE WHEN content_category = 'policy_violation' THEN 1 ELSE 0 END) AS abuse_events,
            ROUND(
                SUM(CASE WHEN content_category = 'policy_violation' THEN 1.0 ELSE 0 END) / COUNT(*),
                4
            ) AS abuse_rate
        FROM read_parquet('{api_path}')
        GROUP BY account_id
        ORDER BY abuse_events DESC
    """).df()

    # High-abuse accounts: top 5% by abuse_events
    p95_threshold = float(account_rates["abuse_events"].quantile(0.95))
    high_abuse_accounts = account_rates[account_rates["abuse_events"] >= p95_threshold]["account_id"].tolist()
    n_high_abuse = len(high_abuse_accounts)
    total_accounts = len(account_rates)

    # Per-account abuse events: summary stats
    median_abuse_per_account = float(account_rates["abuse_events"].median())
    mean_abuse_per_account = float(account_rates["abuse_events"].mean())
    p99_abuse = float(account_rates["abuse_events"].quantile(0.99))
    max_abuse = float(account_rates["abuse_events"].max())

    # ── 3. Q1 abuse concentration by account ─────────────────────────────────
    q1_by_account = con.execute(f"""
        SELECT
            account_id,
            COUNT(*) AS q1_abuse_events
        FROM read_parquet('{api_path}')
        WHERE content_category = 'policy_violation'
          AND timestamp >= '2024-01-01'
          AND timestamp < '2024-04-01'
        GROUP BY account_id
        ORDER BY q1_abuse_events DESC
    """).df()

    # What share of Q1 abuse comes from top-N accounts?
    q1_total_abuse = int(q1_by_account["q1_abuse_events"].sum())
    q1_top20_abuse = int(q1_by_account.head(20)["q1_abuse_events"].sum())
    q1_top50_abuse = int(q1_by_account.head(50)["q1_abuse_events"].sum())
    q1_concentration_top20 = round(q1_top20_abuse / q1_total_abuse, 4) if q1_total_abuse > 0 else 0.0
    q1_concentration_top50 = round(q1_top50_abuse / q1_total_abuse, 4) if q1_total_abuse > 0 else 0.0

    # ── 4. Fraud incidents — Q1 by attack vector ──────────────────────────────
    # detected_date is VARCHAR in "YYYY-MM-DD HH:MM:SS" format — string comparison works
    q1_incidents = con.execute(f"""
        SELECT
            attack_vector,
            cluster_id,
            COUNT(*) AS incident_count,
            SUM(financial_impact_usd) AS total_financial_impact,
            AVG(financial_impact_usd) AS avg_financial_impact
        FROM read_parquet('{incidents_path}')
        WHERE detected_date >= '2024-01-01'
          AND detected_date < '2024-04-01'
        GROUP BY attack_vector, cluster_id
        ORDER BY incident_count DESC
    """).df()

    q1_total_incidents = int(q1_incidents["incident_count"].sum())
    q1_api_abuse_incidents = int(
        q1_incidents[q1_incidents["attack_vector"] == "api_abuse"]["incident_count"].sum()
        if "api_abuse" in q1_incidents["attack_vector"].values else 0
    )
    q1_total_financial_impact = float(q1_incidents["total_financial_impact"].sum())
    # Cluster incidents in Q1 (all attack vectors)
    q1_cluster_incidents = int(
        q1_incidents[q1_incidents["cluster_id"].notna()]["incident_count"].sum()
    )

    # All-period incident rates for comparison
    all_incidents = con.execute(f"""
        SELECT
            substr(detected_date, 1, 7) AS month,
            COUNT(*) AS incident_count,
            SUM(financial_impact_usd) AS monthly_impact
        FROM read_parquet('{incidents_path}')
        GROUP BY 1
        ORDER BY 1
    """).df()

    avg_monthly_incidents = float(all_incidents["incident_count"].mean())
    q1_months_incidents = all_incidents[all_incidents["month"].isin(["2024-01","2024-02","2024-03"])]
    q1_avg_monthly_incidents = float(q1_months_incidents["incident_count"].mean()) if len(q1_months_incidents) > 0 else 0.0
    incident_q1_ratio = round(q1_avg_monthly_incidents / avg_monthly_incidents, 3) if avg_monthly_incidents > 0 else 1.0

    # ── 5. Account behavioral fingerprint clustering via graph ────────────────
    # Build co-occurrence graph: accounts with high abuse events in same week
    weekly_abusers = con.execute(f"""
        SELECT
            account_id,
            CAST(strftime(timestamp, '%Y-%W') AS VARCHAR) AS year_week,
            COUNT(*) AS weekly_abuse_events
        FROM read_parquet('{api_path}')
        WHERE content_category = 'policy_violation'
          AND timestamp >= '2024-01-01'
          AND timestamp < '2024-04-01'
        GROUP BY account_id, year_week
        HAVING COUNT(*) >= 5
    """).df()

    # Build edge list: accounts sharing active abuse weeks
    import networkx as nx

    G = nx.Graph()
    week_to_accounts: dict = {}
    for _, row in weekly_abusers.iterrows():
        wk = row["year_week"]
        acct = row["account_id"]
        if wk not in week_to_accounts:
            week_to_accounts[wk] = []
        week_to_accounts[wk].append(acct)

    edge_weights: dict = {}
    for wk, accounts in week_to_accounts.items():
        for i in range(len(accounts)):
            for j in range(i + 1, len(accounts)):
                a, b = sorted([accounts[i], accounts[j]])
                key = (a, b)
                edge_weights[key] = edge_weights.get(key, 0) + 1

    # Only include edges with co-occurrence >= 2 weeks (reduces noise)
    for (a, b), weight in edge_weights.items():
        if weight >= 2:
            G.add_edge(a, b, weight=weight)

    n_graph_nodes = G.number_of_nodes()
    n_graph_edges = G.number_of_edges()

    # Connected components = potential coordinated clusters
    components = sorted(nx.connected_components(G), key=len, reverse=True)
    n_components = len(components)
    largest_component_size = len(components[0]) if components else 0
    second_component_size = len(components[1]) if len(components) > 1 else 0
    component_sizes = [len(c) for c in components[:10]]

    # Accounts in the largest clusters
    top_cluster_accounts = list(components[0]) if components else []
    second_cluster_accounts = list(components[1]) if len(components) > 1 else []
    all_cluster_accounts = set()
    for c in components:
        if len(c) >= 3:  # Only clusters of 3+ accounts
            all_cluster_accounts.update(c)

    n_clustered_accounts = len(all_cluster_accounts)

    # Graph density and degree stats
    if n_graph_nodes > 1:
        degrees = [d for _, d in G.degree()]
        avg_degree = round(float(np.mean(degrees)), 2)
        max_degree = max(degrees)
        density = round(nx.density(G), 4)
    else:
        avg_degree = 0.0
        max_degree = 0
        density = 0.0

    # ── 6. Cluster account Q1 abuse contribution ──────────────────────────────
    if all_cluster_accounts:
        cluster_ids_sql = "','".join(list(all_cluster_accounts)[:200])  # cap at 200 for SQL
        cluster_q1_abuse = con.execute(f"""
            SELECT COUNT(*) AS abuse_count
            FROM read_parquet('{api_path}')
            WHERE content_category = 'policy_violation'
              AND timestamp >= '2024-01-01'
              AND timestamp < '2024-04-01'
              AND account_id IN ('{cluster_ids_sql}')
        """).fetchone()[0]

        cluster_q1_share = round(cluster_q1_abuse / q1_total_abuse, 4) if q1_total_abuse > 0 else 0.0

        # These cluster accounts: what fraction of all accounts are they?
        cluster_account_share = round(n_clustered_accounts / total_accounts, 4)
    else:
        cluster_q1_abuse = 0
        cluster_q1_share = 0.0
        cluster_account_share = 0.0

    # ── 7. Financial impact from financial_impact table ───────────────────────
    # period is VARCHAR "YYYY-MM" format; aggregate across both US and EU regions
    financial_q1 = con.execute(f"""
        SELECT
            SUM(direct_loss_usd) AS direct_loss,
            SUM(indirect_cost_usd) AS indirect_cost,
            SUM(regulatory_penalty_usd) AS regulatory_penalty,
            SUM(legal_liability_usd) AS legal_liability,
            SUM(remediation_cost_usd) AS remediation_cost,
            SUM(compute_overhead_usd) AS compute_overhead
        FROM read_parquet('{financial_path}')
        WHERE period IN ('2024-01', '2024-02', '2024-03')
          AND attack_vector = 'api_abuse'
    """).df()

    fi_direct = float(financial_q1["direct_loss"].iloc[0] or 0)
    fi_indirect = float(financial_q1["indirect_cost"].iloc[0] or 0)
    fi_regulatory = float(financial_q1["regulatory_penalty"].iloc[0] or 0)
    fi_legal = float(financial_q1["legal_liability"].iloc[0] or 0)
    fi_remediation = float(financial_q1["remediation_cost"].iloc[0] or 0)
    fi_compute = float(financial_q1["compute_overhead"].iloc[0] or 0)
    fi_total = fi_direct + fi_indirect + fi_regulatory + fi_legal + fi_remediation + fi_compute

    # Also get fraud_incidents financial impact for Q1 api_abuse
    incident_impact = con.execute(f"""
        SELECT
            COUNT(*) AS n_incidents,
            SUM(financial_impact_usd) AS total_impact,
            AVG(financial_impact_usd) AS avg_impact,
            MIN(financial_impact_usd) AS min_impact,
            MAX(financial_impact_usd) AS max_impact
        FROM read_parquet('{incidents_path}')
        WHERE detected_date >= '2024-01-01'
          AND detected_date < '2024-04-01'
          AND attack_vector = 'api_abuse'
    """).df()

    incident_n = int(incident_impact["n_incidents"].iloc[0] or 0)
    incident_total_impact = float(incident_impact["total_impact"].iloc[0] or 0)
    incident_avg_impact = float(incident_impact["avg_impact"].iloc[0] or 0)

    # ── 8. Account tier distribution — labeled clusters vs non-clusters ────────
    # The accounts table has cluster_id directly — use this for ground-truth comparison
    tier_comparison = con.execute(f"""
        SELECT
            CASE WHEN cluster_id IS NOT NULL THEN 'labeled_cluster' ELSE 'non_cluster' END AS group_type,
            tier,
            COUNT(*) AS n_accounts
        FROM read_parquet('{accounts_path}')
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
    """).df()
    tier_breakdown = tier_comparison.to_dict(orient="records")

    # Get labeled cluster accounts (ground truth from cluster_id column)
    labeled_cluster_accounts_df = con.execute(f"""
        SELECT account_id, cluster_id FROM read_parquet('{accounts_path}')
        WHERE cluster_id IS NOT NULL
    """).df()
    labeled_cluster_account_ids = set(labeled_cluster_accounts_df["account_id"].tolist())
    n_labeled_cluster_accounts = len(labeled_cluster_account_ids)

    # Labeled cluster Q1 abuse share
    if labeled_cluster_account_ids:
        cluster_ids_sql3 = "','".join(list(labeled_cluster_account_ids))
        labeled_cluster_q1_abuse = con.execute(f"""
            SELECT COUNT(*) AS cnt FROM read_parquet('{api_path}')
            WHERE content_category = 'policy_violation'
              AND timestamp >= '2024-01-01' AND timestamp < '2024-04-01'
              AND account_id IN ('{cluster_ids_sql3}')
        """).fetchone()[0]
        labeled_cluster_q1_share = round(labeled_cluster_q1_abuse / q1_total_abuse, 4) if q1_total_abuse > 0 else 0.0
    else:
        labeled_cluster_q1_abuse = 0
        labeled_cluster_q1_share = 0.0

    elapsed = round(time.time() - t0, 2)
    con.close()

    return {
        "elapsed_sec": elapsed,
        "volume_analysis": {
            "q1_2024_abuse_events": int(q1_abuse),
            "q2_2024_abuse_events": int(q2_abuse),
            "q3_2024_abuse_events": int(q3_abuse),
            "q4_2024_abuse_events": int(q4_abuse),
            "q1_total_events": int(q1_total),
            "q1_abuse_rate": round(q1_rate, 5),
            "q1_monthly_avg_abuse": round(q1_monthly_avg, 1),
            "non_q1_monthly_avg_abuse": round(avg_non_q1_monthly, 1),
            "q1_spike_ratio": q1_spike_ratio,
            "monthly_time_series": monthly_volume[["month","abuse_events","total_events","abuse_rate"]].to_dict(orient="records"),
        },
        "account_analysis": {
            "total_accounts": total_accounts,
            "n_high_abuse_accounts": n_high_abuse,
            "p95_abuse_threshold": round(p95_threshold, 1),
            "median_abuse_per_account": round(median_abuse_per_account, 1),
            "mean_abuse_per_account": round(mean_abuse_per_account, 1),
            "p99_abuse_per_account": round(p99_abuse, 1),
            "max_abuse_per_account": round(max_abuse, 1),
            "q1_top20_accounts_abuse_share": q1_concentration_top20,
            "q1_top50_accounts_abuse_share": q1_concentration_top50,
        },
        "graph_analysis": {
            "n_graph_nodes": n_graph_nodes,
            "n_graph_edges": n_graph_edges,
            "graph_density": density,
            "n_connected_components": n_components,
            "component_sizes_top10": component_sizes,
            "largest_component_size": largest_component_size,
            "second_component_size": second_component_size,
            "avg_degree": avg_degree,
            "max_degree": max_degree,
            "n_clustered_accounts_3plus": n_clustered_accounts,
            "cluster_account_share_of_population": cluster_account_share,
            "cluster_q1_abuse_events": int(cluster_q1_abuse) if all_cluster_accounts else 0,
            "cluster_q1_abuse_share": cluster_q1_share,
        },
        "fraud_incident_analysis": {
            "q1_total_incidents": q1_total_incidents,
            "q1_api_abuse_incidents": q1_api_abuse_incidents,
            "q1_cluster_incidents": q1_cluster_incidents,
            "q1_total_financial_impact_from_incidents": round(q1_total_financial_impact, 2),
            "q1_by_attack_vector_and_cluster": q1_incidents.to_dict(orient="records"),
            "avg_monthly_incidents_all_period": round(avg_monthly_incidents, 1),
            "q1_avg_monthly_incidents": round(q1_avg_monthly_incidents, 1),
            "incident_q1_ratio": incident_q1_ratio,
            "incident_n_api_abuse_q1": incident_n,
            "incident_avg_impact_api_abuse_q1": round(incident_avg_impact, 2),
            "incident_total_impact_api_abuse_q1": round(incident_total_impact, 2),
        },
        "financial_impact_table": {
            "q1_api_abuse_direct_loss": round(fi_direct, 2),
            "q1_api_abuse_indirect_cost": round(fi_indirect, 2),
            "q1_api_abuse_regulatory_penalty": round(fi_regulatory, 2),
            "q1_api_abuse_legal_liability": round(fi_legal, 2),
            "q1_api_abuse_remediation_cost": round(fi_remediation, 2),
            "q1_api_abuse_compute_overhead": round(fi_compute, 2),
            "q1_api_abuse_total": round(fi_total, 2),
        },
        "tier_breakdown": tier_breakdown,
        "cluster_accounts_sample": top_cluster_accounts[:10],
        "labeled_cluster_analysis": {
            "n_labeled_cluster_accounts": n_labeled_cluster_accounts,
            "labeled_cluster_account_share": round(n_labeled_cluster_accounts / total_accounts, 4),
            "labeled_cluster_q1_abuse_events": int(labeled_cluster_q1_abuse),
            "labeled_cluster_q1_abuse_share": labeled_cluster_q1_share,
            "note": "labeled_cluster = accounts with cluster_id in dataset; graph_clusters = independently detected via co-temporal analysis",
        },
    }


class AnalystAgent:
    """
    Phase 1 full implementation.

    Runs DuckDB + networkx analysis → calls LLM for interpretation →
    emits Evidence Bundle with full quantitative findings + narrative.
    """

    def __init__(self, phase: int = 1):
        self.phase = phase

    def run(self, capability_bundle_id: str, context_bundle_id: str) -> dict:
        """
        Full Phase 1 investigation run.
        Returns: {evidence_bundle_id, path, analysis_summary}
        """
        # Read upstream artifacts
        cb = read_artifact(capability_bundle_id)
        ctx = read_artifact(context_bundle_id)
        validate_envelope(cb)
        validate_envelope(ctx)

        task_id = cb["content"]["task_id"]
        question = cb["content"]["task_description"]

        print(f"\n[Analyst] Starting Phase 1 investigation")
        print(f"[Analyst] Task ID: {task_id}")
        print(f"[Analyst] Question: {question}")

        # ── Step 1: CDI Layer query (MANDATORY — before any analysis decision) ──
        reader = CDIReader(agent_name="analyst", task_id=task_id)
        reasoning_frameworks = reader.get_reasoning_frameworks()
        analogues = reader.get_analogues_for_problem(question)
        disciplinary_methods = reader.get_disciplinary_methods()
        # Query inference layer to ensure L1 is healthy before analysis
        l1_status = reader.get_inference_layer_status("L1")
        l2_status = reader.get_inference_layer_status("L2")

        cdi_query_record = {
            "domains_queried": list(reader.get_queried_domains()),
            "reasoning_modes_available": [m["id"] for m in reasoning_frameworks if m.get("activation_state") == "AVAILABLE"],
            "analogues_found": len(analogues) if isinstance(analogues, list) else 0,
            "l1_status": l1_status,
            "l2_status": l2_status,
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Select reasoning mode: ABDUCTIVE — what generative process explains this pattern?
        reasoning_mode = "ABDUCTIVE"
        generation_mode = "FIRST_PRINCIPLES"  # No prior high-similarity analysis in Second Brain

        print(f"[Analyst] CDI Layer queried: {cdi_query_record['domains_queried']}")
        print(f"[Analyst] Reasoning mode selected: {reasoning_mode}")

        # ── Step 2: Execute quantitative analysis ────────────────────────────────
        print(f"[Analyst] Running DuckDB + networkx analysis...")
        t_analysis = time.time()
        analysis_results = _run_duckdb_analysis(task_id)
        analysis_elapsed = round(time.time() - t_analysis, 2)
        print(f"[Analyst] Analysis complete in {analysis_elapsed}s")

        # ── Step 3: LLM interpretation call ─────────────────────────────────────
        print(f"[Analyst] Calling LLM for interpretation...")
        llm = LLMWrapper(agent_name="analyst", task_id=task_id)

        # Build a concise data summary for the LLM (key metrics only)
        va = analysis_results["volume_analysis"]
        ga = analysis_results["graph_analysis"]
        fia = analysis_results["fraud_incident_analysis"]
        fi_table = analysis_results["financial_impact_table"]
        aa = analysis_results["account_analysis"]

        labeled = analysis_results.get("labeled_cluster_analysis", {})
        data_summary = {
            "investigation_question": question,
            "period": "Q1 2024 (Jan-Mar 2024) vs subsequent quarters, 18-month dataset",
            "dataset": "Synthetic Financial Impact Analysis — 750K api_events, 2K accounts, 18 months",
            "volume_findings": {
                "q1_abuse_events": va["q1_2024_abuse_events"],
                "q2_abuse_events": va["q2_2024_abuse_events"],
                "q3_abuse_events": va["q3_2024_abuse_events"],
                "q1_spike_ratio_vs_non_q1_average": va["q1_spike_ratio"],
                "q1_abuse_rate": va["q1_abuse_rate"],
                "note": "spike_ratio > 1.0 means Q1 monthly average exceeds non-Q1 average"
            },
            "concentration_findings": {
                "q1_top20_accounts_abuse_share": aa["q1_top20_accounts_abuse_share"],
                "q1_top50_accounts_abuse_share": aa["q1_top50_accounts_abuse_share"],
                "max_abuse_per_account": aa["max_abuse_per_account"],
                "p99_abuse_per_account": aa["p99_abuse_per_account"],
                "median_abuse_per_account": aa["median_abuse_per_account"],
                "note": "high concentration = top few accounts drive most abuse"
            },
            "labeled_cluster_findings": {
                "n_labeled_cluster_accounts": labeled.get("n_labeled_cluster_accounts", 0),
                "cluster_account_share_of_population_pct": round(labeled.get("labeled_cluster_account_share", 0.0) * 100, 2),
                "labeled_cluster_q1_abuse_events": labeled.get("labeled_cluster_q1_abuse_events", 0),
                "labeled_cluster_q1_abuse_share_pct": round(labeled.get("labeled_cluster_q1_abuse_share", 0.0) * 100, 2),
                "note": "labeled_cluster = accounts with cluster_id column in dataset (clusters A, B, C); independent of graph detection"
            },
            "graph_detection_findings": {
                "accounts_with_co_temporal_abuse_in_q1": ga["n_graph_nodes"],
                "co_occurrence_edges": ga["n_graph_edges"],
                "connected_components": ga["n_connected_components"],
                "largest_cluster_size": ga["largest_component_size"],
                "second_cluster_size": ga["second_component_size"],
                "component_sizes": ga["component_sizes_top10"],
                "accounts_in_clusters_3plus": ga["n_clustered_accounts_3plus"],
                "graph_cluster_accounts_as_pct_of_population": round(ga["cluster_account_share_of_population"] * 100, 2),
                "graph_cluster_accounts_q1_abuse_share_pct": round(ga["cluster_q1_abuse_share"] * 100, 2),
                "note": "co_occurrence = two accounts both had >=5 abuse events in same week, >=2 weeks overlap. This is an INDEPENDENT detection method — compare to labeled_cluster findings above"
            },
            "fraud_incident_findings": {
                "q1_api_abuse_incidents": fia["q1_api_abuse_incidents"],
                "q1_cluster_incidents": fia["q1_cluster_incidents"],
                "q1_incident_rate_vs_period_average": fia["incident_q1_ratio"],
                "q1_total_financial_impact_from_incidents_usd": fia["q1_total_financial_impact_from_incidents"],
                "avg_impact_per_api_abuse_incident_usd": fia["incident_avg_impact_api_abuse_q1"],
            },
            "financial_impact_table_q1": {
                "direct_loss_usd": fi_table["q1_api_abuse_direct_loss"],
                "indirect_cost_usd": fi_table["q1_api_abuse_indirect_cost"],
                "remediation_cost_usd": fi_table["q1_api_abuse_remediation_cost"],
                "compute_overhead_usd": fi_table["q1_api_abuse_compute_overhead"],
                "total_usd": fi_table["q1_api_abuse_total"],
            },
        }

        # FSB injection — enrich system prompt with prior exemplars (Phase 4+)
        fsb = FewShotBank()
        enriched_analyst_prompt, fsb_injected_ids = fsb.inject_into_system_prompt(
            ANALYST_SYSTEM_PROMPT, "api_abuse_investigation", agent_name="analyst"
        )

        llm_response = llm.generate(
            system_prompt=enriched_analyst_prompt,
            user_message=json.dumps(data_summary, indent=2),
            max_tokens=4096,
        )

        # Parse LLM response
        llm_content = llm_response["content"]
        try:
            # Strip markdown code fences if present
            clean = llm_content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            interpretation = json.loads(clean.strip())
        except (json.JSONDecodeError, ValueError):
            # If JSON parsing fails, wrap the raw text in a structured format
            interpretation = {
                "hypothesis_assessment": {
                    "coordinated_abuse": {"probability": 0.5, "evidence_points": [], "against_points": []},
                    "organic_growth": {"probability": 0.5, "evidence_points": [], "against_points": []},
                },
                "primary_conclusion": "AMBIGUOUS",
                "conclusion_rationale": llm_content,
                "financial_impact_assessment": {
                    "conservative_usd": fi_table["q1_api_abuse_total"] * 0.7,
                    "base_case_usd": fi_table["q1_api_abuse_total"],
                    "methodology": "Financial impact table Q1 api_abuse total",
                    "confidence": "MEDIUM",
                },
                "countermeasure": {
                    "primary": "Deploy graph-based anomaly detection on co-temporal abuse patterns",
                    "implementation_path": "Build account co-occurrence graph; flag clusters with >=3 accounts sharing >=2 abuse-active weeks",
                    "secondary": "Implement per-account weekly abuse rate monitoring",
                    "hardening_step": "Validate detection threshold on historical data before production deployment",
                },
                "generation_mode": "ABDUCTIVE",
                "reasoning_chain": ["LLM response could not be parsed as JSON"],
                "known_limitations": ["LLM interpretation parsing failed — raw narrative only"],
                "confidence_score": 0.4,
            }

        # ── Step 4: Emit Evidence Bundle ─────────────────────────────────────────
        confidence = float(interpretation.get("confidence_score", 0.5))

        evidence_content = {
            "task_id": task_id,
            "investigation_question": question,
            "phase": self.phase,
            "hypotheses_tested": ["coordinated_abuse", "organic_growth"],
            "primary_conclusion": interpretation.get("primary_conclusion", "AMBIGUOUS"),
            "causal_claim": False,  # L1 rule: analyst never claims causation
            "generation_mode": interpretation.get("generation_mode", "ABDUCTIVE"),
            "reasoning_mode_selected": reasoning_mode,
            "cdi_query_record": cdi_query_record,
            "analysis_results": {
                "volume_analysis": analysis_results["volume_analysis"],
                "account_analysis": analysis_results["account_analysis"],
                "graph_analysis": analysis_results["graph_analysis"],
                "fraud_incident_analysis": analysis_results["fraud_incident_analysis"],
                "financial_impact_table": analysis_results["financial_impact_table"],
            },
            "llm_interpretation": interpretation,
            "capability_bundle_id": capability_bundle_id,
            "context_bundle_id": context_bundle_id,
            "lineage": {
                "data_sources": [
                    {"source": "data/raw/api_events.parquet", "role": "abuse event volume and timing"},
                    {"source": "data/raw/accounts.parquet", "role": "account tier and flag status"},
                    {"source": "data/raw/fraud_incidents.parquet", "role": "confirmed incident rates by vector"},
                    {"source": "data/raw/financial_impact.parquet", "role": "aggregated financial loss estimates"},
                ],
                "analysis_elapsed_sec": analysis_elapsed,
                "llm_call_id": llm_response["call_id"],
                "llm_input_tokens": llm_response["input_tokens"],
                "llm_output_tokens": llm_response["output_tokens"],
            },
        }

        evidence = create_artifact(
            artifact_type="evidence_bundle",
            producing_agent="analyst",
            phase=self.phase,
            content=evidence_content,
            provenance=[capability_bundle_id, context_bundle_id],
            confidence_score=min(0.95, max(0.1, confidence)),
            known_limitations=interpretation.get("known_limitations", [
                "Analysis based on synthetic dataset — real-world patterns may differ",
                "Graph clustering uses co-temporal co-occurrence, not direct communication links",
                "Financial impact derived from aggregated table, not individual incident attribution",
                "Q1 is the first quarter in the dataset — no year-over-year baseline available",
            ]),
        )
        path = write_artifact(evidence)

        print(f"[Analyst] Evidence Bundle written: {evidence['artifact_id']}")
        print(f"[Analyst] Conclusion: {interpretation.get('primary_conclusion', 'AMBIGUOUS')}")

        # ── Step 4b: Write to Second Brain vault ─────────────────────────────────
        write_analysis_entry(evidence)

        # ── Step 5: Record CDI non-activation ────────────────────────────────────
        updater = CDIUpdater(agent_name="analyst", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {
            "evidence_bundle_id": evidence["artifact_id"],
            "path": str(path),
            "conclusion": interpretation.get("primary_conclusion"),
            "confidence": confidence,
        }
