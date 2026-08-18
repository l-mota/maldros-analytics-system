"""
Artifact Envelope — lib/artifact.py
Creates, validates, and stores inter-agent hand-off artifacts.

All artifacts are written once, content-hashed, immutable.
Corrections produce new versioned artifacts referencing the original.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


VALID_ARTIFACT_TYPES = {
    "capability_bundle",
    "context_bundle",
    "evidence_bundle",
    "statistical_result",
    "red_team_report",
    "discovery_report",
    "aims_mode_a",
    "aims_mode_b",
    "diagnostic_result",
    "healing_record",
    "telemetry_triple",
    "promotion_gate_decision",
    "few_shot_exemplar",
    "algorithmic_rule_cycle",
    "invention_pipeline_report",
    # Phase 6
    "bottleneck_report",
    "phase7_proposal",
    "sandbox_test_result",
}

VALID_AGENTS = {
    "orchestrator", "analyst", "statistician", "storyteller",
    "data_architect", "diagnostic", "healing", "red_team",
    "promotion_gate", "telemetry_capture", "forge",
    # Phase 6
    "bottleneck_detector", "phase7_proposer",
}

REQUIRED_ENVELOPE_FIELDS = {
    "artifact_id", "artifact_type", "schema_version", "phase_of_origin",
    "producing_agent", "timestamp_utc", "provenance", "content_hash",
    "confidence_score", "known_limitations", "content",
}


def create_artifact(
    artifact_type: str,
    producing_agent: str,
    phase: int,
    content: dict,
    provenance: Optional[list[str]] = None,
    confidence_score: float = 0.0,
    known_limitations: Optional[list[str]] = None,
) -> dict:
    """
    Create a new artifact envelope. Content is immediately hashed.
    Returns the complete artifact dict — caller must then write it via write_artifact().
    """
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(f"Invalid artifact_type: {artifact_type}. Valid: {VALID_ARTIFACT_TYPES}")
    if producing_agent not in VALID_AGENTS:
        raise ValueError(f"Invalid producing_agent: {producing_agent}. Valid: {VALID_AGENTS}")
    if not 0 <= confidence_score <= 1.0:
        raise ValueError(f"confidence_score must be 0.0–1.0, got: {confidence_score}")

    content_str = json.dumps(content, sort_keys=True, ensure_ascii=False)
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()

    return {
        "artifact_id": str(uuid.uuid4()),
        "artifact_type": artifact_type,
        "schema_version": "1.0.0",
        "phase_of_origin": phase,
        "producing_agent": producing_agent,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance or [],
        "content_hash": content_hash,
        "confidence_score": confidence_score,
        "known_limitations": known_limitations or [],
        "content": content,
    }


def write_artifact(artifact: dict) -> Path:
    """
    Write an artifact to the artifact store. Immutable — never overwrites.
    Returns the file path.
    Raises if artifact_id already exists (immutability enforcement).
    """
    validate_envelope(artifact)
    artifact_id = artifact["artifact_id"]
    artifact_type = artifact["artifact_type"]

    type_dir = ARTIFACTS_DIR / artifact_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / f"{artifact_id}.json"

    if path.exists():
        raise FileExistsError(
            f"Artifact {artifact_id} already exists at {path}. "
            "Artifacts are immutable. Create a new artifact referencing this one in provenance."
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)

    return path


def read_artifact(artifact_id: str) -> dict:
    """Read an artifact by ID. Raises if not found."""
    for type_dir in ARTIFACTS_DIR.iterdir():
        if not type_dir.is_dir():
            continue
        path = type_dir / f"{artifact_id}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Artifact {artifact_id} not found in {ARTIFACTS_DIR}")


def validate_envelope(artifact: dict) -> bool:
    """
    Validate artifact envelope against required fields and type constraints.
    Raises ValueError on any violation.
    Used by Diagnostic Agent on every hand-off receipt.
    """
    missing = REQUIRED_ENVELOPE_FIELDS - set(artifact.keys())
    if missing:
        raise ValueError(f"Artifact envelope missing required fields: {missing}")

    if artifact["artifact_type"] not in VALID_ARTIFACT_TYPES:
        raise ValueError(f"Invalid artifact_type: {artifact['artifact_type']}")

    if artifact["producing_agent"] not in VALID_AGENTS:
        raise ValueError(f"Invalid producing_agent: {artifact['producing_agent']}")

    if not isinstance(artifact["provenance"], list):
        raise ValueError("provenance must be a list")

    if not isinstance(artifact["known_limitations"], list):
        raise ValueError("known_limitations must be a list")

    score = artifact.get("confidence_score", -1)
    if not (0.0 <= score <= 1.0):
        raise ValueError(f"confidence_score out of range: {score}")

    # Verify content hash integrity
    content_str = json.dumps(artifact["content"], sort_keys=True, ensure_ascii=False)
    expected_hash = hashlib.sha256(content_str.encode()).hexdigest()
    if artifact["content_hash"] != expected_hash:
        raise ValueError(
            f"content_hash mismatch — artifact may have been tampered with. "
            f"Expected {expected_hash[:16]}..., got {artifact['content_hash'][:16]}..."
        )

    return True


def create_correction(original_artifact_id: str, corrected_content: dict,
                       producing_agent: str, phase: int,
                       correction_reason: str,
                       confidence_score: float = 0.0,
                       known_limitations: Optional[list[str]] = None) -> dict:
    """
    Create a corrected version of an artifact.
    The original artifact is referenced in provenance — it is never modified.
    """
    original = read_artifact(original_artifact_id)
    corrected_content["correction_of"] = original_artifact_id
    corrected_content["correction_reason"] = correction_reason

    return create_artifact(
        artifact_type=original["artifact_type"],
        producing_agent=producing_agent,
        phase=phase,
        content=corrected_content,
        provenance=[original_artifact_id] + original.get("provenance", []),
        confidence_score=confidence_score,
        known_limitations=known_limitations or [],
    )
