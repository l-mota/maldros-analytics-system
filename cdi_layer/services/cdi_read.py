"""
CDI Layer Read Interface — cdi_read.py
All agents query the CDI Layer through this module. Direct file reads are forbidden.

Usage:
    from cdi_layer.services.cdi_read import CDIReader

    reader = CDIReader()
    frameworks = reader.get_reasoning_frameworks()
    analogues = reader.get_analogues_for_problem("detecting coordinated behavior")
    l1_status = reader.get_inference_layer_status("L1")
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

INDEX_DIR = Path(__file__).resolve().parents[1] / "index"
CAPABILITY_REGISTRY = Path(__file__).resolve().parents[1] / "capability_registry" / "capability_registry.json"

logger = logging.getLogger(__name__)


def _load(filename: str) -> dict:
    path = INDEX_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"CDI index file missing: {path}. Run Phase 0 setup.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class CDIReader:
    """
    Read interface for the CDI Layer.

    Every agent uses this to query CDI domains. Each query is recorded in
    the non-activation log via cdi_update.py (caller is responsible for
    recording which domains were NOT queried on a given task).
    """

    def __init__(self, agent_name: str = "unknown", task_id: str = "unknown"):
        self.agent_name = agent_name
        self.task_id = task_id
        self._queried_domains: set = set()

    # ─────────────────────────────────────────────────────────────────────────
    # REASONING FRAMEWORKS
    # ─────────────────────────────────────────────────────────────────────────

    def get_reasoning_frameworks(self) -> list[dict]:
        """Return all 7 reasoning modes with activation states."""
        data = _load("reasoning_frameworks.json")
        self._queried_domains.add("reasoning_frameworks")
        return data["modes"]

    def get_reasoning_mode(self, mode_id: str) -> Optional[dict]:
        """Return a single reasoning mode by ID (MODE_1 through MODE_7)."""
        for mode in self.get_reasoning_frameworks():
            if mode["id"] == mode_id:
                return mode
        return None

    def get_available_reasoning_modes(self) -> list[dict]:
        """Return only modes with activation_state == 'AVAILABLE'."""
        return [m for m in self.get_reasoning_frameworks() if m["activation_state"] == "AVAILABLE"]

    # ─────────────────────────────────────────────────────────────────────────
    # DISCIPLINARY METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def get_disciplinary_methods(self) -> list[dict]:
        """Return all 8 disciplinary knowledge domains."""
        data = _load("disciplinary_methods.json")
        self._queried_domains.add("disciplinary_methods")
        return data["disciplines"]

    def get_discipline_for_agent(self, agent_name: str) -> list[dict]:
        """Return disciplines most relevant to a given agent."""
        disciplines = self.get_disciplinary_methods()
        return [d for d in disciplines if agent_name in d.get("primary_agents", [])]

    # ─────────────────────────────────────────────────────────────────────────
    # INFERENCE LAYERS
    # ─────────────────────────────────────────────────────────────────────────

    def get_inference_layer_status(self, layer_id: Optional[str] = None) -> dict | list:
        """
        Return inference layer status. If layer_id given (e.g. 'L1'), return that layer.
        Otherwise return all layers.
        """
        data = _load("inference_layers.json")
        self._queried_domains.add("inference_layers")
        if layer_id:
            for layer in data["layers"]:
                if layer["id"] == layer_id:
                    return layer
            raise ValueError(f"Unknown layer_id: {layer_id}")
        return data["layers"]

    def get_active_l1_vetoes(self) -> list[str]:
        """Return list of currently active L1 veto classes. Empty = nominal."""
        l1 = self.get_inference_layer_status("L1")
        return l1.get("active_vetoes", [])

    def is_l1_nominal(self) -> bool:
        """True if no L1 vetoes are currently active."""
        return len(self.get_active_l1_vetoes()) == 0

    # ─────────────────────────────────────────────────────────────────────────
    # CROSS-DOMAIN ANALOGUES
    # ─────────────────────────────────────────────────────────────────────────

    def get_all_analogues(self) -> list[dict]:
        """Return all cross-domain analogues."""
        data = _load("cross_domain_analogues.json")
        self._queried_domains.add("cross_domain_analogues")
        return data["analogues"]

    def get_analogues_for_problem(self, problem_description: str) -> list[dict]:
        """
        Return analogues relevant to a problem description.
        Keyword-based matching for Phase 1; vector search added in Phase 2.
        """
        analogues = self.get_all_analogues()
        problem_lower = problem_description.lower()
        keywords = set(problem_lower.split())

        scored = []
        for analogue in analogues:
            score = 0
            text = (analogue["problem_structure"] + " " + analogue["analytics_translation"]).lower()
            for kw in keywords:
                if len(kw) > 4 and kw in text:
                    score += 1
            if score > 0:
                scored.append((score, analogue))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:5]]

    def get_repair_analogues_by_failure_class(self, failure_class: str) -> list[dict]:
        """
        Return cross-domain analogues whose failure_classes list includes this class.
        Used by Healing Agent (Phase 2) to retrieve canonical 5-domain repair strategies
        (Medicine, Materials Science, Systems Biology, Military Logistics, Law).

        failure_class ∈ {structural_break, gradual_degradation, contamination,
                         cascade, capacity_overload, ambiguity}
        """
        self._queried_domains.add("cross_domain_analogues")
        analogues = _load("cross_domain_analogues.json")["analogues"]
        return [a for a in analogues
                if failure_class in a.get("failure_classes", [])]

    def get_repair_strategies(self, failure_class: str) -> list[dict]:
        """
        Return the flat list of repair_strategies across all matching analogues
        for a given failure_class. Each strategy carries domain provenance.

        Used by Healing Agent for the score-and-select step.
        """
        analogues = self.get_repair_analogues_by_failure_class(failure_class)
        out = []
        for a in analogues:
            for strat in a.get("repair_strategies", []):
                out.append({
                    **strat,
                    "domain": a["source_domain"],
                    "analogue_id": a["id"],
                })
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # EXTERNAL KNOWLEDGE
    # ─────────────────────────────────────────────────────────────────────────

    def get_external_knowledge(self, topic: Optional[str] = None) -> list[dict]:
        """Return external knowledge signals, optionally filtered by topic keyword."""
        data = _load("external_knowledge.json")
        self._queried_domains.add("external_knowledge")
        signals = data["signals"]
        if topic:
            topic_lower = topic.lower()
            signals = [s for s in signals if topic_lower in s["topic"].lower()
                       or topic_lower in s["summary"].lower()]
        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # SECOND BRAIN SIGNAL
    # ─────────────────────────────────────────────────────────────────────────

    def get_second_brain_state(self) -> dict:
        """Return current Second Brain vault state (not a fresh query — CDI Layer reflection)."""
        data = _load("second_brain_signal.json")
        self._queried_domains.add("second_brain_signal")
        return data

    def get_open_constraints(self) -> list[dict]:
        """Return open Constraint Register entries from the Second Brain signal."""
        state = self.get_second_brain_state()
        return state.get("open_constraints", [])

    # ─────────────────────────────────────────────────────────────────────────
    # EXEMPLAR SURFACE (FEW-SHOT BANK)
    # ─────────────────────────────────────────────────────────────────────────

    def get_exemplars(self, query_class: Optional[str] = None) -> list[dict]:
        """Return active Few-Shot Bank exemplars, optionally filtered by query class."""
        data = _load("exemplar_surface.json")
        self._queried_domains.add("exemplar_surface")
        exemplars = data.get("exemplars", [])
        if query_class and exemplars:
            exemplars = [e for e in exemplars
                         if query_class.lower() in e.get("query_class", "").lower()]
        return exemplars

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 7 SIGNALS
    # ─────────────────────────────────────────────────────────────────────────

    def get_phase7_signals(self) -> dict:
        """Return Phase 7 bottleneck candidates and improvement signals."""
        data = _load("phase7_signals.json")
        self._queried_domains.add("phase7_signals")
        return data

    # ─────────────────────────────────────────────────────────────────────────
    # DESIGN SYSTEM (C-031 / C-032)
    # ─────────────────────────────────────────────────────────────────────────

    def get_design_system(self) -> dict:
        """
        Return the Maldros Visual Design System (C-031) snapshot.

        Every agent that produces a visual artifact MUST call this before
        emitting output. A Capability Bundle whose lineage trace lacks a
        design_system query, when the task produces visual output, is a
        Diagnostic Agent L1 failure.

        Returns the full domain payload: communication_pattern, color_system,
        typography_hierarchy, chart_construction_rules, information_hierarchy,
        stakeholder_calibration.
        """
        data = _load("design_system.json")
        self._queried_domains.add("design_system")
        return data

    def get_design_palette(self) -> dict:
        """Convenience: return only the color tokens (data-meaning + infrastructure)."""
        return self.get_design_system()["color_system"]

    def get_chart_construction_rules(self) -> dict:
        """Convenience: return chart construction rules used by Storyteller."""
        return self.get_design_system()["chart_construction_rules"]

    # ─────────────────────────────────────────────────────────────────────────
    # CAPABILITY REGISTRY
    # ─────────────────────────────────────────────────────────────────────────

    def get_capability_registry(self) -> list[dict]:
        """Return the 5 capability expansion properties with their requirements."""
        with open(CAPABILITY_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["properties"]

    def get_applicable_capabilities(self, agent_name: str, phase: int) -> list[dict]:
        """Return CEPs applicable to this agent at this phase."""
        props = self.get_capability_registry()
        return [p for p in props
                if agent_name in p.get("applicable_agents", [])
                and phase in p.get("applicable_phases", [])]

    # ─────────────────────────────────────────────────────────────────────────
    # COMPOSITE QUERY (full Capability Bundle context)
    # ─────────────────────────────────────────────────────────────────────────

    def get_capability_bundle_context(self, task_description: str, phase: int) -> dict:
        """
        Composite query for Capability Bundle emission.
        Returns a snapshot of CDI Layer state relevant to the given task.
        This is what the Orchestrator calls when emitting a Capability Bundle.
        """
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "task_description": task_description,
            "phase": phase,
            "available_reasoning_modes": self.get_available_reasoning_modes(),
            "l1_veto_state": {
                "nominal": self.is_l1_nominal(),
                "active_vetoes": self.get_active_l1_vetoes(),
            },
            "relevant_analogues": self.get_analogues_for_problem(task_description),
            "open_constraints": self.get_open_constraints(),
            "applicable_capabilities": {
                agent: self.get_applicable_capabilities(agent, phase)
                for agent in ["orchestrator", "analyst", "statistician", "storyteller",
                              "data_architect", "diagnostic", "healing", "red_team"]
            },
            "second_brain_coverage": _load("second_brain_signal.json")["vault_state"],
            "exemplar_bank_state": _load("exemplar_surface.json")["bank_state"],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION ACCOUNTING (for non-activation log)
    # ─────────────────────────────────────────────────────────────────────────

    def get_queried_domains(self) -> set[str]:
        """Return which domains were queried in this reader session."""
        return self._queried_domains.copy()

    def get_unqueried_domains(self) -> set[str]:
        """Return CDI domains that were NOT queried in this session."""
        all_domains = {
            "reasoning_frameworks", "disciplinary_methods", "inference_layers",
            "cross_domain_analogues", "external_knowledge", "second_brain_signal",
            "exemplar_surface", "phase7_signals", "design_system",
        }
        return all_domains - self._queried_domains
