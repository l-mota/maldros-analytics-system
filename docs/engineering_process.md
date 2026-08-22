# Engineering process

## The finding

**The governance in this system was not designed once and then trusted — it was repeatedly caught failing by its own audits.** The change log this document summarises contains entries where the subject of the correction is the process itself: a spec that had drifted from the code implementing it, a fix applied correctly but never logged, a session that exceeded its own context budget and skipped its closing obligations. Each was found by a scheduled check rather than by the operator, and each was written down before it was fixed.

**Impact.** A portfolio artifact that only shows working output tells a reviewer nothing about what happens when something breaks, which is the only question that matters for a system meant to run without supervision. The material below is the answer: here is what broke, here is how it was caught, and here is what changed so the same class of failure would be caught earlier next time.

**A note on what you can verify.** Everything in this document is a restatement of entries in the project's internal change log, rewritten for public release. The original log is not published — it contains machine paths, session identifiers, and working notes with no value outside the build. What is published is the substance: what happened, why, what was changed, and how it was validated. Change identifiers from that log are used liberally throughout the codebase — in comments, agent prompts, configuration, and generated artifacts — which is why you will see references like `C-031` in roughly two dozen files. They are commit-style back-references. Nothing in this document depends on them.

---

## How the system was specified

Three documents govern the build, in a fixed authority order:

| Rank | Document | Governs |
|---|---|---|
| 1 | The runtime system prompt | Agent behaviour, operational constraints, the deterministic veto rules, the knowledge-layer specification, governance protocol |
| 2 | The architectural overview | The seven-layer architecture, technology stack, data flow, the agent interaction map, the eleven-step execution lifecycle, operator interface design |
| 3 | The implementation plan | Phase-by-phase deliverables, exit criteria, risk register, dependency map, honest scope assessment |

The visual design system sits outside this ranking as a **peer authority for visual decisions**, non-overridable by the other three on any visual matter.

The ordering exists to answer a specific question: when two documents disagree, which one wins? Without a declared rank, a conflict gets resolved by whichever document the implementer happened to read most recently — which is how specifications quietly diverge from the systems built to satisfy them. The rule adopted here is stricter than "pick the higher-ranked document": **conflicts are surfaced to the operator, never silently resolved.** Where a specification is ambiguous or self-contradictory, the correct action is to stop and ask, not to choose.

One further resolution rule applies when documents disagree with code: **prefer the code.** Documentation is a claim about the system; code is the system. This rule was not theoretical — it decided at least two live disputes during the build, including one where every specification document stated the agent count incorrectly and the directory listing settled it.

---

## The continuity layer

The build was expected from the outset to exceed the context window of any single working session, and was designed around that constraint rather than against it.

Three files carry state between sessions:

- **A persistent memory file** — decisions, rationale, assumptions, constraints, and discoveries. The single mandatory read at the start of every session.
- **A progression tracker** — phase completion, blockers, exit-criteria status, milestones.
- **A change log** — one entry per modification, with a one-line human-scannable summary, rationale, files touched, and validation evidence.

Two rules make the layer load-bearing rather than decorative:

1. **Every session reads the memory file before doing any work, and updates all three files before closing.** A session that skips the close is non-compliant, and the omission is itself logged.
2. **Every log entry opens with a one-line summary before any structured content.** An entry you have to read in full to know whether it is relevant is an entry nobody reads.

The stated design risk is worth quoting directly, because it is the reason the layer exists: *the primary risk is not token limits or session limits — it is architectural drift caused by inadequate context preservation.* Token limits are a budgeting problem. Drift is a correctness problem, and it compounds silently.

A later refinement reduced the mandatory session-start read from all three files to the memory file alone, after the three-file read was measurably accelerating context consumption without improving reconstruction quality. The other two are still written at session end; they are simply not required reading to resume.

---

## Operating directives

Six numbered directives bind every session — the identifiers run to D-8, with two numbers unused. Four of the six shaped the material in this document more than the rest:

- **Fix it and log it.** Any error, omission, or non-compliance found anywhere must be *both* corrected *and* recorded. A finding documented but not fixed is unacceptable; a fix applied but not logged is a continuity failure. This directive is why the log contains entries about the log.
- **Do not deviate from source specifications.** Implementations must faithfully match their specs. Any proposed deviation — including apparent simplifications and "equivalent" approaches — requires explicit authorisation first. Ambiguity gets surfaced, not resolved.
- **Every idea requires explicit approval.** Broader than the runtime Confirmation Gate: it covers build-time decisions such as new files, new patterns, and new abstractions not present in the spec. Describing an idea is permitted; acting on it unilaterally is not.
- **Audit prior phases before starting a new one.** At each phase boundary, all previous deliverables are checked against the specification checklist before any new code is written. Anything incomplete must be finished or formally deferred with written rationale.

