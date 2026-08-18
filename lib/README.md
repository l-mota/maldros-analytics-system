# `lib/`

Shared machinery every agent depends on. Nothing here is agent-specific — each module implements one cross-cutting guarantee.

| Module | Introduced | What it does |
|---|---|---|
| `artifact.py` | Phase 0 | Creates, validates and stores the artifact envelope. Write-once, content-hashed, immutable; corrections produce a new versioned artifact referencing the original. |
| `llm_wrapper.py` | Phase 1 (full portability layer, Phase 6) | The single point every language-model call passes through, so the model is swappable without touching agent code. |
| `second_brain.py` | Phase 1 | The knowledge-vault write interface. Every artifact write is immediately followed by a vault write through this module — agents never write vault entries directly. |
| `design_tokens.py` · `design_tokens.css` | — | Single source of truth for the visual design system's colour and typography constants, for Python-side and HTML-side consumers respectively. |
| `telemetry.py` | Phase 4 | Captures (agent output, human edit, accepted output) triples from every analyst correction, computes structural diffs, and clusters edit patterns. |
| `promotion_gate.py` | Phase 4 | Categorises captured corrections and routes each to the right destination. |
| `few_shot_bank.py` | Phase 4 | Versioned store of approved exemplars, surfaced into agent prompt context for the matching query class. |
| `algorithmic_rule.py` | Phase 4 | The mandatory exploration budget. Every tenth investigation cycle is diverted to a counter-intuitive hypothesis from the open Constraint Register; the counter persists to disk, so the obligation survives a process restart. |
| `research_loop.py` | Phase 4 | A closed research loop triggered by open Constraint Register entries. |
| `aims_router.py` | Phase 6 | Deterministic routing of every artifact to either the operational log or the stakeholder-briefing path. |
| `bottleneck_detector.py` | Phase 6 | Aggregates telemetry across prior investigation cycles and identifies structural bottlenecks with evidence-based confidence scores. |
| `phase7_proposals.py` | Phase 6 | Generates an improvement proposal for the highest-priority bottleneck — and routes it to the Confirmation Gate rather than applying it. |

The last two are the self-improvement loop, and they are deliberately incomplete on their own. `bottleneck_detector.py` finds the problem and `phase7_proposals.py` writes the proposal, but neither can act on one. That path terminates at `governance/confirmation_gate/confirmation_gate.py`, and it terminates there by construction rather than by convention.

Two design choices in this folder are worth noticing. `algorithmic_rule.py` hard-codes an exploration obligation the system cannot skip — the operator may adjust its magnitude, not switch it off. And `design_tokens.py` / `design_tokens.css` exist so that a colour has exactly one definition; editing a token in a consumer file instead of here is treated as a design-system violation rather than a shortcut.
