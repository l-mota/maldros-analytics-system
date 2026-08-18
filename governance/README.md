# `governance/`

The human-oversight layer. If one folder in this repository carries the architecture's central claim, it is this one.

| Path | What it is |
|---|---|
| `confirmation_gate/confirmation_gate.py` | The Confirmation Gate. Catches triggering conditions, routes to the Review Queue, raises a HIGH notification, enforces no-auto-approve, and logs every decision. |
| `notification/notification.py` | Notification tiers and delivery, plus Review Queue depth monitoring against the Green / Yellow / Orange / Red / Critical thresholds. |
| `operator_config.json` | Operating windows, review-capacity ceiling, materiality threshold, dataset-quality thresholds, notification preferences, the exploration-budget setting, model selection, and the recorded Phase 0 acceptance. |
| `judgment_metric_registry.json` | Every analyst-judgment-bound metric with its handling mechanism, plus the Phase 0 exit-criterion check confirming no unresolved metric gates a phase transition or triggers the Confirmation Gate. |

**No auto-approve, under any condition.** Not on timeout, not on operator absence, not for a proposal the system generated itself and rates highly. Silence is not approval. This is a code-level constant rather than a policy document, and it is why one self-generated improvement proposal is currently sitting in the queue unapproved rather than quietly merged.

That queued proposal is listed among the project's limitations, but only because the alternative — approving it automatically — would have been the actual defect. The gate holding a real item is the strongest available evidence that it holds.

`confirmation_gate.py` is short. If you read one file in this repository, read that one: it is where the central claim is either true or false.

The Review Queue's accumulated contents and the notification log are runtime state, excluded in `.gitignore`. The mechanism is committed here; the run history is not.
