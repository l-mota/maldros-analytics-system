# `scripts/`

Entry points for the six phase demonstrations, plus the report renderer. Each script resolves the repository root relative to its own location, so the `scripts/phaseN/` layout is required rather than cosmetic — run them from the repository root.

| Script | What it runs |
|---|---|
| `phase1/run_investigation.py` | The first end-to-end investigation: Orchestrator → Analyst → Statistician → Storyteller, one natural-language question to one governed output. |
| `phase2/inject_failures.py` | Injects three synthetic failure scenarios — structural break, gradual degradation, cascade — into copies of the baseline tables. |
| `phase2/run_phase2_demo.py` | The self-healing demonstration: detection, severity classification, and cross-domain remediation of those three failures. |
| `phase3/run_phase3_demo.py` | Experiment analysis with the Red-Team Agent — three experiments analysed blind, with no advance disclosure of which carried which pathology. |
| `phase4/run_phase4_demo.py` | The self-improving cycle: telemetry capture, promotion gate, few-shot bank, and the exploration rule firing on schedule. |
| `phase5/run_phase5_demo.py` | The Forge — invention cycles under the novelty floor, with adversarial review preceding statistical validation rather than following it. |
| `phase6/run_phase6_demo.py` | Full AIMS routing end to end, terminating at the Confirmation Gate. |
| `render_aims_report.py` | The canonical reference implementation of the visual design system, and the renderer that produced `case-study/aims_mode_b_report.html`. |

**What will and will not run from a fresh clone.** The phase demos require a language-model API key and the full artifact store; neither ships here. `render_aims_report.py` reads from an artifact directory that is not committed, so it exits with a not-found error rather than rendering.

These scripts are here to be read as the executable specification of each phase. The sequence of agent calls, the gates between them, and the exit criteria each phase was checked against are all legible from the source without executing anything — which is the more useful thing to inspect, since a run against a synthetic dataset proves less than the wiring that constrains the run.
