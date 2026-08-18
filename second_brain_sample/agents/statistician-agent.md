---
source: Maldros system specification
created: 2026-06-08
content_hash: agent/statistician/v1.0.0
relevance: Validates all inferences; experiment analysis; SRM/novelty detection; ship/no-ship verdicts
---

# Statistician Agent

**Mandate:** Validate all inferences from the `Evidence Bundle`. Experiment analysis. SRM/novelty effect detection. Ship/no-ship verdicts.

**Phase:** Implemented in `Phase 1 — First End-to-End` (experiment analysis in `Phase 3`)

## Toolset (Bound)

| Tool | Access |
|------|--------|
| CDI Layer query | reasoning_frameworks, inference_layers |
| Python execution | statsmodels, scipy, pingouin |
| Artifact read/write | Evidence Bundle in; Statistical Result out |

## Key Constraints

- Cannot override `L1 Heuristic Layer` vetoes — if L1 rejects, Statistician must document the veto, not argue against it
- Must query CDI Layer for alternative statistical frameworks before selecting validation approach (`CEP_4`)
- Flags insufficient N explicitly — does not report significance on underpowered tests
- SRM detection uses chi-squared test with threshold p < 0.001 (stricter than 0.05)

## Experiment Analysis Protocol

For each experiment (`experiments` table):

1. Check SRM: `chi2_contingency([[control_n, treatment_n], [planned_n, planned_n]])` — flag if p < 0.001
2. Check novelty: fit exponential decay to week-by-week effect; flag if decay rate significant
3. Power analysis: verify N is adequate for claimed effect size at α=0.05, β=0.20
4. Ship/no-ship: `SHIP` only if all pass (no SRM, no novelty, adequate power, p < threshold)

## Artifact Outputs

| Artifact | Schema |
|----------|--------|
| [Statistical Result](../analyses/statistical-result-phase1-c26f19d3.md) | [`statistical_result.schema.json`](../../artifacts/schemas/statistical_result.schema.json) |

## Dataset Signals Requiring Statistician Skills

- `Signal 3 — Experiment Pathologies`: EXP-001 (SRM), EXP-002 (SRM), EXP-003 (novelty), **EXP-004 (genuine)** — see the Red-Team stress test of EXP-004 at [RedTeam — EXP-004 — Conditionally Robust](../analyses/redteam-exp-004-conditionally-robust.md)
- `Signal 2 — Safety Bypass Escalation`: SPRT rate-change detection for `fraud_incidents` cluster_b, measured by [safety_bypass_incidents](../metrics/safety_bypass_incidents.md)

## Related Agents

← Input from: [Analyst Agent](analyst-agent.md) (Evidence Bundle)
→ Output to: `Storyteller Agent` (Statistical Result)
← Monitored by: `Diagnostic Agent`
→ Stress-tested by: [Red-Team Agent](red-team-agent.md)

## CDI Layer Required Queries

- `CDI reasoning_frameworks`: select appropriate reasoning mode for validation
- `CDI inference_layers`: check L1-L4 status before validation

---

*Ported from the working Second Brain vault. YAML frontmatter preserved as-is. Content verbatim; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. Two links in the "Dataset Signals" section were resolved to their in-sample targets so the traversal is walkable — in the source vault those targets are reached by note title, not by an explicit wikilink. See [the sample index](../README.md), which explains why that edge had to be added.*
