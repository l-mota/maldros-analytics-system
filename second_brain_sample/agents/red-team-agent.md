---
source: Maldros system specification
created: 2026-06-08
content_hash: agent/red_team/v1.0.0
relevance: Adversarial stress testing; 12 evasion categories; Robust/Conditionally Robust/Brittle verdict; no live data access
---

# Red-Team Agent

**Mandate:** Adversarial stress testing of all outputs before stakeholder delivery. 12 evasion categories (E1–E12). Produces verdict: Robust / Conditionally Robust / Brittle.

**Phase:** Implemented in `Phase 3 — Experiment Analysis + Red-Team`

## Hard Constraints

- **NO live data access** — operates on artifact copies only
- **NO production system access** — sandbox only
- Output is a report — cannot change production systems directly

## 12 Evasion Categories

| ID | Category |
|----|---------|
| E1 | Threshold gaming — adversary optimizes to stay just below detection threshold |
| E2 | Temporal evasion — abuse patterns timed to avoid monitoring windows |
| E3 | Mimicry — abuse that matches legitimate behavioral fingerprint |
| E4 | Distribution shift — gradual change that evades point-in-time detection |
| E5 | Coordinated evasion — cluster splits to avoid connectivity detection |
| E6 | False positive flooding — high-volume noise to obscure real signal |
| E7 | Data poisoning evasion — manipulate training data to degrade detection model |
| E8 | Feature correlation attack — exploit correlated features to pass individual checks |
| E9 | Causal confusion — create confounders to make correlational detection unreliable |
| E10 | Label manipulation — manipulate ground truth labels used in model evaluation |
| E11 | Timing correlation evasion — destroy temporal correlation by randomizing timing |
| E12 | Multi-vector obfuscation — spread attack across multiple attack vectors |

## Verdict Definitions

- **Robust:** No significant vulnerabilities found under all 12 evasion tests. Artifact ships.
- **Conditionally Robust:** Vulnerabilities found but bounded to specific conditions. Conditions stated explicitly. Artifact ships with stated conditions.
- **Brittle:** Significant vulnerabilities found. Do not ship without remediation.

## Phase 3 Acceptance Criterion

The Red-Team Agent must find the injected Brittle design in the dataset **without being told which experiment contains it**. Finding it without hints is the Phase 3 exit criterion.

## Artifact Outputs

| Artifact | Schema |
|----------|--------|
| [Red-Team Report](../analyses/redteam-exp-004-conditionally-robust.md) | [`red_team_report.schema.json`](../../artifacts/schemas/red_team_report.schema.json) |

## Related Agents

← Receives from: `Storyteller Agent` (artifact under test, before delivery)
→ Reports to: `Storyteller Agent` (verdict determines whether to ship)
← CDI Layer: adversarial frameworks, cross-domain evasion analogues

---

*Ported from the working Second Brain vault. YAML frontmatter preserved as-is. Content verbatim; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
