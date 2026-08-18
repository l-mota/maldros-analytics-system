"""
Data Architect Agent stub — agents/data_architect/data_architect.py
Phase 0: validates Capability Bundle, emits context_bundle with schema scope.
Full implementation in Phase 1.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.artifact import create_artifact, write_artifact, read_artifact, validate_envelope
from cdi_layer.services.cdi_read import CDIReader
from cdi_layer.services.cdi_update import CDIUpdater


class DataArchitectAgent:
    def __init__(self, phase: int = 0):
        self.phase = phase

    def run(self, capability_bundle_id: str) -> dict:
        """Phase 0 stub."""
        cb = read_artifact(capability_bundle_id)
        validate_envelope(cb)
        task_id = cb["content"]["task_id"]

        reader = CDIReader(agent_name="data_architect", task_id=task_id)
        _ = reader.get_disciplinary_methods()

        bundle = create_artifact(
            artifact_type="context_bundle",
            producing_agent="data_architect",
            phase=self.phase,
            content={
                "task_id": task_id,
                "status": "STUB_PHASE_0",
                "note": "Full Data Architect Agent implementation begins in Phase 1.",
                "schema_scope": [],
                "proposed_models": [],
            },
            provenance=[capability_bundle_id],
            confidence_score=0.0,
            known_limitations=["Phase 0 stub"],
        )
        path = write_artifact(bundle)

        updater = CDIUpdater(agent_name="data_architect", task_id=task_id)
        updater.record_non_activation(reader.get_queried_domains())

        return {"context_bundle_id": bundle["artifact_id"], "path": str(path)}
