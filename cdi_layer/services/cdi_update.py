"""
CDI Layer Update Interface — cdi_update.py
The ONLY authorized path for writing to CDI Layer index files.
Direct writes to index files are forbidden — they bypass audit logging and
can produce inconsistent state that the Diagnostic Agent cannot detect.

Usage:
    from cdi_layer.services.cdi_update import CDIUpdater

    updater = CDIUpdater(agent_name="analyst", task_id="task-uuid")
    updater.record_reasoning_mode_usage("MODE_5")
    updater.record_analogue_usage("XDA_002", agent="analyst")
    updater.record_non_activation(queried={"cross_domain_analogues"}, task_id="task-uuid")
    updater.update_second_brain_signal(new_note_path="metrics/api_abuse_rate.md", folder="metrics")
    updater.add_external_knowledge(signal_dict)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

INDEX_DIR = Path(__file__).resolve().parents[1] / "index"
CAPABILITY_REGISTRY = Path(__file__).resolve().parents[1] / "capability_registry" / "capability_registry.json"
AIMS_MODE_A_DIR = Path(__file__).resolve().parents[2] / "aims" / "mode_a"

logger = logging.getLogger(__name__)


def _load(filename: str) -> dict:
    path = INDEX_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(filename: str, data: dict) -> None:
    path = INDEX_DIR / filename
    data["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _save_registry(data: dict) -> None:
    data["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(CAPABILITY_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _log_to_aims_mode_a(event_type: str, payload: dict) -> None:
    """Write a governance event to AIMS Mode A log."""
    AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "aims_entry_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
    log_file = AIMS_MODE_A_DIR / "cdi_update_log.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class CDIUpdater:
    """
    Update interface for the CDI Layer. All writes route through here.

    After completing a task, the calling agent should call:
        record_non_activation(queried_domains, task_id)
    to log which domains were NOT queried.
    """

    def __init__(self, agent_name: str, task_id: str):
        self.agent_name = agent_name
        self.task_id = task_id
        self.timestamp = datetime.now(timezone.utc).isoformat()

    # ─────────────────────────────────────────────────────────────────────────
    # REASONING FRAMEWORKS
    # ─────────────────────────────────────────────────────────────────────────

    def record_reasoning_mode_usage(self, mode_id: str) -> None:
        """Increment usage count for a reasoning mode and record last_used."""
        data = _load("reasoning_frameworks.json")
        for mode in data["modes"]:
            if mode["id"] == mode_id:
                mode["usage_count"] = mode.get("usage_count", 0) + 1
                mode["last_used"] = self.timestamp
                break
        _save("reasoning_frameworks.json", data)

    # ─────────────────────────────────────────────────────────────────────────
    # DISCIPLINARY METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def record_discipline_query(self, discipline_id: str) -> None:
        """Increment query count for a discipline."""
        data = _load("disciplinary_methods.json")
        for disc in data["disciplines"]:
            if disc["id"] == discipline_id:
                disc["query_count"] = disc.get("query_count", 0) + 1
                disc["last_queried"] = self.timestamp
                break
        _save("disciplinary_methods.json", data)

    # ─────────────────────────────────────────────────────────────────────────
    # INFERENCE LAYERS
    # ─────────────────────────────────────────────────────────────────────────

    def set_l1_veto(self, veto_class: str, reason: str) -> None:
        """
        Activate an L1 veto. This immediately blocks all downstream processing.
        Triggers AIMS Mode A event.
        """
        data = _load("inference_layers.json")
        for layer in data["layers"]:
            if layer["id"] == "L1":
                if veto_class not in layer["active_vetoes"]:
                    layer["active_vetoes"].append(veto_class)
                layer.setdefault("veto_history", []).append({
                    "veto_class": veto_class,
                    "reason": reason,
                    "set_by": self.agent_name,
                    "task_id": self.task_id,
                    "timestamp": self.timestamp,
                    "status": "ACTIVE",
                })
                if layer["current_state"] != "L1_VETO_ACTIVE":
                    layer["current_state"] = "L1_VETO_ACTIVE"
                break
        _save("inference_layers.json", data)
        _log_to_aims_mode_a("L1_VETO_SET", {
            "veto_class": veto_class,
            "reason": reason,
            "agent": self.agent_name,
            "task_id": self.task_id,
        })
        logger.warning(f"L1 VETO SET: {veto_class} by {self.agent_name} on task {self.task_id}")

    def clear_l1_veto(self, veto_class: str, resolution: str) -> None:
        """
        Clear an L1 veto after resolution. Requires explicit resolution statement.
        Triggers AIMS Mode A event.
        """
        data = _load("inference_layers.json")
        for layer in data["layers"]:
            if layer["id"] == "L1":
                if veto_class in layer["active_vetoes"]:
                    layer["active_vetoes"].remove(veto_class)
                for entry in layer.get("veto_history", []):
                    if entry["veto_class"] == veto_class and entry["status"] == "ACTIVE":
                        entry["status"] = "CLEARED"
                        entry["cleared_by"] = self.agent_name
                        entry["resolution"] = resolution
                        entry["cleared_at"] = self.timestamp
                if not layer["active_vetoes"]:
                    layer["current_state"] = "NOMINAL"
                break
        _save("inference_layers.json", data)
        _log_to_aims_mode_a("L1_VETO_CLEARED", {
            "veto_class": veto_class,
            "resolution": resolution,
            "agent": self.agent_name,
            "task_id": self.task_id,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # CROSS-DOMAIN ANALOGUES
    # ─────────────────────────────────────────────────────────────────────────

    def record_analogue_usage(self, analogue_id: str) -> None:
        """Increment use count and record which agents have accessed an analogue."""
        data = _load("cross_domain_analogues.json")
        for analogue in data["analogues"]:
            if analogue["id"] == analogue_id:
                analogue["use_count"] = analogue.get("use_count", 0) + 1
                if self.agent_name not in analogue.get("agents_accessed", []):
                    analogue.setdefault("agents_accessed", []).append(self.agent_name)
                if analogue.get("first_used") is None:
                    analogue["first_used"] = self.timestamp
                break
        _save("cross_domain_analogues.json", data)

    def add_analogue(self, analogue: dict) -> None:
        """
        Add a new cross-domain analogue to the index.
        Requires: id, problem_structure, source_domain, source_solution,
                  analytics_translation, structural_isomorphism.
        """
        required = ["id", "problem_structure", "source_domain", "source_solution",
                    "analytics_translation", "structural_isomorphism"]
        missing = [f for f in required if f not in analogue]
        if missing:
            raise ValueError(f"New analogue missing required fields: {missing}")
        data = _load("cross_domain_analogues.json")
        analogue.setdefault("use_count", 0)
        analogue.setdefault("first_used", None)
        analogue.setdefault("agents_accessed", [])
        data["analogues"].append(analogue)
        _save("cross_domain_analogues.json", data)
        _log_to_aims_mode_a("NEW_ANALOGUE_ADDED", {
            "analogue_id": analogue["id"],
            "source_domain": analogue["source_domain"],
            "added_by": self.agent_name,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # EXTERNAL KNOWLEDGE
    # ─────────────────────────────────────────────────────────────────────────

    def add_external_knowledge(self, signal: dict) -> None:
        """
        Add a new external knowledge signal.
        Requires: id, topic, source, retrieval_date, summary, relevance_to_constraints.
        """
        required = ["id", "topic", "source", "retrieval_date", "summary"]
        missing = [f for f in required if f not in signal]
        if missing:
            raise ValueError(f"External knowledge signal missing required fields: {missing}")
        data = _load("external_knowledge.json")
        data["signals"].append(signal)
        _save("external_knowledge.json", data)

    # ─────────────────────────────────────────────────────────────────────────
    # SECOND BRAIN SIGNAL
    # ─────────────────────────────────────────────────────────────────────────

    def update_second_brain_signal(self, new_note_path: str, folder: str) -> None:
        """
        Called whenever a new note is added to the Second Brain vault.
        Updates folder counts and recent additions list.
        """
        data = _load("second_brain_signal.json")
        vault_state = data["vault_state"]
        vault_state["total_notes"] = vault_state.get("total_notes", 0) + 1
        vault_state["last_addition"] = self.timestamp[:10]
        folders = vault_state.get("folders", {})
        folders[folder] = folders.get(folder, 0) + 1
        vault_state["folders"] = folders
        data.setdefault("recent_additions", []).insert(0, {
            "path": new_note_path,
            "folder": folder,
            "added_at": self.timestamp,
            "added_by": self.agent_name,
        })
        data["recent_additions"] = data["recent_additions"][:20]
        _save("second_brain_signal.json", data)

    def open_constraint(self, constraint_id: str, title: str, summary: str,
                        status: str = "OPEN") -> None:
        """Add or update a Constraint Register entry in the Second Brain signal."""
        data = _load("second_brain_signal.json")
        constraints = data.get("open_constraints", [])
        for c in constraints:
            if c["constraint_id"] == constraint_id:
                c.update({"title": title, "summary": summary, "status": status})
                _save("second_brain_signal.json", data)
                return
        constraints.append({
            "constraint_id": constraint_id,
            "title": title,
            "summary": summary,
            "status": status,
            "relevance": "",
        })
        data["open_constraints"] = constraints
        _save("second_brain_signal.json", data)

    def close_constraint(self, constraint_id: str, resolution: str) -> None:
        """Mark a Constraint Register entry as resolved."""
        data = _load("second_brain_signal.json")
        for c in data.get("open_constraints", []):
            if c["constraint_id"] == constraint_id:
                c["status"] = "CLOSED"
                c["resolution"] = resolution
                c["closed_at"] = self.timestamp
                break
        _save("second_brain_signal.json", data)
        _log_to_aims_mode_a("CONSTRAINT_CLOSED", {
            "constraint_id": constraint_id,
            "resolution": resolution,
            "agent": self.agent_name,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # EXEMPLAR SURFACE (FEW-SHOT BANK)
    # ─────────────────────────────────────────────────────────────────────────

    def promote_exemplar(self, exemplar: dict) -> None:
        """
        Promote an approved exemplar to the Few-Shot Bank.
        Requires Promotion Gate authorization — this should only be called
        after the Promotion Gate has approved the exemplar.
        Required fields: id, query_class, input, output, justification.
        """
        required = ["id", "query_class", "input", "output", "justification"]
        missing = [f for f in required if f not in exemplar]
        if missing:
            raise ValueError(f"Exemplar missing required fields: {missing}")

        data = _load("exemplar_surface.json")
        exemplar["promoted_at"] = self.timestamp
        exemplar["promoted_by"] = self.agent_name
        exemplar["task_id"] = self.task_id
        exemplar["recency_score"] = 1.0

        data.setdefault("exemplars", []).append(exemplar)
        bank = data.setdefault("bank_state", {})
        bank["total_exemplars"] = len(data["exemplars"])
        bank["last_promotion"] = self.timestamp
        qc = bank.setdefault("query_classes_covered", [])
        if exemplar["query_class"] not in qc:
            qc.append(exemplar["query_class"])
        _save("exemplar_surface.json", data)
        _log_to_aims_mode_a("EXEMPLAR_PROMOTED", {
            "exemplar_id": exemplar["id"],
            "query_class": exemplar["query_class"],
            "promoted_by": self.agent_name,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # NON-ACTIVATION LOGGING
    # ─────────────────────────────────────────────────────────────────────────

    def record_non_activation(self, queried_domains: set[str]) -> None:
        """
        Record which CDI domains were NOT queried on this task.
        Called at task completion by every agent.
        This is the input to Phase 7 blind spot detection.
        """
        all_domains = {
            "reasoning_frameworks", "disciplinary_methods", "inference_layers",
            "cross_domain_analogues", "external_knowledge", "second_brain_signal",
            "exemplar_surface", "phase7_signals"
        }
        not_queried = all_domains - queried_domains

        data = _load("non_activation_log.json")
        entry = {
            "log_id": str(uuid.uuid4()),
            "timestamp": self.timestamp,
            "agent": self.agent_name,
            "task_id": self.task_id,
            "domains_queried": list(queried_domains),
            "domains_not_queried": list(not_queried),
        }
        data.setdefault("log_entries", []).append(entry)

        # Update per-agent statistics
        stats = data.setdefault("agent_query_statistics", {})
        agent_stats = stats.setdefault(self.agent_name, {
            "total_tasks": 0, "cdi_queries": 0, "non_queries_by_domain": {}
        })
        agent_stats["total_tasks"] += 1
        agent_stats["cdi_queries"] += len(queried_domains)
        for domain in not_queried:
            agent_stats["non_queries_by_domain"][domain] = \
                agent_stats["non_queries_by_domain"].get(domain, 0) + 1

        # Check for blind spot alerts
        threshold = 5
        alerts = data.setdefault("blind_spot_alerts", [])
        for domain, count in agent_stats["non_queries_by_domain"].items():
            if count >= threshold:
                alert_key = f"{self.agent_name}:{domain}"
                existing = [a for a in alerts if a.get("key") == alert_key]
                if not existing:
                    alert = {
                        "key": alert_key,
                        "agent": self.agent_name,
                        "domain": domain,
                        "consecutive_non_queries": count,
                        "first_detected": self.timestamp,
                        "status": "OPEN",
                    }
                    alerts.append(alert)
                    _log_to_aims_mode_a("CDI_BLIND_SPOT_DETECTED", alert)
                    logger.warning(f"CDI blind spot: {self.agent_name} has not queried "
                                   f"'{domain}' for {count} consecutive tasks")
                else:
                    existing[0]["consecutive_non_queries"] = count

        _save("non_activation_log.json", data)

    # ─────────────────────────────────────────────────────────────────────────
    # DESIGN SYSTEM (color tokens)
    # ─────────────────────────────────────────────────────────────────────────

    def update_color_token(self, slot: str, new_hex: str, justification: str) -> None:
        """
        Refine a hex value in the design_system CDI domain (cdi_layer/index/design_system.json).
        design_system.json's own _meta.update_policy requires this — direct writes to that
        file are forbidden. Searches data_meaning, infrastructure, and semantic_accents for
        the slot key (e.g. "TERTIARY", "BORDER", "ACTION_GREEN"); raises if not found.
        Per the file's own governance field: changes are operator-approved per D-7 and
        logged as C-NNN entries in the Change Tracker — this call only performs the write
        and the AIMS Mode A log entry, it does not substitute for that Change Tracker entry.
        """
        data = _load("design_system.json")
        groups = ("data_meaning", "infrastructure", "semantic_accents")
        found = False
        old_hex = None
        for group in groups:
            slots = data["color_system"].get(group, {})
            if slot in slots:
                old_hex = slots[slot]["hex"]
                slots[slot]["hex"] = new_hex
                found = True
                break
        if not found:
            raise ValueError(f"Color slot '{slot}' not found in design_system.json color_system")
        _save("design_system.json", data)
        _log_to_aims_mode_a("COLOR_TOKEN_REFINED", {
            "slot": slot,
            "old_hex": old_hex,
            "new_hex": new_hex,
            "justification": justification,
            "agent": self.agent_name,
            "task_id": self.task_id,
        })
        logger.info(f"Color token refined: {slot} {old_hex} -> {new_hex} by {self.agent_name}")

    # ─────────────────────────────────────────────────────────────────────────
    # CAPABILITY REGISTRY
    # ─────────────────────────────────────────────────────────────────────────

    def record_capability_exercise(self, capability_id: str,
                                   task_id: str, outcome: str) -> None:
        """Record that a capability expansion property was exercised on a task."""
        with open(CAPABILITY_REGISTRY, "r", encoding="utf-8") as f:
            data = json.load(f)

        for prop in data["properties"]:
            if prop["id"] == capability_id:
                prop["usage_count"] = prop.get("usage_count", 0) + 1
                prop["last_exercised"] = self.timestamp
                prop.setdefault("exercise_log", []).append({
                    "task_id": task_id,
                    "agent": self.agent_name,
                    "timestamp": self.timestamp,
                    "outcome": outcome,
                })
                break

        _save_registry(data)
