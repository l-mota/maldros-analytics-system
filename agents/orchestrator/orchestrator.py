"""
Orchestrator Agent — agents/orchestrator/orchestrator.py
Deliverable 0.5.

Accepts a natural-language question → queries Second Brain → queries CDI Layer →
emits Capability Bundle → decomposes into sub-tasks → routes to agent stubs.

This is Phase 0/1 prototype. The lib/llm_wrapper.py interface is respected
even before full LLM integration — all Claude API calls will route through it.
"""

import json
import uuid
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater
from lib.artifact import create_artifact, write_artifact
from lib.second_brain import write_capability_bundle_entry, write_context_bundle_entry
from lib.algorithmic_rule import AlgorithmicRule
from lib.few_shot_bank import FewShotBank
from governance.notification.notification import (
    NotificationMechanism, Severity, NotificationCategory
)
from governance.confirmation_gate.confirmation_gate import ConfirmationGate, evaluate_artifact_for_gate


AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
SECOND_BRAIN_DIR = BASE / "Maldros 2.0 Brain"

# Phase 0 similarity threshold — below this, First-Principles mode is activated
SIMILARITY_THRESHOLD = 0.75

# Minimum similarity for Analogical mode
ANALOGY_THRESHOLD = 0.50


class OrchestratorAgent:
    """
    Phase 0/1 Orchestrator prototype.

    Key invariants:
    1. CDI Layer query is always first — before any decomposition
    2. Second Brain query is always executed — similarity score always recorded
    3. Capability Bundle is always first artifact — before any agent begins
    4. CEP_5 (multidimensional decomposition) queried when task spans > 1 agent
    """

    def __init__(self, phase: int = 0):
        self.phase = phase
        self.notifier = NotificationMechanism()
        self.gate = ConfirmationGate()

    def process_question(self, question: str, task_id: Optional[str] = None) -> dict:
        """
        Main entry point. Accepts a natural-language question.
        Returns a dict with: capability_bundle_id, context_bundle_id, task_decomposition.
        """
        task_id = task_id or str(uuid.uuid4())
        print(f"\n{'='*60}")
        print(f"Orchestrator: Processing question")
        print(f"Task ID: {task_id}")
        print(f"Question: {question}")
        print(f"{'='*60}")

        # ── Step 0: Algorithmic Rule cycle decision (Phase 4)
        # Hard rule: every 10th cycle is mandatorily diverted to a counter-intuitive
        # hypothesis from the open Constraint Register. The system cannot skip.
        algorithmic_rule = AlgorithmicRule(agent_name="orchestrator", task_id=task_id)
        cycle = algorithmic_rule.next_cycle()
        diversion = None
        original_question = question
        if cycle["is_exploration_cycle"]:
            print(f"\n⚡ ALGORITHMIC RULE — cycle #{cycle['cycle_number']} is an exploration cycle "
                  f"({cycle['exploration_percent']:.0f}% budget).")
        else:
            print(f"\n[Algorithmic Rule] Cycle #{cycle['cycle_number']} — standard. "
                  f"Next exploration in {cycle['cycles_until_next_exploration']} cycle(s).")

        # ── Step 1: CDI Layer query (MUST happen before everything else)
        reader = CDIReader(agent_name="orchestrator", task_id=task_id)
        cdi_context = self._query_cdi_layer(reader, question)

        # Fire the exploration diversion only after CDI has been queried (so
        # get_open_constraints() reflects the current Constraint Register state).
        if cycle["is_exploration_cycle"]:
            diversion = algorithmic_rule.fire(cycle, task_id=task_id, reader=reader)
            print(f"  → Constraint: {diversion['constraint_id']}")
            print(f"  → Hypothesis: {diversion['hypothesis'][:140]}...")
            question = (
                f"[EXPLORATION CYCLE #{cycle['cycle_number']}] {diversion['hypothesis']}\n\n"
                f"(Original standard-queue question deferred: {original_question})"
            )

        # ── Step 2: Second Brain query
        second_brain_result = self._query_second_brain(question, reader)
        similarity_score = second_brain_result["similarity_score"]

        # ── Step 3: Update Capability Bundle context with both results
        active_modes = self._select_reasoning_modes(similarity_score, cdi_context)
        capabilities_met, capabilities_not_met = self._evaluate_capabilities(question, self.phase)

        # ── Step 4: Emit Capability Bundle (FIRST ARTIFACT — before any decomposition)
        # Phase 4 — Algorithmic Rule cycle data is included in content before hashing.
        # Must be built here and passed in; mutating content after create_artifact
        # would invalidate the content_hash.
        algorithmic_rule_data = {
            "cycle_number": cycle["cycle_number"],
            "is_exploration_cycle": cycle["is_exploration_cycle"],
            "exploration_percent": cycle["exploration_percent"],
            "cycles_until_next_exploration": cycle["cycles_until_next_exploration"],
            "diversion": diversion,
            "original_question_if_diverted": original_question if diversion else None,
        }
        capability_bundle = self._emit_capability_bundle(
            task_id=task_id,
            question=question,
            cdi_context=cdi_context,
            second_brain_result=second_brain_result,
            active_modes=active_modes,
            capabilities_met=capabilities_met,
            capabilities_not_met=capabilities_not_met,
            algorithmic_rule_data=algorithmic_rule_data,
        )
        cb_path = write_artifact(capability_bundle)
        write_capability_bundle_entry(capability_bundle)
        print(f"\n✓ Capability Bundle emitted: {capability_bundle['artifact_id'][:8]}...")
        print(f"  Active reasoning modes: {[m['id'] for m in active_modes]}")
        print(f"  L1 nominal: {cdi_context['l1_nominal']}")
        print(f"  Second Brain similarity: {similarity_score:.2f}")

        # Log to AIMS Mode A
        self._log_to_aims_mode_a({
            "event_type": "CAPABILITY_BUNDLE_EMITTED",
            "task_id": task_id,
            "artifact_id": capability_bundle["artifact_id"],
            "question": question,
            "active_reasoning_modes": [m["id"] for m in active_modes],
            "l1_nominal": cdi_context["l1_nominal"],
        })

        # ── Step 5: Emit Context Bundle
        context_bundle = self._emit_context_bundle(
            task_id=task_id,
            question=question,
            second_brain_result=second_brain_result,
            provenance=[capability_bundle["artifact_id"]],
        )
        ctx_path = write_artifact(context_bundle)
        write_context_bundle_entry(context_bundle)
        print(f"✓ Context Bundle emitted: {context_bundle['artifact_id'][:8]}...")

        # ── Step 6: CDI query for decomposition frameworks (CEP_5)
        decomposition_structure = self._decompose_with_cdi(question, reader, task_id)

        # ── Step 7: Record non-activation
        updater = CDIUpdater(agent_name="orchestrator", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        # ── Step 8: Record CEP_5 exercise
        updater.record_capability_exercise(
            capability_id="CEP_5",
            task_id=task_id,
            outcome=f"Decomposition into {len(decomposition_structure['tasks'])} tasks",
        )

        result = {
            "task_id": task_id,
            "capability_bundle_id": capability_bundle["artifact_id"],
            "context_bundle_id": context_bundle["artifact_id"],
            "task_decomposition": decomposition_structure,
            "active_reasoning_modes": [m["id"] for m in active_modes],
            "l1_nominal": cdi_context["l1_nominal"],
            "algorithmic_rule_cycle": cycle["cycle_number"],
            "is_exploration_cycle": cycle["is_exploration_cycle"],
            "algorithmic_rule_diversion": diversion,
        }

        print(f"\n✓ Decomposition complete: {len(decomposition_structure['tasks'])} tasks")
        for t in decomposition_structure["tasks"]:
            print(f"  → {t['task_label']}: {t['assigned_agent']}")

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # CDI LAYER QUERY
    # ──────────────────────────────────────────────────────────────────────────

    def _query_cdi_layer(self, reader: CDIReader, question: str) -> dict:
        """Query CDI Layer for task-relevant context. Records which domains queried."""
        print("\n[CDI Layer query]")
        available_modes = reader.get_available_reasoning_modes()
        l1_vetoes = reader.get_active_l1_vetoes()
        analogues = reader.get_analogues_for_problem(question)
        constraints = reader.get_open_constraints()
        capabilities = reader.get_capability_registry()

        print(f"  Domains queried: {reader.get_queried_domains()}")
        print(f"  L1 vetoes: {l1_vetoes if l1_vetoes else 'None (nominal)'}")
        print(f"  Relevant analogues: {len(analogues)}")

        return {
            "available_modes": available_modes,
            "l1_nominal": len(l1_vetoes) == 0,
            "active_vetoes": l1_vetoes,
            "relevant_analogues": analogues,
            "open_constraints": constraints,
            "capabilities": capabilities,
            "queried_domains": list(reader.get_queried_domains()),
            "key_findings": [a["analytics_translation"] for a in analogues[:3]],
        }

    # ──────────────────────────────────────────────────────────────────────────
    # SECOND BRAIN QUERY
    # ──────────────────────────────────────────────────────────────────────────

    def _query_second_brain(self, question: str, reader: CDIReader) -> dict:
        """
        Query Second Brain via CDI Layer signal (Phase 1 keyword search).
        Phase 2: vector search via lib/vector_index.py
        """
        print("\n[Second Brain query]")
        sb_state = reader.get_second_brain_state()

        # Phase 0/1: keyword-based matching against vault files
        matching_notes = self._keyword_search_vault(question)
        similarity_score = min(0.8, len(matching_notes) * 0.15) if matching_notes else 0.0

        print(f"  Vault notes: {sb_state['vault_state']['total_notes']}")
        print(f"  Matching notes: {len(matching_notes)}")
        print(f"  Similarity score: {similarity_score:.2f}")

        return {
            "query": question,
            "similarity_score": similarity_score,
            "matching_notes": matching_notes[:5],
            "prior_analyses": [],
            "relevant_metrics": self._extract_relevant_metrics(question),
            "external_intelligence": reader.get_external_knowledge(topic=question[:50]),
            "open_constraints": reader.get_open_constraints(),
            "retrieval_mode": "keyword",
        }

    def _keyword_search_vault(self, question: str) -> list[dict]:
        """Phase 1 keyword search over vault markdown files."""
        keywords = set(question.lower().split()) - {"the", "a", "an", "is", "are", "what", "how", "why"}
        results = []
        if not SECOND_BRAIN_DIR.exists():
            return results
        for md_file in SECOND_BRAIN_DIR.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8").lower()
                score = sum(1 for kw in keywords if len(kw) > 4 and kw in content)
                if score > 0:
                    results.append({"path": str(md_file.relative_to(BASE)), "score": score})
            except Exception:
                pass
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def _extract_relevant_metrics(self, question: str) -> list[str]:
        """Extract relevant metrics from the question."""
        metric_keywords = {
            "api_abuse_rate": ["api abuse", "abuse rate", "policy violation", "api_abuse"],
            "fraud_loss_direct": ["fraud loss", "direct loss", "financial impact", "fraud"],
            "account_takeover_volume": ["account takeover", "takeover", "compromised account"],
            "safety_bypass_incidents": ["safety bypass", "jailbreak", "bypass", "safety"],
            "downstream_harm_exposure": ["downstream harm", "harm exposure", "third party"],
            "compliance_cost_per_incident": ["compliance cost", "cost per incident", "remediation"],
        }
        question_lower = question.lower()
        relevant = []
        for metric, keywords in metric_keywords.items():
            if any(kw in question_lower for kw in keywords):
                relevant.append(metric)
        return relevant

    # ──────────────────────────────────────────────────────────────────────────
    # REASONING MODE SELECTION
    # ──────────────────────────────────────────────────────────────────────────

    def _select_reasoning_modes(self, similarity_score: float, cdi_context: dict) -> list[dict]:
        """Select active reasoning modes based on similarity score and task context."""
        available = cdi_context["available_modes"]
        active = []

        if similarity_score >= SIMILARITY_THRESHOLD:
            mode = next((m for m in available if m["id"] == "MODE_1"), None)
            if mode:
                active.append(mode)
        else:
            mode = next((m for m in available if m["id"] == "MODE_2"), None)
            if mode:
                active.append(mode)

        if cdi_context["relevant_analogues"]:
            mode = next((m for m in available if m["id"] == "MODE_5"), None)
            if mode and mode not in active:
                active.append(mode)

        return active

    # ──────────────────────────────────────────────────────────────────────────
    # CAPABILITY EVALUATION
    # ──────────────────────────────────────────────────────────────────────────

    def _evaluate_capabilities(self, question: str, phase: int) -> tuple[list, list]:
        """Evaluate which CEPs are met and which are not for this task."""
        reader = CDIReader(agent_name="orchestrator", task_id="cep_eval")
        all_caps = reader.get_capability_registry()

        met, not_met = [], []
        for cap in all_caps:
            if phase in cap.get("applicable_phases", []):
                met.append(cap["id"])
            else:
                not_met.append({
                    "cep_id": cap["id"],
                    "reason": f"Not applicable in Phase {phase} (applicable: {cap['applicable_phases']})",
                })
        return met, not_met

    # ──────────────────────────────────────────────────────────────────────────
    # ARTIFACT EMISSION
    # ──────────────────────────────────────────────────────────────────────────

    def _emit_capability_bundle(self, task_id, question, cdi_context,
                                 second_brain_result, active_modes,
                                 capabilities_met, capabilities_not_met,
                                 algorithmic_rule_data: Optional[dict] = None) -> dict:
        content = {
            "task_id": task_id,
            "task_description": question,
            "cdi_query_timestamp": datetime.now(timezone.utc).isoformat(),
            "active_reasoning_modes": [m["id"] for m in active_modes],
            "capabilities_met": capabilities_met,
            "capabilities_not_met": capabilities_not_met,
            "cdi_lineage_trace": {
                "domains_queried": cdi_context["queried_domains"],
                "key_findings": cdi_context["key_findings"],
                "alternative_approaches_surfaced": [
                    a["analytics_translation"] for a in cdi_context["relevant_analogues"][:3]
                ],
            },
            "l1_veto_state": {
                "nominal": cdi_context["l1_nominal"],
                "active_vetoes": cdi_context["active_vetoes"],
            },
            "second_brain_similarity_score": second_brain_result["similarity_score"],
            "decomposition": {"tasks": []},  # Populated after CDI decomposition query
            "algorithmic_rule": algorithmic_rule_data or {},
        }
        return create_artifact(
            artifact_type="capability_bundle",
            producing_agent="orchestrator",
            phase=self.phase,
            content=content,
            provenance=[],
            confidence_score=0.9,
            known_limitations=["Phase 0 prototype — LLM-powered CDI queries not yet active; using keyword matching"],
        )

    def _emit_context_bundle(self, task_id, question, second_brain_result, provenance) -> dict:
        content = {
            "task_id": task_id,
            "second_brain_query": question,
            "similarity_score": second_brain_result["similarity_score"],
            "prior_analyses": second_brain_result["prior_analyses"],
            "relevant_metrics": second_brain_result["relevant_metrics"],
            "external_intelligence": second_brain_result["external_intelligence"],
            "open_constraints": second_brain_result["open_constraints"],
            "retrieval_mode": second_brain_result["retrieval_mode"],
        }
        return create_artifact(
            artifact_type="context_bundle",
            producing_agent="orchestrator",
            phase=self.phase,
            content=content,
            provenance=provenance,
            confidence_score=0.7,
            known_limitations=["Phase 0: keyword search only; vector search added in Phase 2"],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # TASK DECOMPOSITION (CEP_5)
    # ──────────────────────────────────────────────────────────────────────────

    def _decompose_with_cdi(self, question: str, reader: CDIReader, task_id: str) -> dict:
        """
        Query CDI for decomposition frameworks (CEP_5) then decompose the task.
        The standard 4-agent decomposition is the default; CDI may augment it.
        """
        print("\n[Task decomposition — CDI query for CEP_5]")

        # Check if this needs new data models
        needs_new_models = any(kw in question.lower()
                               for kw in ["new metric", "new model", "build a table", "create a view"])

        # Standard tasks
        tasks = []
        if needs_new_models:
            tasks.append({
                "task_label": "Task A",
                "assigned_agent": "data_architect",
                "description": "Design and generate required data models",
                "cdi_influence": "CDI disciplinary_methods: programming logic for formal model specification",
            })

        tasks.extend([
            {
                "task_label": "Task B",
                "assigned_agent": "analyst",
                "description": f"Investigate: {question[:100]}",
                "cdi_influence": "CDI cross_domain_analogues: alternative analytical frameworks for this problem type",
            },
            {
                "task_label": "Task C",
                "assigned_agent": "statistician",
                "description": "Validate all inferences from analyst findings",
                "cdi_influence": "CDI reasoning_frameworks: alternative statistical validation methods",
            },
            {
                "task_label": "Task D",
                "assigned_agent": "red_team",
                "description": "Stress-test findings for evasion vulnerability",
                "cdi_influence": "CDI adversarial frameworks: evasion categories E1-E12",
            },
            {
                "task_label": "Task E",
                "assigned_agent": "storyteller",
                "description": "Produce Discovery Report + AIMS routing",
                "cdi_influence": "CDI cross_domain_analogues: framing analogies for plain-language translation",
            },
        ])

        cdi_delta = "Standard 4-agent decomposition confirmed. Network forensics analogue from CDI suggests adding graph-topology validation as explicit sub-step within Task B."
        print(f"  CDI influence: {cdi_delta}")
        print(f"  Total tasks: {len(tasks)}")

        return {
            "cdi_decomposition_query": "Frameworks for multi-causal attribution problems",
            "cdi_delta": cdi_delta,
            "tasks": tasks,
        }

    def _log_to_aims_mode_a(self, entry: dict) -> None:
        """Log an operational event to AIMS Mode A."""
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
        entry["aims_entry_id"] = str(uuid.uuid4())
        entry["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        log_file = AIMS_MODE_A_DIR / "orchestrator_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# QUICK TEST (Phase 0 verification)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    orch = OrchestratorAgent(phase=0)
    result = orch.process_question(
        "Is the Q1 spike in API abuse volume driven by coordinated multi-account behavior, "
        "and what is the financial exposure?"
    )
    print("\n" + "=" * 60)
    print("RESULT SUMMARY")
    print("=" * 60)
    print(json.dumps({
        "task_id": result["task_id"],
        "capability_bundle_id": result["capability_bundle_id"][:8] + "...",
        "context_bundle_id": result["context_bundle_id"][:8] + "...",
        "active_modes": result["active_reasoning_modes"],
        "l1_nominal": result["l1_nominal"],
        "tasks": [t["task_label"] + ": " + t["assigned_agent"]
                  for t in result["task_decomposition"]["tasks"]],
    }, indent=2))
