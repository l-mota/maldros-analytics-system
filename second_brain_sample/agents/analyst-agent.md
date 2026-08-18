---
source: Maldros system specification
created: 2026-06-08
content_hash: agent/analyst/v1.0.0
relevance: End-to-end investigation agent; forms hypotheses, queries data, executes Python, interprets results
---

# Analyst Agent

**Mandate:** End-to-end investigation — hypotheses → data query → Python execution → interpretation → recommendations.

**Phase:** Implemented in `Phase 1 — First End-to-End`

## Toolset (Bound)

| Tool | Access |
|------|--------|
| CDI Layer query | All 9 domains; mid-task access permitted |
| BigQuery data query | Via `semantic layer` interface only |
| Python execution | pandas, polars, networkx, scipy (via scripted code execution) |
| Web search | External intelligence retrieval |
| Artifact read/write | All types |

> **Editorial note on row 2, added for this sample and not present in the source.** The source note names BigQuery because BigQuery is the *specified production warehouse*. The recorded runs did not use it — they ran DuckDB over Parquet, which is what ships in this repository. The row is retained unedited rather than quietly corrected, because the gap between the specified target and the exercised implementation is exactly the kind of thing a reader is entitled to see. Nothing here was deployed to a production warehouse.

## Investigation Protocol

1. Receive `Context Bundle` from `Orchestrator`
2. Query `CDI Layer` for alternative approaches before committing (`CEP_2`, `CEP_3`)
3. Record CDI-surfaced alternatives and selection rationale in `Evidence Bundle` lineage trace
4. Query data via `semantic layer` (natural language → execution plan → result)
5. Execute Python for analysis, graph detection, statistical computation
6. Form and rank hypotheses
7. Produce `Evidence Bundle`
8. Mid-task CDI re-query permitted if findings surface unexpected patterns

## Key Constraints

- Must query `CDI cross_domain_analogues` before finalizing any hypothesis (`CEP_3`)
- Must record at least one alternative approach in Evidence Bundle lineage trace (`CEP_2`)
- Cannot use SQL as primary interface — semantic layer is the data query interface
- Sandboxed SQL available for explicit invocation; logged to `AIMS Mode A`

## Artifact Outputs

| Artifact | Schema |
|----------|--------|
| `Evidence Bundle` | [`evidence_bundle.schema.json`](../../artifacts/schemas/evidence_bundle.schema.json) |

## Signals in Dataset Requiring Analyst Skills

- `Signal 1 — Coordinated Clusters`: networkx graph analysis of `api_events`
- `Signal 2 — Safety Bypass Escalation`: SPRT on `fraud_incidents` cluster_b
- `Signal 5 — Regulatory Lag`: lag-correlation between `fraud_incidents` and `regulatory_events`

## Metrics Consumed

[api_abuse_rate](../metrics/api_abuse_rate.md) · `fraud_loss_direct` · `account_takeover_volume` · [safety_bypass_incidents](../metrics/safety_bypass_incidents.md) · `downstream_harm_exposure` · `compliance_cost_per_incident`

## Related Agents

← Input from: `Orchestrator` (Context Bundle + task decomposition)
→ Output to: [Statistician Agent](statistician-agent.md) (Evidence Bundle for validation)
← Monitored by: `Diagnostic Agent`
→ Stress-tested by: [Red-Team Agent](red-team-agent.md)

## CDI Layer — Required Queries

| Query Type | CDI Domain | CEP |
|-----------|-----------|-----|
| Alternative approaches | disciplinary_methods, cross_domain_analogues | CEP_2 |
| Non-obvious hypothesis | cross_domain_analogues | CEP_3 |
| External intel | external_knowledge | — |
| Prior analyses | second_brain_signal | — |

---

*Ported from the working Second Brain vault. YAML frontmatter preserved as-is. Content verbatim except the clearly-marked editorial note above; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. One phrase — the Python execution harness — was generalized to "scripted code execution" under the repository's tooling-anonymisation rule. See [the sample index](../README.md) for the full porting rules.*