---

## Phase gates

The build ran as a strict sequence, each phase a hard prerequisite for the next, with no parallel tracks:

```
Phase 0  Foundation — dataset, semantic layer, knowledge vault, intelligence layer, governance stubs
  └─ Phase 1  First end-to-end investigation
      └─ Phase 2  Self-healing — diagnostic and healing agents
          └─ Phase 3  Experiment analysis and adversarial review
              └─ Phase 4  Self-improving cycle — telemetry, promotion gate, exemplar bank
                  └─ Phase 5  Invention engine
                      └─ Phase 6  Full audit-and-briefing loop
```

Phase 0 alone carried thirteen deliverables and **nine lettered exit criteria, all of which had to be true simultaneously** before Phase 1 could begin.

The criteria are deliberately behavioural rather than declarative. One of the nine reads, in full: *the Cross-Domain Intelligence Layer demonstrates a successful update cycle — an event propagates and appears in a subsequent Capability Bundle.* Two terms in that sentence carry the weight. The **Cross-Domain Intelligence Layer** is an always-on index of reasoning frameworks, disciplinary methods, and cross-domain analogues that every agent must query before acting; an agent that produces output with no recorded query against it is a monitoring failure by definition. A **Capability Bundle** is the first artifact emitted on every task — a snapshot of what that layer could offer for this specific task context, including capabilities that were evaluated and found not to apply, which are logged rather than omitted.

So the criterion is not "the layer is built." It is "prove a change made to the layer shows up downstream in the next task's snapshot." A criterion you can satisfy by asserting it is not a gate.

---

## The change log, rewritten

Seven entries, selected because they show the process working rather than the product succeeding. Identifiers are local to this document.

### E-1 · The deterministic veto blocked draft after draft before it was correct

**Type:** implementation + governance · **Status:** resolved across two rounds

The first full investigation ran end to end in 288.9 seconds, and its output was immediately blocked by the system's own vetoes — correctly in one sense and wrongly in another. The causal-language check flagged the phrase "due to" inside a sentence describing statistical methodology, which is not a causal claim about the data. The citation check reported 10.1% coverage against an 80% threshold, which was not a false positive at all but a real gap in how the model had been instructed to cite.

Round one rewrote the causal check to extract sentence-level context and exempt statistical-methodology sentences, and rewrote the citation instruction with worked correct/wrong/blocked examples. Four further runs surfaced three more false-positive patterns: "due to" appearing in confidence-score explanations; the citation check scanning the model's entire output rather than only the stakeholder-facing section; and dense financial paragraphs where a citation sat inside the string but outside the proximity window used to match it.

Round two added confidence-score vocabulary to the methodology exemption list, rescoped the check to the stakeholder-facing section — so that the check running at generation time inspected exactly the same text the monitoring agent re-inspects afterwards, which it previously had not — and added a string-level fallback so a paragraph containing any source marker counts its claims as cited. **One Phase 1 development run reached 97.2% citation coverage — 104 of 107 claims — with the citation and omission checks clean, and was blocked anyway:** the causal-language veto caught one remaining instance of "due to" and stopped the report from shipping. Clearing two of three vetoes is not a pass. The arc ran further still before a development run cleared all three — the released report, Discovery Report `84c4e728`, at 94.6% coverage and 88 of 93 claims.

The instinct when a correctness check blocks good output is to loosen the check. What happened instead was run after run of narrowing the check's *precision* while leaving its authority untouched — the veto never became advisory, and no output was ever shipped past a failing check. A separate decision made during this work: blocked reports are still written to the artifact store with their violations attached, so failures remain inspectable rather than disappearing.

### E-2 · A design specification was rewritten into five enforcement layers because a document alone could not bind anything

**Type:** governance / infrastructure · **Status:** applied, two layers formally queued

The visual design system had been written as a specification and was, by its author's own assessment at the time, not load-bearing: agents and renderers could still drift from it with nothing to stop them. The remediation installed enforcement at five distinct layers rather than restating the rules more firmly.

A single source of truth for design tokens was created in both Python and CSS form; the chart renderer was refactored to import from it instead of holding inline constants, and the report renderer now reads the CSS at module load and inlines it into its output. The spec was added to the governing document set as a peer authority, with a mandatory read before any visual work. A named file cluster was defined listing the eleven files that must be updated together whenever a visual rule changes, together with an explicit rule that hand-editing a colour token in a consumer file — rather than in the source of truth — is itself a violation. The output readiness checklist was expanded from six criteria to seven, adding a design-conformance check. Finally the design system was registered as a queryable domain in the Cross-Domain Intelligence Layer described above, so an agent producing visual output with no recorded query against the design rules is a detectable monitoring failure.

