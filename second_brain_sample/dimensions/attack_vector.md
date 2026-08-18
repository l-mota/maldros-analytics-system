# attack_vector

> **Summary:** Primary analytical segmentation dimension. Five values: api_abuse, safety_bypass, platform_fraud, downstream_harm, data_poisoning. Every FIA metric can be sliced by attack_vector.

---

**Source:** `semantic_layer/dimensions/attack_vector.yaml`
**Type:** categorical
**Grain:** per-event / per-incident
**Version:** 1.0.0

---

## Definition

The category of fraud or abuse attack. Primary analytical segmentation dimension for all Financial Impact Analysis metrics. Maps directly to FIA §1.1–1.6 attack vector taxonomy.

## Values

| Value | Label | Description | Detection Lead Time | Severity Distribution |
|-------|-------|-------------|--------------------|-----------------------|
| `api_abuse` | API Abuse | Unauthorized or exploitative API use: token theft, key sharing, proxy services, high-volume scraping, cost fraud. Vectors 1–2 in FIA §1.1–1.2. | 1–7 days | low:30% / medium:40% / high:20% / critical:10% |
| `safety_bypass` | Safety Bypass | Deliberate circumvention of safety guardrails: jailbreaks, prompt injection, system prompt extraction, adversarial inputs. Escalates gradually — SPRT-detectable. Vector 3 §1.3. | 3–30 days | low:10% / medium:35% / high:40% / critical:15% |
| `platform_fraud` | Platform Fraud | Financial fraud through or against the platform: fraudulent account creation, payment fraud, subscription abuse, referral fraud, credit-back schemes. Vector 4 §1.4. | 7–60 days | low:15% / medium:30% / high:35% / critical:20% |
| `downstream_harm` | Downstream Harm | Harm caused to third parties by AI-generated content: misinformation, harassment, harmful content at scale. Hardest to quantify. Vector 5 §1.5. | 14–90 days | low:20% / medium:30% / high:35% / critical:15% |
| `data_poisoning` | Data Poisoning | Intentional manipulation of training data or fine-tuning inputs: degrading model quality, injecting backdoors, exfiltrating model parameters. Requires privileged access; low volume, very high severity. Vector 6 §1.6. | 30–180 days | low:10% / medium:30% / high:40% / critical:20% |

## Tables

| Table | Field | Join Type |
|-------|-------|-----------|
| `fraud_incidents` | `attack_vector` | direct field |
| `financial_impact` | `attack_vector` | direct field |
| `api_events` | inferred via `content_category` → mapping | indirect |
| `regulatory_events` | `related_attack_vector` | direct field (nullable) |

## Applicable Metrics

[api_abuse_rate](../metrics/api_abuse_rate.md) · `fraud_loss_direct` · `account_takeover_volume` · [safety_bypass_incidents](../metrics/safety_bypass_incidents.md) · `downstream_harm_exposure` · `compliance_cost_per_incident`

## Phase 1 Usage

The Phase 1 investigation focused on `api_abuse` vector. Key finding: 41 clustered accounts responsible for 25.87% of Q1 api_abuse events. No Q1-specific volumetric spike. See `Discovery — Is the spike in API abuse volume in Q1 of the synthetic data — Phase`.

## Links

[Analyst Agent](../agents/analyst-agent.md) · `fraud_incident` · `api_account` · `region` · `time_period` · `Constraint Register`

---

*Ported from the working Second Brain vault. Content verbatim; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
