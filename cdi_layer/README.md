# `cdi_layer/`

The Cross-Domain Intelligence Layer — the always-on index every agent queries before it acts. It is not computed per task. It is a continuously maintained store, and an agent that produces output without a recorded CDI query in its lineage trace is a Diagnostic Agent L1 failure. Agents receive a snapshot of it for their task context (the Capability Bundle) rather than re-deriving it.

| Path | What it holds |
|---|---|
| `services/cdi_read.py` | The read interface. Every agent queries here directly. |
| `services/cdi_update.py` | The update interface. Index changes propagate through this — never by direct file write. |
| `capability_registry/capability_registry.json` | The capability-expansion properties and the failure protocol that applies when one is evaluated but not met. |
| `index/cdi_index.json` | Master index: domains, capability-expansion properties, update triggers. |
| `index/reasoning_frameworks.json` | The reasoning modes an agent may declare on its output. |
| `index/disciplinary_methods.json` | Analytical methods indexed by discipline. |
| `index/cross_domain_analogues.json` | Repair and framing strategies drawn from analogue domains — the substrate the Healing Agent retrieves from. |
| `index/inference_layers.json` | The five-layer inference stack and its arbitration invariant: L1 blocks are final and L5 cannot override them. |
| `index/external_knowledge.json` | Retrieved external intelligence signals. |
| `index/second_brain_signal.json` | Vault state, high-similarity clusters, open constraints, recent additions, coverage gaps. |
| `index/exemplar_surface.json` | Few-Shot Bank state and promotion-gate status. |
| `index/phase7_signals.json` | Bottleneck candidates, cross-phase patterns, improvement proposals, telemetry coverage. |
| `index/design_system.json` | The visual design system expressed as a queryable CDI domain — communication pattern, colour system, typography, chart construction rules. |

**One index file is deliberately absent.** `non_activation_log.json` — the record of which CDI domains were queried and returned nothing, plus the blind-spot alerts derived from it — is runtime state regenerated on every run, and is excluded in `.gitignore` alongside telemetry and the AIMS logs. The code that reads and writes it is here; the accumulated log is not.

The non-activation log is worth knowing about even though it does not ship. A capability index that only records hits cannot tell you what the system consistently failed to reach for, which is the more useful signal — so the layer logs its own misses and raises a blind-spot alert when a domain goes unqueried past a threshold.
