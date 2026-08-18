# Confirmation Gate

> **Summary:** The human authorization checkpoint for consequential system actions. Permanently locked: no auto-approve under any condition — not on timeout, not on operator absence. Silence ≠ approval.

---

**Source:** `analytics_engineering_system_prompt.md` · [`governance/confirmation_gate.py`](../../governance/confirmation_gate/confirmation_gate.py)
**Type:** Governance / Human-in-the-Loop
**Auto-approve:** Never — permanently locked
**Phase introduced:** Phase 0 (stub), Phase 2 (full implementation)

---

## Definition

The Confirmation Gate is the mandatory human authorization checkpoint for every consequential action in the Maldros system. It sits between a proposed consequential action and its execution. No action can proceed without explicit operator approval.

**Governance Rule 2 (permanently locked):** Every consequential action requires explicit operator authorization. No auto-approve on timeout, not on operator absence, not under any Phase 7 Authorized proposal. Silence ≠ approval. This rule is permanently locked and cannot be overridden.

## Triggering Conditions (7)

1. Analyst conclusion of material significance (above materiality threshold)
2. Statistical verdict with high financial implication (>$500K estimated impact)
3. Storyteller output classified as AIMS Mode B (novel finding, first-principles invention)
4. Healing Agent proposes a remediation that modifies production pipeline logic
5. Red-Team Agent returns a Brittle verdict on a system component
6. Phase transition proposal (system requests transition to next phase)
7. Any L3+ escalation from Diagnostic Agent

## Workflow

```
Triggering condition fires
  → Item enters Review Queue
  → HIGH notification sent to operator
  → Operator reviews (no time limit — no auto-approve)
  → Operator decision: APPROVED | REJECTED | REQUEST_MORE_INFO
  → Decision logged to AIMS Mode A
  → If APPROVED: action proceeds
  → If REJECTED: rationale logged, item archived
  → If REQUEST_MORE_INFO: item held pending additional analysis
```

## What Is Gated

- AIMS Mode B delivery (requires sign-off before action)
- Any production pipeline modification
- Phase transition
- Any healing action that modifies production logic
- Any Red-Team-flagged Brittle component being deployed
- Material findings above the $500K materiality threshold

## What Is NOT Gated

- AIMS Mode A log entries (auto-logged, no gate)
- Routine L1–L2 pipeline self-heals (below materiality threshold)
- Routine telemetry exemplar promotions with Robust verdict
- CDI Layer update cycles

## Phase 0 Status

Confirmation Gate stub implemented and confirmed operational (Phase 0 exit criterion h). Tested: item enters queue, `no_auto_approve=True` hardcoded, `requires_explicit_operator_decision=True`, operator decision logged to AIMS Mode A.

## Current Queue Item

AIMS Mode B `f3d5a232` is READY_FOR_REVIEW — awaiting operator Confirmation Gate sign-off. `AIMS Mode B — Phase 1 — f3d5a232`

> **This line is the point of the whole sample.** The queue item is still sitting there. It is not a stale record left over from a demo — it is a briefing the system produced, classified as consequential, and then refused to release on its own authority. The gate is the one place in the end-to-end run where a human is structurally required, and it did what it was built to do: it stopped.

## Links

`Review Queue` · `AIMS Mode B` · `AIMS Mode A` · `Storyteller Agent` · `Diagnostic Agent` · `Healing Agent` · `Design Invariants` · `Phase 0 — Foundation` · [RedTeam — EXP-004 — Conditionally Robust](../analyses/redteam-exp-004-conditionally-robust.md)

---

*Ported from the working Second Brain vault. Content verbatim except the highlighted commentary block, which is written for this sample and marked as such; the **Source** line had an operator-local path prefix removed and now points at the shipped implementation in this repository. `[[wikilinks]]` converted to relative markdown links, and references to notes outside this sample rendered as `code` so no link 404s. See [the sample index](../README.md) for the full porting rules.*