Two layers were **explicitly deferred rather than quietly dropped**: embedding the chart rules directly into the output agent's prompt so future runs produce conforming titles natively, and a deterministic conformance veto that inspects rendered output for off-palette colours and missing narrative titles. Both are named, scoped, and queued.

### E-3 · An automated conformance audit found sixteen palette violations in an artifact that had been reviewed by eye

**Type:** design-system enforcement · **Status:** applied; one spec conflict escalated

An audit script checking the operator console mockup against the approved colour list found sixteen off-palette six-digit hex codes plus one three-digit shorthand, all of them in status colours that had never been migrated when the palette was consolidated. It also caught a single-character typo in a token value that no visual review would ever have noticed.

All violations were resolved and the artifact re-audited to zero. The instructive part is what happened next: the fix surfaced a genuine conflict between two governing documents — the architecture document specified conventional status colours (red for critical, orange for action, blue for informational), while the consolidated palette permits only four data-meaning colours. Rather than pick one, the entry **applied an interim mapping, documented it in a comment block at the point of change, and escalated the conflict for an explicit decision**, which is what the no-silent-resolution rule requires. The conflict is recorded as still pending.

### E-4 · A compliance audit found thirteen gaps; eleven were closed and two were formally deferred

**Type:** compliance · **Status:** eleven applied, two deferred with rationale

A scheduled audit found thirteen gaps spanning knowledge-vault coverage, missing per-agent prompt files, missing vault-write functions, and one outright bug. Under the fix-it-and-log-it directive all thirteen counted as violations, and the following session executed the remediation.

Three findings are worth naming individually.

**A credential file was present in the working directory.** It was blanked, the credential rotated, and the pattern added to the exclusion rules. It was never in version control — this repository is the first time the project has been placed under git — and it is excluded here by `.gitignore`.

**A filename-collision bug had been silently overwriting knowledge-vault entries.** Vault filenames were derived from a truncated version of the investigation question, so two investigations of the same question produced the same filename and the second overwrote the first. The fix appended a content identifier to every filename; a backfill script then reconstructed what had been lost — seventeen discovery records and seventeen briefing records, the symmetry being an artifact of the two write paths failing together. Nothing had errored, and nothing had alerted.

**A prior deviation was accepted rather than reverted, and the acceptance was logged.** Nineteen vault entries had been written directly rather than through the designated write interface. On inspection the content matched what the interface would have produced, so re-writing them would have changed nothing; the deviation was accepted as compliant and recorded as a deviation anyway. The two remaining gaps — a set of interface notes and a set of later-phase notes — were **formally deferred to a named phase with written rationale**, not dropped.

### E-5 · A documentation-drift pass found five discrepancies; three were fixed and two were refused

**Type:** documentation correction · **Status:** all five ultimately closed

A drift pass compared the continuity documents against what had actually been built. The progression tracker was contradicting itself on the same page: its summary table showed every phase complete while its status diagram, its exit-criteria section, and its indicator table all still described later phases as unbuilt or blocked, and a blocker was still listed open that two later entries confirmed closed. The implementation plan still described an early, smaller version of the foundation phase. A superseded model-version string survived in three documents — and, beyond the intended documentation-only scope, in an active configuration file, where it was a real behavioural discrepancy rather than a stale sentence.

Those were corrected. **Two were deliberately not corrected.** One was a directives table in the implementation plan whose numbering mapped to different definitions than the canonical set — in one case to an almost exactly opposite instruction. The other was a mismatch between the specified asset list for stakeholder briefings and the list actually implemented, differing in both count and field names, where several specified concepts had no shipped equivalent and several shipped fields were unnamed in the spec. Neither is a stale-fact correction; both are questions about which version is authoritative and what the divergence means. **Both were surfaced for explicit decision rather than resolved by whoever happened to notice them**, and both were closed by later entries.

**Root cause, recorded honestly:** the drift was discovered while sourcing facts for an unrelated document under a read-the-source-first discipline. That discipline was designed to catch exactly this, and it did — but it means the drift had been sitting undetected in the continuity layer until an outside task went looking.

### E-6 · A correct fix was logged as a violation because it had not been logged

**Type:** retroactive log entry · **Status:** closed, logging only

One of the two items escalated in E-5 — the mismatched briefing asset list — was corrected in a later working session. The correction was verified by direct read: the **runtime system prompt** now matches the implemented schema exactly, in the same order, with the previously unnamed fields explicitly present and the concepts with no shipped equivalent removed.

