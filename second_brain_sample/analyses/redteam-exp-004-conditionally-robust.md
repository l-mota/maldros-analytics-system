# RedTeam — EXP-004 — Conditionally Robust — 89ff0e23

> **Summary:** Phase 3 Red-Team — EXP-004 — verdict: Conditionally Robust — primary weakness: safety_bypass_incidents measures DETECTED incidents, not actual bypass occurrence — treatment may alter detection/reporting rather than true bypass behavior, and subgroup data is unavailable to confirm uniform effect direction (E5). — PDS: 6.20

---

**Source artifact:** `89ff0e23-c4ec-4c3e-813c-9d91e915bfc9`
**Producing agent:** red_team
**Phase:** 3
**Timestamp:** 2026-06-19T02:07:49.446429+00:00
**Content hash:** `309900fbbe92a33308f06e64db4b9e35d0e8c49b597a56cef8f51bc41958bc07`
**Relevance:** Red-Team E1–E12 evaluation of EXP-004: Conditionally Robust — primary weakness safety_bypass_incidents measures DETECTED incidents, not actual bypass occurrence — treatment may alter detection/reporting rather than true bypass behavior, and subgroup data is unavailable to confirm uniform effect direction (E5). — hardening required before ship

---

## Verdict Summary

**Experiment:** `EXP-004`
**Overall verdict:** Conditionally Robust
**Primary weakness:** safety_bypass_incidents measures DETECTED incidents, not actual bypass occurrence — treatment may alter detection/reporting rather than true bypass behavior, and subgroup data is unavailable to confirm uniform effect direction (E5).
**Penetration difficulty score:** 6.20 (0=trivially broken, 1=fully robust)
**Verdict rationale:** EXP-004 is statistically sound: clean SRM (deviation 0.0004), adequate retrospective power (0.854), and a significant effect (p=0.00484, CI excludes zero). However, the metric 'safety_bypass_incidents' is a count of detected/reported events, which is inherently sensitive to detection-rate confounding and reporting behavior changes. The most serious unresolved issue is E5: subgroup assignment logs are unavailable, so segment heterogeneity cannot be ruled out — a 9.5% average reduction in safety bypass incidents could mask a region/tier where bypass incidents INCREASED. No single category presents a concrete TRIVIAL/LOW-effort attack path that would invalidate the design, so the worst-case is Conditionally Robust driven by E5 (unverifiable) and E1/E12 (detection-vs-occurrence seam).

## Deterministic Pre-screens (L1-enforced)

None fired.

## E1–E12 Adversarial Assessments

- **E1** (MEDIUM effort): Conditionally Robust — safety_bypass_incidents counts DETECTED/REPORTED bypass events. A treatment that reduces the visibility or logging of by
- **E2** (MEDIUM effort): Conditionally Robust — If users who trigger safety bypasses churn, get banned, or drop out at different rates between arms, the surviving measu
- **E3** (MEDIUM effort): Conditionally Robust — Randomization with clean SRM (deviation 0.0004, p=0.96) makes classical confounding unlikely. Residual risk: if the trea
- **E4** (MEDIUM effort): Conditionally Robust — The 3-week window (Apr 15 – May 6) is short. Formal time-decay regression could not be run (daily assignment data absent
- **E5** (MEDIUM effort): Conditionally Robust — Pre-screen confirms subgroup assignment logs are UNAVAILABLE. The 9.5% average effect (CI 5.7%–13.4%) could be composed
- **E6** (MEDIUM effort): Robust — No explicit KPI threshold or gating boundary is documented in this experiment. Without a known decision threshold tied t
- **E7** (MEDIUM effort): Conditionally Robust — Bypass tactics evolve adversarially. A safety treatment effective against the bypass patterns present in April 2024 may
- **E8** (MEDIUM effort): Conditionally Robust — Multiple formal tests (time-decay, SPRT) could not be run because daily/subgroup data is absent from the experiments tab
- **E9** (MEDIUM effort): Conditionally Robust — Peeking risk was assessed LOW only via observable proxies; proper SPRT could not be run (no daily time series). The effe
- **E10** (MEDIUM effort): Conditionally Robust — The business question is presumably 'are users actually bypassing safety controls?' while the metric is 'incidents count
- **E11** (MEDIUM effort): Conditionally Robust — Safety bypass is an adversarial domain: the population being measured includes actors actively trying to defeat the cont
- **E12** (MEDIUM effort): Conditionally Robust — The captured data is 'detected/reported incidents'; the actual question is 'did real safety bypasses decrease.' The seam

> **On the truncated lines above.** Each E-category summary is cut off mid-sentence in the source vault entry — the writer truncates the per-category rationale to a fixed width. They are reproduced exactly as stored rather than reconstructed from the underlying artifact, because this file documents what the knowledge layer actually retained, not what it could have retained. The truncation is a real defect in the vault writer and is recorded as such.

## Hardening Steps (priority order)

- Obtain subgroup assignment logs (tier/region) and re-run the effect estimate per segment to confirm the direction of effect is consistent and no subpopulation shows increased bypass incidents.
- Validate that the metric counts ACTUAL bypass attempts (via independent ground-truth audit or red-team injection) rather than only detected/reported incidents, to separate detection-rate effects from true behavioral effects.
- Cross-check whether the treatment changes incident detectability (e.g., suppresses logging or reclassifies events) — confirm detection instrumentation is identical across arms.
- Add a pre-registered analysis plan retroactively documented to confirm the metric, stopping rule, and segments were fixed before analysis given peeking risk could not be formally tested (SPRT data absent).
- Run a holdout/replication window post-2024-05-06 to confirm the effect persists and is not a novelty artifact, since formal time-decay regression could not be performed.

## Known Limitations

- E5 severity is genuinely UNKNOWN — subgroup logs unavailable means segment heterogeneity could not be tested; this is a blocking gap for a safety metric, not a cleared category.
- Formal time-decay (E4) and SPRT peeking (E9) tests could not be executed due to absent daily time-series data; assessments rely on proxies.
- No ground-truth audit exists to separate true bypass reduction from detection/reporting-rate effects (E1/E12).
- Effect size (0.0954) is only marginally above MDE (0.0887), making the result statistically borderline and sensitive to stopping/sampling decisions.
- Red-Team self-assessment: no category was rated Brittle because no specific TRIVIAL/LOW-effort actor-driven attack path against THIS design could be articulated; the dominant risks (E1, E5, E12) are structural seams and unverifiable gaps appropriately rated Conditionally Robust.

## Artifact Lineage

- Red-team report: `89ff0e23-c4ec-4c3e-813c-9d91e915bfc9`
- Provenance: ['eb85004c-6d35-4372-b146-01cfb9d144c2']

## Links

[Red-Team Agent](../agents/red-team-agent.md) · [Statistician Agent](../agents/statistician-agent.md) · `CDI Layer` · `AIMS Mode B` · [Confirmation Gate](../governance/confirmation-gate.md)

---

*Ported from the working Second Brain vault. Content verbatim, including the truncated E1–E12 lines; `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
