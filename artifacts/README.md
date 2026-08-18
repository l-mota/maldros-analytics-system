# `artifacts/`

Every agent-to-agent hand-off is a JSON file with a fixed envelope: `artifact_id`, `artifact_type`, `phase_of_origin`, `producing_agent`, `timestamp_utc`, `provenance`, `schema_version`, `content`, `known_limitations`, `confidence_score`. Artifacts are written once, content-hashed, and immutable — a correction produces a new versioned artifact referencing the original in its `provenance` field rather than editing it in place. That is why an investigation is simultaneously a conclusion and a full record of how the conclusion was produced.

This folder ships the schemas and four real examples. **The full artifact store is not committed** — it is runtime output, excluded in `.gitignore` along with the chart renders.

## Schemas

Eight hand-off types. Each requires the same eleven envelope fields, then constrains `content` per type.

| Schema | Emitted by | Required `content` fields |
|---|---|---|
| `capability_bundle.schema.json` | Orchestrator | 10 |
| `context_bundle.schema.json` | Orchestrator | 8 |
| `evidence_bundle.schema.json` | Analyst | 8 |
| `statistical_result.schema.json` | Statistician | 6 |
| `red_team_report.schema.json` | Red-Team | 6 |
| `discovery_report.schema.json` | Storyteller | 9 |
| `aims_mode_a.schema.json` | Operational log (auto-logged) | 9 |
| `aims_mode_b.schema.json` | Storyteller (stakeholder briefing) | 12 |

## Examples

Four artifacts taken from real runs, not hand-written illustrations.

| File | What it shows |
|---|---|
| `capability_bundle.example.json` | The first artifact of every task — the CDI Layer snapshot the Orchestrator emits before any downstream agent begins. Confidence 0.90. |
| `evidence_bundle.example.json` | The Analyst's Phase 1 hand-off to the Statistician. Confidence 0.72. |
| `aims_mode_b.example.json` | A stakeholder briefing that passed: `l1_compliance_summary.overall_passed` is `true`. |
| `aims_mode_b_blocked.example.json` | The same artifact type, blocked. `causal_check` is `false`; the citation and omission checks both passed. The report does not ship. |

The last pair is the reason for shipping examples at all. The two files are structurally identical and differ in one boolean — and that boolean is what stands between a draft and a delivered stakeholder briefing. Both carry a `human_approval_gate` field regardless of outcome.

A documented divergence between the Mode B schema's required fields and the asset set the shipped renderer emits is disclosed in [`docs/engineering_process.md`](../docs/engineering_process.md) rather than quietly reconciled.
