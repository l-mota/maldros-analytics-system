"""
lib/research_loop.py
Phase 4 — Automated AI Research Loop (Deliverable 4.5)

A closed research loop triggered by open Constraint Register entries.

  trigger      → open Constraint Register entry (or operator-supplied question)
  formulation  → research question + abductive hypothesis framing
  retrieval    → external evidence acquisition (web search; injectable provider)
  hypothesis   → 2–3 candidate hypotheses (Phase 5 abbreviated reasoning modes)
  artifact     → discovery_report + vault entry under discoveries/
  intel        → vault entry under external_intel/ for retrieved evidence

Phase 4 scope: the loop runs in the dev harness, not at production agent
runtime. The external retrieval interface is pluggable — the caller injects
a `web_search` callable. A `_StubSearch` implementation is provided so the
loop is end-to-end testable without network access.

Phase 5 upgrade: the abbreviated reasoning here is replaced by The Forge's
full seven-mode generation pipeline.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater
from lib.artifact import create_artifact, write_artifact
from lib.second_brain import write_vault_entry, _safe_filename, _file_hash, _now_iso

AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
VAULT = BASE / "Maldros 2.0 Brain"


# ── pluggable web search interface ───────────────────────────────────────────

class _StubSearch:
    """
    Deterministic stub for the web-search dependency.

    Returns 2 synthetic search hits derived from the query, each carrying a
    plausible source attribution. Used for offline testing of the research
    loop. Replace with a real Claude Code web-search adapter when running
    in the dev harness.
    """

    def __call__(self, query: str, limit: int = 3) -> list[dict]:
        seed = sum(ord(c) for c in query) % 1000
        return [
            {
                "title": f"External finding {i + 1} relating to: {query[:60]}",
                "url": f"https://stub.local/research/{seed}-{i}",
                "snippet": (
                    f"Synthetic evidence #{i + 1} for the question '{query[:60]}...'. "
                    f"Phase 4 stub: replace with Claude Code WebSearch adapter."
                ),
                "source_type": "stub_external",
                "retrieved_at": _now_iso(),
            }
            for i in range(min(limit, 2))
        ]


def _log_to_aims_mode_a(event_type: str, payload: dict) -> None:
    AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": _now_iso(),
        "event_type": event_type,
        "payload": payload,
    }
    log_file = AIMS_MODE_A_DIR / "research_loop_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── research loop ────────────────────────────────────────────────────────────

class ResearchLoop:
    """
    Phase 4 Automated AI Research Loop.

    Usage:
        loop = ResearchLoop()
        report = loop.run_for_constraint(constraint_id="CR-006")
        # or
        report = loop.run_for_question("Why do small clusters evade rate monitors?")
    """

    def __init__(self, web_search: Optional[Callable] = None):
        self.web_search = web_search or _StubSearch()

    # ─── triggers ────────────────────────────────────────────────────────────

    def run_for_constraint(self, constraint_id: str) -> dict:
        """Run the loop against a specific open Constraint Register entry."""
        reader = CDIReader(agent_name="research_loop", task_id=constraint_id)
        constraints = reader.get_open_constraints()
        target = next(
            (c for c in constraints if c.get("constraint_id") == constraint_id
             or c.get("id") == constraint_id),
            None,
        )
        if not target:
            raise ValueError(f"Constraint {constraint_id} not found in open register")
        question = self._formulate_question(target)
        return self._execute(question, source_constraint=target)

    def run_for_question(self, question: str, source_constraint: Optional[dict] = None) -> dict:
        return self._execute(question, source_constraint=source_constraint)

    # ─── steps ───────────────────────────────────────────────────────────────

    def _formulate_question(self, constraint: dict) -> str:
        desc = constraint.get("description", constraint.get("summary", constraint.get("title", "")))
        cid = constraint.get("constraint_id", constraint.get("id", "CR-?"))
        return (
            f"What evidence in the broader literature or industry practice "
            f"addresses constraint {cid}: '{desc}'?"
        )

    def _abductive_framing(self, question: str) -> str:
        return (
            "Abductive framing: among the simplest generative processes that "
            "would produce the observed gap in our coverage of this question, "
            "which is best supported by external evidence?"
        )

    def _generate_hypotheses(self, question: str, evidence: list[dict]) -> list[dict]:
        """
        Phase 4 abbreviated mode: produce 2–3 candidate hypotheses from the
        question and the retrieved evidence using deterministic templates.
        Phase 5 replaces this with The Forge's full reasoning-mode pipeline.
        """
        snippets = " | ".join(e.get("snippet", "")[:120] for e in evidence[:3])
        return [
            {
                "id": "H1-abductive",
                "mode": "abductive",
                "statement": (
                    f"H1 (abductive): the simplest mechanism producing the observed "
                    f"gap in '{question[:80]}' is a structural seam between the "
                    f"measurement layer and the entity layer. Evidence pointers: {snippets[:200]}."
                ),
                "supporting_evidence_ids": [e.get("url") for e in evidence[:2]],
                "falsifiability": (
                    "Predicts that explicit cross-layer joins will recover the "
                    "missed signal; refuted if joins produce no signal lift."
                ),
            },
            {
                "id": "H2-analogy",
                "mode": "cross_domain_analogy",
                "statement": (
                    f"H2 (cross-domain analogy): an analogous failure in network "
                    f"epidemiology suggests the gap reflects an undetected "
                    f"low-prevalence superspreader subpopulation rather than a "
                    f"broad-base shift. Evidence pointers: {snippets[200:400]}."
                ),
                "supporting_evidence_ids": [e.get("url") for e in evidence[1:3]],
                "falsifiability": (
                    "Predicts a fat-tail distribution in per-entity contribution; "
                    "refuted if the distribution is heavy-shoulder rather than "
                    "fat-tail."
                ),
            },
            {
                "id": "H3-counter",
                "mode": "counterfactual",
                "statement": (
                    "H3 (counterfactual): had the previous quarter's monitoring "
                    "thresholds been left in place, the population-level signal "
                    "would have correctly flagged the cohort — implying the "
                    "calibration drift is the load-bearing cause, not the "
                    "underlying behavior."
                ),
                "supporting_evidence_ids": [],
                "falsifiability": (
                    "Predicts a measurable drift in monitor calibration over the "
                    "preceding window; refuted if calibration was stable across "
                    "the period."
                ),
            },
        ]

    def _execute(self, question: str, source_constraint: Optional[dict] = None) -> dict:
        cid = (
            source_constraint.get("constraint_id", source_constraint.get("id", "CR-OPEN"))
            if source_constraint else "OPERATOR-QUESTION"
        )
        task_id = str(uuid.uuid4())
        print(f"\n[ResearchLoop] task={task_id[:8]} | trigger={cid}")
        print(f"  Question: {question[:120]}")

        # 1) Abductive framing
        framing = self._abductive_framing(question)

        # 2) External evidence retrieval
        evidence = self.web_search(question, limit=3)
        print(f"  Retrieved {len(evidence)} evidence hit(s)")

        # 3) Hypothesis generation
        hypotheses = self._generate_hypotheses(question, evidence)
        print(f"  Generated {len(hypotheses)} candidate hypotheses")

        # 4) Discovery Report artifact
        report_content = {
            "task_id": task_id,
            "source_constraint_id": cid,
            "research_question": question,
            "abductive_framing": framing,
            "external_evidence": evidence,
            "hypotheses": hypotheses,
            "next_step": (
                "Hand to Analyst for pre-validation; promote to investigation "
                "queue if any hypothesis survives statistical pre-screen."
            ),
            "phase4_scope_note": (
                "Phase 4 abbreviated reasoning. Phase 5 replaces hypothesis "
                "generation with The Forge's full reasoning-mode pipeline and "
                "the external_evidence list with Red-Team-stress-tested retrieval."
            ),
        }
        report = create_artifact(
            artifact_type="discovery_report",
            producing_agent="orchestrator",
            phase=4,
            content=report_content,
            provenance=[],
            confidence_score=0.5,
            known_limitations=[
                "Phase 4 abbreviated reasoning (only 3 modes — abductive, analogical, counterfactual)",
                "External retrieval is stub-backed unless production WebSearch adapter is injected",
                "Hypotheses have not been Red-Team-stress-tested at this stage",
            ],
        )
        write_artifact(report)

        # 5) Vault entries
        self._write_discovery_vault_entry(report, cid)
        for i, e in enumerate(evidence):
            self._write_external_intel_entry(e, question, cid, idx=i)

        # 6) AIMS Mode A
        _log_to_aims_mode_a("RESEARCH_LOOP_RUN", {
            "task_id": task_id,
            "trigger_constraint": cid,
            "question": question[:300],
            "evidence_count": len(evidence),
            "hypothesis_count": len(hypotheses),
            "discovery_report_id": report["artifact_id"],
        })

        # 7) CDI Layer external_knowledge update
        try:
            updater = CDIUpdater(agent_name="research_loop", task_id=task_id)
            for e in evidence:
                updater.add_external_knowledge({
                    "id": str(uuid.uuid4()),
                    "topic": question[:80],
                    "source": e.get("url"),
                    "retrieval_date": e.get("retrieved_at", _now_iso()),
                    "summary": e.get("snippet", "")[:300],
                    "relevance_to_constraints": [cid],
                })
        except Exception as err:
            print(f"  [Warning] CDI external_knowledge update failed: {err}")

        return {
            "task_id": task_id,
            "constraint_id": cid,
            "research_question": question,
            "discovery_report_id": report["artifact_id"],
            "evidence_count": len(evidence),
            "hypothesis_count": len(hypotheses),
            "hypotheses": hypotheses,
        }

    # ─── vault writes ────────────────────────────────────────────────────────

    def _write_discovery_vault_entry(self, report: dict, constraint_id: str) -> Path:
        c = report["content"]
        question = c.get("research_question", "")
        cid_short = report["artifact_id"][:8]
        filename = _safe_filename(
            f"Research Loop — {constraint_id} — {question[:60]} — {cid_short}",
            max_len=120,
        )
        summary = (
            f"Phase 4 research loop for {constraint_id} — "
            f"{c.get('evidence_count', len(c.get('external_evidence', [])))} evidence; "
            f"{len(c.get('hypotheses', []))} hypotheses"
        )
        hyp_lines = []
        for h in c.get("hypotheses", []):
            hyp_lines.append(
                f"### {h.get('id', '?')} — mode: {h.get('mode', '?')}\n\n"
                f"{h.get('statement', '')}\n\n"
                f"**Falsifiability:** {h.get('falsifiability', '')}"
            )
        evidence_lines = [
            f"- [{e.get('title', '?')}]({e.get('url', '?')}) — {e.get('source_type', '?')}"
            for e in c.get("external_evidence", [])
        ]
        sections = {
            "Research Question": question,
            "Abductive Framing": c.get("abductive_framing", ""),
            "External Evidence": "\n".join(evidence_lines) or "(none retrieved)",
            "Candidate Hypotheses": "\n\n".join(hyp_lines) or "(none generated)",
            "Next Step": c.get("next_step", ""),
            "Phase 4 Scope Note": c.get("phase4_scope_note", ""),
        }
        wikilinks = [
            "Research Loop",
            "Constraint Register",
            "CDI Layer",
            "external_knowledge",
            "AIMS Mode A",
            constraint_id,
        ]
        return write_vault_entry(
            subfolder="discoveries",
            filename=filename,
            summary=summary,
            sections=sections,
            wikilinks=wikilinks,
            source_artifact_id=report["artifact_id"],
            content_hash=report.get("content_hash", _file_hash(report["artifact_id"])),
            producing_agent="orchestrator",
            timestamp_utc=report.get("timestamp_utc", _now_iso()),
            phase=4,
            relevance_rationale=(
                f"Automated AI research loop triggered by open Constraint "
                f"Register entry {constraint_id}; outputs candidate hypotheses "
                f"for Analyst pre-validation."
            ),
        )

    def _write_external_intel_entry(self, evidence: dict, question: str,
                                     constraint_id: str, idx: int = 0) -> Path:
        title = evidence.get("title", f"Evidence {idx}")
        url = evidence.get("url", "")
        filename = _safe_filename(
            f"ExtIntel — {constraint_id} — {title[:50]} — {idx:02d}",
            max_len=120,
        )
        summary = f"External evidence for {constraint_id}: {title[:80]}"
        sections = {
            "Source": f"- **URL:** {url}\n- **Type:** {evidence.get('source_type', '?')}\n- **Retrieved:** {evidence.get('retrieved_at', '?')}",
            "Snippet": evidence.get("snippet", ""),
            "Surfacing Query": question,
            "Relevance": (
                f"Retrieved by the Phase 4 automated research loop while "
                f"investigating {constraint_id}. Cross-source corroboration "
                f"required before any claim is treated as load-bearing."
            ),
        }
        wikilinks = [
            "Research Loop",
            "external_knowledge",
            constraint_id,
            "Constraint Register",
        ]
        return write_vault_entry(
            subfolder="external_intel",
            filename=filename,
            summary=summary,
            sections=sections,
            wikilinks=wikilinks,
            source_artifact_id=url,
            content_hash=_file_hash(url + title),
            producing_agent="orchestrator",
            timestamp_utc=evidence.get("retrieved_at", _now_iso()),
            phase=4,
            relevance_rationale=(
                f"External evidence surfaced for constraint {constraint_id}; "
                f"awaits cross-source corroboration before load-bearing use."
            ),
        )
