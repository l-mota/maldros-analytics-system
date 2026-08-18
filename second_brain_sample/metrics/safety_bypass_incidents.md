# safety_bypass_incidents

> **Summary:** Count metric — confirmed safety bypass incidents (jailbreaks, prompt injection, adversarial inputs). Tracked separately from API abuse due to distinct regulatory implications and SPRT escalation detection protocol.

---

**Source:** `semantic_layer/metrics/safety_bypass_incidents.yaml`
**Owner:** analyst · fraud_abuse_analytics
**Type:** count
**Grain:** monthly (default); weekly (trend investigation mode)
**Judgment mechanism:** Mechanism 1 — count metric, fully computable; SPRT configuration parameters require initial analyst judgment, then validated quarterly
**Version:** 1.0.0 (2026-06-08)

---

## Definition

Count of confirmed safety bypass incidents where `attack_vector = 'safety_bypass'` in the `fraud_incidents` table. Tracks volume of events where users or attackers deliberately circumvented model safety guardrails: jailbreaks, prompt injections, system prompt extraction, adversarial inputs. This is a count metric (not a rate); use [api_abuse_rate](api_abuse_rate.md) for the rate view, `fraud_loss_direct` for financial impact.

## Computation Logic

```python
safety_bypass_incidents = fraud_incidents[
    (fraud_incidents['attack_vector'] == 'safety_bypass')
    & (fraud_incidents['detected_date'] >= period_start)
    & (fraud_incidents['detected_date'] < period_end)
].shape[0]

# Trend analysis (for SPRT): monthly rate per account
monthly_rate_by_account = (
    fraud_incidents[fraud_incidents['attack_vector'] == 'safety_bypass']
    .assign(month=lambda df: pd.to_datetime(df['detected_date']).dt.to_period('M'))
    .groupby(['account_id', 'month'])
    .size()
    .reset_index(name='incident_count')
)
```

## SPRT Configuration

| Parameter | Value |
|-----------|-------|
| Null hypothesis rate | 1.0 incidents/account/month |
| Alternative rate | 3.0 incidents/account/month |
| Alpha (false positive) | 0.05 |
| Beta (false negative) | 0.10 |
| Detection lead time | ~3–4 months before fixed threshold triggers |

## Policy Rationale

Safety bypass incidents are tracked separately from general API abuse because:

1. **Regulatory implications** — EU AI Act GPAI provisions require incident reporting for safety bypass events above materiality threshold
2. **Distinct escalation pattern** — gradual escalation consistent with professional jailbreak operators moving from testing to exploitation (detectable by SPRT, not by threshold triggers)
3. **Different remediation path** — model-level mitigations, not account-level rate limits

The SPRT monitoring protocol runs continuously on this metric. It is specifically designed to detect rate changes that characterize professional jailbreak operators.

## Known Limitations

- Only counts incidents in `fraud_incidents` table — undercounting is likely for sophisticated attacks that never trigger incident creation
- `automated_threshold` detection method has lower recall than `automated_ml` — sophisticated attacks evade threshold rules
- Count without normalization by total API calls is misleading when volume changes; always report alongside [api_abuse_rate](api_abuse_rate.md)
- "Safety bypass" encompasses a wide severity range — always segment by severity for decision-making

## Links

[Analyst Agent](../agents/analyst-agent.md) · [Statistician Agent](../agents/statistician-agent.md) · [attack_vector](../dimensions/attack_vector.md) · `account_tier` · `region` · `time_period` · `fraud_incident` · [api_abuse_rate](api_abuse_rate.md) · `Constraint Register`

---

*Ported from the working Second Brain vault. Content verbatim; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
