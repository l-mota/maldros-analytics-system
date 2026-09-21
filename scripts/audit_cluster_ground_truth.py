#!/usr/bin/env python3
"""
audit_cluster_ground_truth.py — C-053 ground-truth audit of the Phase 1 41-account cluster.

Reproduces, from primary source, the claim that the graph-detected coordinated-fraud
cluster achieves 100% recall against every labeled ground-truth account in the dataset
at 46% precision against any labeled ring.

Provenance
----------
The graph-analysis logic below is a faithful reproduction of the clustering block in
`agents/analyst/analyst.py` (the co-occurrence graph section): policy_violation events
in Q1 2024, >= 5 events per account-week, account pairs sharing >= 2 such weeks, and
networkx connected components over the resulting edge set.

C-053 (Maldros_Change_Tracker.md) recorded this audit on 2026-09-07 but the script was
run ad hoc from a Portfolio session sandbox and never saved. This file is that script,
written from the query documented in C-053 and in the Phase 1 postmortem's
"Audit Update — Item 1 Resolved" section, and verified to reproduce every control value
those two documents state.

Usage
-----
    python3 audit_cluster_ground_truth.py [DATA_ROOT]

DATA_ROOT defaults to ../data/raw relative to this file. A reviewer working from a clone
of the published repository can regenerate the dataset first with `data/generate_dataset.py`
(seeded np.random.seed(42)) and point DATA_ROOT at its output.

Exit status is 0 only when every control below reproduces.
"""
import sys
from pathlib import Path

import duckdb
import networkx as nx

# Control values as recorded in C-053 and the Phase 1 postmortem. The script asserts
# against these rather than printing numbers for a human to eyeball.
CONTROLS = {
    "graph_nodes": 41,
    "graph_edges": 462,
    "connected_components": 1,
    "accounts_total": 2000,
    "labeled_total": 19,
    "labeled_by_ring": {"cluster_a": 8, "cluster_b": 6, "cluster_c": 5},
    "true_positives": 19,
    "unlabeled_in_cluster": 22,
    "cluster_a_q1_incidents": 34,
    "cluster_a_q1_total_usd": 475802.92,
}

# The Q1 2024 window is the analysis scope throughout: analyst.py's clustering query is
# bounded to it, and the C-053 financial figure is computed inside it. Stated explicitly
# here because C-053's own prose omits the date scope, and without it the same phrase
# ("cluster_a's own fraud-incident total") computes to 73 incidents / $1,480,159.26.
Q1_START, Q1_END = "2024-01-01", "2024-04-01"


def build_cluster(con, api_path):
    """Reproduce analyst.py's co-occurrence graph. Returns (graph, components)."""
    weekly = con.execute(
        f"""
        SELECT account_id,
               CAST(strftime(timestamp, '%Y-%W') AS VARCHAR) AS year_week,
               COUNT(*) AS weekly_abuse_events
        FROM read_parquet('{api_path}')
        WHERE content_category = 'policy_violation'
          AND timestamp >= '{Q1_START}'
          AND timestamp <  '{Q1_END}'
        GROUP BY account_id, year_week
        HAVING COUNT(*) >= 5
        """
    ).df()

    week_to_accounts = {}
    for _, row in weekly.iterrows():
        week_to_accounts.setdefault(row["year_week"], []).append(row["account_id"])

    edge_weights = {}
    for accounts in week_to_accounts.values():
        for i in range(len(accounts)):
            for j in range(i + 1, len(accounts)):
                a, b = sorted([accounts[i], accounts[j]])
                edge_weights[(a, b)] = edge_weights.get((a, b), 0) + 1

    graph = nx.Graph()
    for (a, b), weight in edge_weights.items():
        if weight >= 2:  # >= 2 weeks of overlap, per analyst.py
            graph.add_edge(a, b, weight=weight)

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    return graph, components


def main(argv):
    here = Path(__file__).resolve().parent
    data_root = Path(argv[1]).resolve() if len(argv) > 1 else (here.parent / "data" / "raw")
    api_path = data_root / "api_events.parquet"
    accounts_path = data_root / "accounts.parquet"
    fraud_path = data_root / "fraud_incidents.parquet"
    for p in (api_path, accounts_path, fraud_path):
        if not p.exists():
            print(f"FATAL: missing {p}", file=sys.stderr)
            return 2

    con = duckdb.connect()
    graph, components = build_cluster(con, api_path)
    detected = set(components[0]) if components else set()

    accounts = con.execute(f"SELECT * FROM read_parquet('{accounts_path}')").df()
    labeled = accounts[accounts["cluster_id"].notna()]
    labeled_ids = set(labeled["account_id"])
    true_positives = labeled_ids & detected

    recall = 100.0 * len(true_positives) / len(labeled_ids) if labeled_ids else 0.0
    precision = 100.0 * len(true_positives) / len(detected) if detected else 0.0

    financial = con.execute(
        f"""
        SELECT COUNT(*) AS n, ROUND(SUM(financial_impact_usd), 2) AS total
        FROM read_parquet('{fraud_path}')
        WHERE cluster_id = 'cluster_a'
          AND detected_date >= '{Q1_START}'
          AND detected_date <  '{Q1_END}'
        """
    ).df()
    fin_n = int(financial["n"].iloc[0])
    fin_total = float(financial["total"].iloc[0])

    observed = {
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "connected_components": len(components),
        "accounts_total": len(accounts),
        "labeled_total": len(labeled_ids),
        "labeled_by_ring": {
            str(k): int(v) for k, v in labeled["cluster_id"].value_counts().items()
        },
        "true_positives": len(true_positives),
        "unlabeled_in_cluster": len(detected) - len(true_positives),
        "cluster_a_q1_incidents": fin_n,
        "cluster_a_q1_total_usd": fin_total,
    }

    print(f"Data root: {data_root}")
    print(f"Graph: {observed['graph_nodes']} nodes, {observed['graph_edges']} edges, "
          f"{observed['connected_components']} connected component(s)")
    print(f"Detected cluster: {len(detected)} accounts")
    print(f"Ground truth: {observed['labeled_total']} labeled accounts of "
          f"{observed['accounts_total']} — {observed['labeled_by_ring']}")
    print(f"RECALL    = {len(true_positives)}/{len(labeled_ids)} = {recall:.1f}%")
    print(f"PRECISION = {len(true_positives)}/{len(detected)} = {precision:.1f}%  (any labeled ring)")
    for ring in sorted(CONTROLS["labeled_by_ring"]):
        ring_ids = set(accounts[accounts["cluster_id"] == ring]["account_id"])
        hit = len(ring_ids & detected)
        print(f"  {ring}: {hit}/{len(ring_ids)} recalled; "
              f"{100.0 * hit / len(detected):.1f}% of the detected cluster")
    print(f"Unlabeled inside the detected cluster: {observed['unlabeled_in_cluster']}")
    print(f"cluster_a fraud incidents, {Q1_START}..{Q1_END}: "
          f"{fin_n} incidents, ${fin_total:,.2f}")

    failures = []
    for key, expected in CONTROLS.items():
        got = observed[key]
        ok = abs(got - expected) < 0.005 if isinstance(expected, float) else got == expected
        if not ok:
            failures.append(f"  {key}: expected {expected}, got {got}")

    if failures:
        print("\nCONTROL FAILURES — the audit did NOT reproduce:")
        print("\n".join(failures))
        return 1
    print("\nAll controls reproduced. C-053 verified against primary source.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
