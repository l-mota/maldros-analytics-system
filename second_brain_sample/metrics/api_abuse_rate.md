# api_abuse_rate

> **Summary:** Ratio metric — share of API events classified as policy violations or borderline. Primary leading indicator for API abuse. Triggers Confirmation Gate at 5%.

---

**Source:** `semantic_layer/metrics/api_abuse_rate.yaml`
**Owner:** analyst · fraud_abuse_analytics
**Type:** ratio
**Grain:** daily (default); hourly (incident investigation mode)
**Judgment mechanism:** Mechanism 1 — fully computable from data
**Version:** 1.0.0 (2026-06-08)

---

## Definition

Share of API call events classified as `policy_violation` or `borderline` over total API call events in the period. Primary operational metric for Vector 1 (Content Generation) and Vector 2 (Operational Scaling) threat classes per FIA §1.1–1.2.

## Computation Logic

```python
# abuse_events: api_events where content_category IN ('policy_violation', 'borderline')
abuse_count = api_events[
    (api_events['content_category'].isin(['policy_violation', 'borderline']))
    & (api_events['timestamp'] >= period_start)
    & (api_events['timestamp'] < period_end)
].shape[0]

total_count = api_events[
    (api_events['timestamp'] >= period_start)
    & (api_events['timestamp'] < period_end)
].shape[0]

api_abuse_rate = abuse_count / total_count if total_count > 0 else None
```

## Applicable Filters

- [`attack_vector`](../dimensions/attack_vector.md) — filter to `api_abuse` for vector-specific view
- `account_tier` (free / pro / enterprise / trial)
- `region` (US / EU / APAC / LATAM)
- `time_period` (daily / weekly / monthly)
- `is_flagged` — True to focus on known-bad accounts
- `cluster_id` — for cluster-specific investigation

## Benchmarks and Thresholds

| Level | Threshold | Action |
|-------|-----------|--------|
| Industry low | 0.8% | Well-managed platform |
| Industry high | 3.2% | Elevated abuse environment |
| Alert | 5% | Confirmation Gate review triggered |
| Critical | 10% | AIMS Mode B + team escalation |

## Policy Rationale

Primary leading indicator for API abuse. Borderline category is included because borderline events are material precursors to confirmed violations — excluding them understates exposure. Segment borderline from policy_violation when analyzing classifier precision; combine them here for exposure measurement.

A sustained rate above 3% in any 7-day window triggers Confirmation Gate review.

## Known Limitations

- content_category classification depends on model output which may drift (monitor PSI on content_category distribution as proxy for classifier drift)
- borderline category has lower precision than policy_violation; segment separately when analyzing classifier performance
- does not capture abuse that evades content classification (the `unknown` category should be monitored separately)
- at high query volumes, borderline events can be transiently misclassified due to model rate limits

## Phase 1 Usage

Used in Analyst Agent's volume analysis and graph investigation. Q1 2024 abuse rate computed as 0.094 (9.4% of events). See [Analysis — Is the spike in API abuse volume in Q1 of the synthetic data — Phase](../analyses/q1-api-abuse-investigation.md).

## Links

[Analyst Agent](../agents/analyst-agent.md) · [Statistician Agent](../agents/statistician-agent.md) · [attack_vector](../dimensions/attack_vector.md) · `account_tier` · `region` · `time_period` · `api_account` · `fraud_incident` · `Constraint Register`

---

*Ported from the working Second Brain vault. Content verbatim; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
