# `data/`

The synthetic dataset layer. Seven tables modelling eighteen months of AI-platform fraud, abuse and financial-impact analytics, generated under a fixed seed. The data is engineered to be analytically difficult rather than merely large: coordinated clusters that graph analysis finds but thresholds do not, gradual escalation detectable only sequentially, and deliberately injected experiment pathologies.

| Path | What it is |
|---|---|
| `generate_dataset.py` | The generator. Produces all seven tables from a single seed-and-scale parameter. |
| `_signal_manifest.json` | The acceptance record: seed, scale, per-table row counts, and the five required signal patterns checked against their Phase 0 acceptance criteria. |
| `schemas/*.schema.json` | Per-table JSON schemas — `accounts`, `api_events`, `experiments`, `financial_impact`, `fraud_incidents`, `pipeline_health`, `regulatory_events`. |
| `samples/*_sample.csv` | Small row extracts, one per table, shipped so the schemas are legible without running the generator. |

**`samples/` is not the dataset the case-study figures were computed from.** Those figures came from the full generated tables — roughly 750,000 API events, ~2,000 accounts, 475 fraud incidents, 198 financial-impact rows, 20 experiments, 7,500 pipeline-health records and 50 regulatory events. The samples are extracts for schema legibility. Running an analysis against them will not reproduce the figures, and is not meant to.

The generated Parquet output is excluded in `.gitignore` — regenerate it with `generate_dataset.py` rather than expecting it in a clone.

**The data is synthetic and no conclusion drawn from it transfers to a real platform.** It models the domain closely enough that the analysis is non-trivial, which is the point; it is not real company data, and nothing in this repository claims otherwise.
