# `semantic_layer/`

Metric, dimension, entity and policy definitions in YAML. This is the layer that makes a metric mean one thing across every agent that touches it: an agent asking for `api_abuse_rate` gets the same computation, the same grain and the same declared limitations regardless of which investigation it is running.

| Path | Contents |
|---|---|
| `metrics/` | Six metrics — `api_abuse_rate`, `fraud_loss_direct`, `account_takeover_volume`, `safety_bypass_incidents`, `downstream_harm_exposure`, `compliance_cost_per_incident`. |
| `dimensions/` | Four dimensions — `attack_vector`, `account_tier`, `region`, `time_period`. |
| `entities/` | Three entities — `api_account`, `fraud_incident`, `regulatory_action`. |
| `policies/` | `metric_governance.yaml` and `query_authorization.yaml` — who may define or change a metric, and what a query is permitted to reach. |

Every metric definition carries its computation logic as Python pseudocode rather than SQL, its grain, its applicable filters, an owner, a policy rationale, a version history, and **its known limitations**. That last field is not decorative. `api_abuse_rate` declares four limitations of the classifier it depends on, and the Red-Team Agent's Conditionally Robust verdict on EXP-004 turns on exactly that class of declared blind spot: a metric that counts *detected* incidents cannot distinguish a treatment that works from a treatment that suppresses logging.

SQL is deliberately not the default interface anywhere in this system. It is a subordinate execution capability, available on explicit invocation in sandboxed mode; the default path is natural language → execution plan → result. Agents do not emit SQL as their primary output.

The corresponding knowledge-vault notes for `api_abuse_rate`, `safety_bypass_incidents` and `attack_vector` are in [`second_brain_sample/`](../second_brain_sample/), where the same definitions appear as linked notes rather than YAML.
