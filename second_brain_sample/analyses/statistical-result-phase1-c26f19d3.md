# Statistical Result — CONDITIONALLY_VALIDATED — Phase 1 — c26f19d3

> **Summary:** Phase 1 statistical validation — verdict: CONDITIONALLY_VALIDATED

---

**Source artifact:** `c26f19d3-d516-4600-9c24-8eff8a46ad03`
**Producing agent:** statistician
**Phase:** 1
**Timestamp:** 2026-06-10T00:08:55.190490+00:00
**Content hash:** `e16a84a53a50dae40cb1f61fd91a706234a20ff14f9b5ba9b0193307bdeb2b39`
**Relevance:** Statistical validation of analyst conclusion — verdict: CONDITIONALLY_VALIDATED

---

## Statistical Verdict

**CONDITIONALLY_VALIDATED**

The evidence presents a split picture. The cluster-level analysis (Chi-square) strongly supports the existence of a coordinated abuse subgroup: 41 accounts behaving as a co-temporal cluster are massively overrepresented in Q1 api_abuse incidents (rate ratio 16.54×). However, the population-level tests either contradict or fail to support the 'COORDINATED_ABUSE' conclusion. The z-test for proportions shows Q1 abuse rate is actually *lower* than non-Q1, directly contradicting a Q1-wide abuse spike. The Gini coefficient (0.026) is far below the 0.3 threshold, indicating abuse is temporally uniform rather than concentrated in bursts — inconsistent with coordinated campaign timing. The KS test is non-significant after Bonferroni correction and underpowered. The analyst's conclusion of COORDINATED_ABUSE is partially supported: there is strong evidence of a small coordinated cluster (41 accounts), but no evidence that this coordination produces a detectable population-level Q1 anomaly. The coordination appears real but contained to a small actor group.

## Tests Run

- **Two-sample z-test for proportions (Q1 vs non-Q1 abuse rate)**: stat=-5.5983, p=0.0, effect=-0.0175
- **Chi-square test (cluster vs non-cluster incident overrepresentation)**: stat=97.6105, p=0.0, effect=1.67
- **Gini coefficient — temporal concentration of Q1 abuse volume**: stat=0.0259, p=nan, effect=0.0259
- **KS two-sample test (Q1 vs non-Q1 monthly abuse distribution)**: stat=0.7333, p=0.085784, effect=0.7333

## Known Limitations

- Cramér's V = 1.67 is mathematically impossible (bounded [0,1] for 2×2 tables) — the Chi-square effect size must be recomputed before the cluster test can be fully credited.
- Potential circularity: if the 41-account cluster was identified via co-temporal abuse graph analysis on Q1 data, testing whether these accounts are overrepresented in Q1 abuse is tautological.
- Temporal analysis uses monthly granularity (N=18 bins), which cannot detect sub-monthly coordination patterns (e.g., same-hour bursts). Coordination might exist at finer timescales not captured by these tests.
- The z-test is overpowered (N=750K) and detects a trivial effect in the opposite direction — this should not be over-interpreted but does rule out any meaningful Q1 abuse rate elevation.
- No confidence intervals provided for the Chi-square test or KS test, limiting precision assessment for those results.
- The 'COORDINATED_ABUSE' label conflates two distinct claims: (a) a small cluster exists with suspicious behavior, and (b) Q1 exhibits systemically elevated coordinated abuse. Evidence supports (a) weakly with caveats; evidence contradicts (b).
- Selection bias in cluster identification methodology is not addressed — how many potential clusters were screened before this 41-account group was surfaced?

## Artifact Lineage

- Statistical Result: `c26f19d3-d516-4600-9c24-8eff8a46ad03`
- Parent Evidence Bundle: `1bcf87a6-1f55-4cd9-9f13-4a78aa7f3b10`
- Vault analysis entry: `analyses/Analysis — Is the spike in API abuse volume in Q1 of the synthetic data — Phase .md`

## Links

[Analysis — Is the spike in API abuse volume in Q1 of the synthetic data — Phase](q1-api-abuse-investigation.md) · [Statistician Agent](../agents/statistician-agent.md) · [Analyst Agent](../agents/analyst-agent.md)

---

*Ported from the working Second Brain vault. Content verbatim with one edit: the "Vault analysis entry" line carried an operator-local absolute path, replaced here with the vault-relative path. `[[wikilinks]]` converted to relative markdown links. See [the sample index](../README.md) for the full porting rules.*

**Why this note is worth reading twice.** It is the Statistician Agent contradicting the Analyst Agent on the record, in the permanent artifact, without a human prompting it to — and then flagging that its own Chi-square effect size (Cramér's V = 1.67) is mathematically impossible. A system that only wrote down its wins would not contain this file.
