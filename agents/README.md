# `agents/`

Nine agents. Each is a directory containing a `system_prompt.md` — the mandate, constraints and output contract the agent runs under — and a Python implementation that executes it. Mandate and toolset are specified as a pair rather than independently: a narrow mandate with an unbounded toolset still permits authority creep, and a bounded toolset under a vague mandate still permits cross-component corruption. The pairing is the unit of governance.

Eight of the nine compose the investigation chain. The ninth, the Forge, runs Phase 5 invention cycles outside that chain and does not appear in the chain diagram in the case study.

| Directory | Agent | Mandate | Notable constraint |
|---|---|---|---|
| `orchestrator/` | Orchestrator | Decomposes the question, queries the knowledge vault, routes to specialists | Emits a Capability Bundle as the first artifact of every task — no exceptions |
| `data_architect/` | Data Architect | Designs and validates data models and semantic-layer definitions | Writes YAML to draft, not into the live semantic layer |
| `analyst/` | Analyst | Hypotheses → query → Python execution → interpretation → recommendations | Query implementation is shaped around its demonstrated investigation, not generalised to arbitrary questions |
| `statistician/` | Statistician | Validates every inference; experiment analysis; sample-ratio-mismatch and novelty-effect detection; ship / no-ship verdicts | Cannot override an L1 veto — must document it, not argue with it |
| `storyteller/` | Storyteller | Dual-layer output, technical and plain-language; renders its own charts | Three deterministic L1 vetoes: causal language, citation coverage, omission audit |
| `diagnostic/` | Diagnostic | Continuous read-only monitoring on an L0–L4 escalation ladder | No write access at all, by design |
| `healing/` | Healing | Characterises a failure, retrieves repair strategies across five analogue disciplines, scores, applies, verifies | Drafts only — never merges to production |
| `red_team/` | Red-Team | Adversarial stress testing across twelve evasion categories (E1–E12); returns Robust / Conditionally Robust / Brittle | No live-data access and no production-system access |
| `forge/` | Forge | Invention engine; operates seven declared reasoning modes under an explicit novelty floor | Must survive Red-Team review *before* statistical validation, not after |

Two rules bind every agent here, and both are checkable in the code rather than asserted in prose. Every agent queries the Cross-Domain Intelligence Layer before acting and records that query in its lineage trace — an output without one is a Diagnostic Agent L1 failure. And every artifact write is immediately followed by a knowledge-vault write through `lib/second_brain.py`; no agent may produce an artifact without a corresponding vault entry.

**Reading them without running them.** The system prompts are the more informative half of each directory. They are the specification the implementation is checked against, and they carry the constraints, the escalation thresholds and the refusal conditions in full. Running the implementations requires a language-model API key and the artifact store, neither of which ships with this repository.