The fix was correct as far as it went. **It was also a violation**, because it was made without a change-log entry or a memory-file update, and the governing directive is explicit that a correction applied but not logged is a continuity failure in its own right. The entry exists to close that gap retroactively; the root cause is recorded as *the correcting session did not complete its logging obligation before ending.*

An engineering log that only records successes is a marketing document.

> **This entry had a third instance of the same drift, found while preparing this repository for publication.** The correction above reconciled the runtime system prompt with the implementation. It did **not** reach the JSON schema at [`artifacts/schemas/aims_mode_b.schema.json`](../artifacts/schemas/aims_mode_b.schema.json), which was still the pre-expansion Phase-0 standard: fifteen required assets, under field names largely disjoint from the eighteen the shipped agent emits, modelled as direct children of `content` rather than as members of `content.assets`. Neither shipped example validated against it. It is the same class of drift as E-5, surviving in the one place the E-5 pass did not look — and it had already survived one correction pass that fixed its sibling.
>
> **It has been corrected.** The schema was rebuilt against `AIMS_MODE_B_REQUIRED_ASSETS` in the agent source and against the shipped artifacts, and carries a `$comment` recording what was wrong and why. The schema is now deliberately strict about asset *presence* and permissive about asset *internals*, which matches what the omission audit actually enforces rather than what a Phase-0 draft guessed it would.
>
> Leaving it broken and merely labelled was considered and rejected. The governing directive is *fix it and log it*, and it names the failure mode explicitly: a finding documented but not corrected is not acceptable. Disclosing a known-broken artifact while declining to repair it would have violated the rule this document cites as binding — and would have been a strange way to argue that the rule is binding. The drift is recorded here; the artifact is fixed. Both, not either.

### E-7 · A session exceeded its own context budget and skipped its closing obligations — logged against itself

**Type:** process violation · **Status:** recovered in the following session

A working session filled its context and was automatically compacted before its closing tasks — the memory update, the progression update, the change-log entry, and the handover message — had been written. The governing protocol requires the operator to be warned *proactively* as context load grows, specifically so this cannot happen. No warning was issued.

The consequence was bounded: one session's closing documentation was missing, and it was reconstructed in the following session. The remediation was to reinstate context monitoring as a per-task obligation, flagging heavy load regardless of the cost of interrupting work in progress.

The same entry also records the substantive work of that session — a briefing generated for an experiment analysis, which passed on its sixth attempt and required seven targeted compatibility fixes to the output agent to handle a new class of input. **Both halves are in the same entry**: what was built, and the process failure that occurred while building it.

---

## What this process cost

- **It is slow.** Eighteen development runs, fourteen of them blocked, to get one report past its own checks. Two sessions to close thirteen audit findings. A phase boundary that cannot be crossed until nine separate criteria are simultaneously true. For a single-operator build with no delivery deadline this is affordable; on a shipping schedule it would need renegotiating, and the honest answer is which gates would be relaxed rather than a claim that none would.
- **The continuity layer consumes real budget.** Reading three state files at the start of every session measurably accelerated context consumption, which is why the mandatory read was cut to one. The overhead is not free and was not free here.
- **Rigour concentrated where it was cheapest to apply.** The governance, artifact, and design-system layers are heavily enforced because enforcement there is mechanical — a hex code either is or is not in the approved list. Judgement-bound areas have thinner enforcement, and the design compensates with an explicit rule that judgement-bound checks may not gate phase transitions or trigger the approval gate.
- **The audits found real problems, which means comparable problems probably remain.** Every audit described above found something. The reasonable inference is not that the system is now clean but that the next audit would also find something.

---

## Recommendation

If you are evaluating this repository as evidence of engineering practice, the load-bearing question is not whether the governance is well-designed on paper — you can read that in the specification. It is whether the governance ever actually stopped anything. Three artifacts answer that directly, and all three are in this repository:

1. [`artifacts/examples/aims_mode_b_blocked.example.json`](../artifacts/examples/aims_mode_b_blocked.example.json) — a complete briefing, all eighteen assets present, killed by one failed check.
2. [`governance/confirmation_gate/confirmation_gate.py`](../governance/confirmation_gate/confirmation_gate.py) — the approval gate, whose submission path contains no approval branch at all.
3. [`agents/storyteller/storyteller.py`](../agents/storyteller/storyteller.py) — the three vetoes described in E-1, and the decision to persist blocked output rather than discard it.

Read those before the specification, not after. If they do not hold up, nothing above matters.

---

<sub>This document summarises an internal change log that is not published. Every claim restates a logged entry. The system it describes is design-complete and validated via simulation against a synthetic dataset; it is not production-deployed.</sub>
