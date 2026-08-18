"""
lib/telemetry.py
Phase 4 — Telemetry Capture

Captures (agent_output, human_edit, accepted_output) triples from every analyst
correction. Computes structural diffs and clusters edit patterns.

Storage: telemetry/triples/<triple_id>.json  (immutable once written)
         telemetry/patterns/                  (cluster summaries, re-computed on demand)

Diff strategy:
  - Narrative outputs (str):          word-level diff via difflib
  - Python code outputs (str):        AST-level diff via ast module
  - Structured outputs (dict/list):   recursive JSON diff

Edit pattern classification is deterministic (L1) and feeds the Promotion Gate.
Phase 3 healing step 5 writes correction triples here after every heal cycle.
"""

import ast
import difflib
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
TELEMETRY_DIR = BASE / "telemetry"
TRIPLES_DIR = TELEMETRY_DIR / "triples"
PATTERNS_DIR = TELEMETRY_DIR / "patterns"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _is_python_code(text: str) -> bool:
    if not isinstance(text, str):
        return False
    markers = ("def ", "import ", "class ", "return ", "    ")
    return sum(1 for m in markers if m in text) >= 2


# ─── diff computation ─────────────────────────────────────────────────────────

def compute_diff(original: Any, edited: Any) -> dict:
    """
    Compute a structural diff between original and edited output.
    Returns a diff record with: diff_type, edit_distance, change_summary, raw_diff.
    """
    if isinstance(original, str) and isinstance(edited, str):
        if _is_python_code(original) and _is_python_code(edited):
            return _ast_diff(original, edited)
        return _narrative_diff(original, edited)
    elif isinstance(original, (dict, list)) and isinstance(edited, (dict, list)):
        return _json_diff(original, edited)
    return _narrative_diff(str(original), str(edited))


def _narrative_diff(original: str, edited: str) -> dict:
    orig_words = original.split()
    edit_words = edited.split()
    matcher = difflib.SequenceMatcher(None, orig_words, edit_words)
    ratio = matcher.ratio()
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changes.append({
                "op": tag,
                "original": " ".join(orig_words[i1:i2]),
                "edited": " ".join(edit_words[j1:j2]),
            })
    return {
        "diff_type": "narrative",
        "similarity_ratio": round(ratio, 4),
        "edit_distance": round(1.0 - ratio, 4),
        "change_count": len(changes),
        "change_summary": changes[:10],
        "raw_diff": list(difflib.unified_diff(
            original.splitlines(), edited.splitlines(), lineterm="", n=2
        ))[:50],
    }


def _ast_diff(original: str, edited: str) -> dict:
    try:
        orig_nodes = {type(n).__name__ for n in ast.walk(ast.parse(original))}
        edit_nodes = {type(n).__name__ for n in ast.walk(ast.parse(edited))}
        added = sorted(edit_nodes - orig_nodes)
        removed = sorted(orig_nodes - edit_nodes)
        diff_lines = list(difflib.unified_diff(
            original.splitlines(), edited.splitlines(), lineterm="", n=1
        ))
        changed_lines = sum(
            1 for l in diff_lines
            if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
        )
        total_lines = max(len(original.splitlines()), 1)
        edit_distance = min(changed_lines / total_lines, 1.0)
        return {
            "diff_type": "ast",
            "similarity_ratio": round(1.0 - edit_distance, 4),
            "edit_distance": round(edit_distance, 4),
            "ast_nodes_added": added,
            "ast_nodes_removed": removed,
            "lines_changed": changed_lines,
            "raw_diff": diff_lines[:50],
        }
    except SyntaxError:
        return _narrative_diff(original, edited)


def _count_leaves(obj: Any, count: int = 0) -> int:
    if isinstance(obj, dict):
        for v in obj.values():
            count = _count_leaves(v, count)
    elif isinstance(obj, list):
        for item in obj:
            count = _count_leaves(item, count)
    else:
        count += 1
    return count


def _json_diff(original: Any, edited: Any) -> dict:
    changes = []

    def _walk(orig, edit, p: str) -> None:
        if type(orig) != type(edit):
            changes.append({"path": p, "op": "type_change",
                            "from": type(orig).__name__, "to": type(edit).__name__})
            return
        if isinstance(orig, dict):
            for k in set(orig) | set(edit):
                cp = f"{p}.{k}" if p else k
                if k not in orig:
                    changes.append({"path": cp, "op": "added"})
                elif k not in edit:
                    changes.append({"path": cp, "op": "removed"})
                else:
                    _walk(orig[k], edit[k], cp)
        elif isinstance(orig, list):
            for i, (a, b) in enumerate(zip(orig, edit)):
                _walk(a, b, f"{p}[{i}]")
            if len(orig) != len(edit):
                changes.append({"path": p, "op": "length_change",
                                "from": len(orig), "to": len(edit)})
        else:
            if orig != edit:
                changes.append({"path": p, "op": "value_change",
                                "from": str(orig)[:100], "to": str(edit)[:100]})

    _walk(original, edited, "")
    total_keys = max(_count_leaves(original), 1)
    edit_distance = min(len(changes) / total_keys, 1.0)
    return {
        "diff_type": "json_structural",
        "similarity_ratio": round(1.0 - edit_distance, 4),
        "edit_distance": round(edit_distance, 4),
        "change_count": len(changes),
        "change_summary": changes[:10],
    }


# ─── edit pattern classification (L1 deterministic) ──────────────────────────

def classify_edit_pattern(diff: dict) -> str:
    """
    Classify the edit pattern of a diff.
    Returns one of: structural | factual | stylistic | additive | reductive | unknown
    """
    diff_type = diff.get("diff_type", "narrative")
    distance = diff.get("edit_distance", 0.0)
    changes = diff.get("change_summary", [])

    if diff_type == "ast":
        if diff.get("ast_nodes_added") or diff.get("ast_nodes_removed"):
            return "structural"
        return "stylistic" if distance < 0.2 else "factual"

    if diff_type == "json_structural":
        if distance == 0.0:
            return "stylistic"
        ops = [c.get("op") for c in changes]
        if "added" in ops:
            return "additive"
        if "removed" in ops:
            return "reductive"
        return "factual"

    # Narrative
    if distance == 0.0:
        return "stylistic"
    if distance < 0.1:
        return "stylistic"
    changes_text = json.dumps(changes)
    if any(c.isdigit() for c in changes_text) and distance > 0.05:
        return "factual"
    if distance < 0.3:
        return "stylistic"
    if distance < 0.8:
        return "factual"
    return "structural"


# ─── TelemetryCapture ─────────────────────────────────────────────────────────

class TelemetryCapture:
    """
    Phase 4 telemetry capture.

    Records (agent_output, human_edit, accepted_output) correction triples,
    computes structural diffs, and clusters edit patterns to feed the Promotion Gate.

    Usage:
        tc = TelemetryCapture()
        triple_id = tc.record_triple(
            agent_output=original_output,
            human_edit=intermediate_edit,   # may equal accepted_output
            accepted_output=final_version,
            task_id="task-uuid",
            agent_name="analyst",
            query_class="api_abuse_investigation",
            edit_context="Changed rate figure from 0.03 to 0.031",
        )
    """

    def __init__(self):
        TRIPLES_DIR.mkdir(parents=True, exist_ok=True)
        PATTERNS_DIR.mkdir(parents=True, exist_ok=True)

    def record_triple(
        self,
        agent_output: Any,
        human_edit: Any,
        accepted_output: Any,
        task_id: str,
        agent_name: str,
        query_class: str,
        edit_context: str = "",
    ) -> str:
        """
        Record a correction triple. Returns the triple_id.
        Triples are immutable once written. A new correction produces a new triple.
        """
        triple_id = str(uuid.uuid4())
        diff = compute_diff(agent_output, accepted_output)
        edit_pattern = classify_edit_pattern(diff)

        triple = {
            "triple_id": triple_id,
            "task_id": task_id,
            "agent_name": agent_name,
            "query_class": query_class,
            "timestamp_utc": _now_iso(),
            "agent_output_hash": _content_hash(agent_output),
            "accepted_output_hash": _content_hash(accepted_output),
            "agent_output": agent_output,
            "human_edit": human_edit,
            "accepted_output": accepted_output,
            "diff": diff,
            "edit_pattern": edit_pattern,
            "edit_context": edit_context,
            "promotion_status": "PENDING",
        }

        path = TRIPLES_DIR / f"{triple_id}.json"
        path.write_text(json.dumps(triple, indent=2, default=str), encoding="utf-8")
        print(
            f"[Telemetry] Triple recorded: {triple_id[:8]}... "
            f"| class={query_class} | pattern={edit_pattern} "
            f"| distance={diff.get('edit_distance', 0):.3f}"
        )
        return triple_id

    def get_triple(self, triple_id: str) -> dict:
        path = TRIPLES_DIR / f"{triple_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Triple not found: {triple_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def update_promotion_status(self, triple_id: str, status: str, category: str = "") -> None:
        path = TRIPLES_DIR / f"{triple_id}.json"
        if not path.exists():
            return
        triple = json.loads(path.read_text(encoding="utf-8"))
        triple["promotion_status"] = status
        if category:
            triple["promotion_category"] = category
        path.write_text(json.dumps(triple, indent=2, default=str), encoding="utf-8")

    def get_all_triples(self) -> list[dict]:
        triples = []
        for p in TRIPLES_DIR.glob("*.json"):
            try:
                triples.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return sorted(triples, key=lambda t: t.get("timestamp_utc", ""))

    def get_triples_by_class(self, query_class: str) -> list[dict]:
        return [t for t in self.get_all_triples() if t.get("query_class") == query_class]

    def get_triples_by_agent(self, agent_name: str) -> list[dict]:
        return [t for t in self.get_all_triples() if t.get("agent_name") == agent_name]

    def get_cluster_summary(self) -> dict:
        """
        Cluster all triples by edit pattern and query class.
        Returns a summary dict used by CDI Layer phase7_signals.
        """
        triples = self.get_all_triples()
        if not triples:
            return {"total_triples": 0, "clusters": {}, "query_classes": []}

        clusters: dict = {}
        class_counts: dict = {}
        agent_counts: dict = {}
        distances: list = []

        for t in triples:
            ep = t.get("edit_pattern", "unknown")
            qc = t.get("query_class", "unknown")
            an = t.get("agent_name", "unknown")
            dist = t.get("diff", {}).get("edit_distance", 0.0)

            cl = clusters.setdefault(ep, {"count": 0, "query_classes": [], "agents": []})
            cl["count"] += 1
            if qc not in cl["query_classes"]:
                cl["query_classes"].append(qc)
            if an not in cl["agents"]:
                cl["agents"].append(an)

            class_counts[qc] = class_counts.get(qc, 0) + 1
            agent_counts[an] = agent_counts.get(an, 0) + 1
            distances.append(dist)

        return {
            "total_triples": len(triples),
            "clusters": clusters,
            "query_classes": list(class_counts.keys()),
            "query_class_counts": class_counts,
            "agent_counts": agent_counts,
            "mean_edit_distance": round(sum(distances) / len(distances), 4),
            "pending_promotion": sum(1 for t in triples if t.get("promotion_status") == "PENDING"),
            "promoted": sum(1 for t in triples if t.get("promotion_status") == "PROMOTED"),
            "quarantined": sum(1 for t in triples if t.get("promotion_status") == "QUARANTINED"),
        }

    def compute_edit_distance_curve(self, query_class: str) -> list[dict]:
        """
        Compute the edit-distance improvement curve for a query class over time.
        Returns [{cycle, triple_id, timestamp, edit_distance, promotion_status}, ...]
        Used for deliverable 4.6 compounding demonstration.
        """
        triples = self.get_triples_by_class(query_class)
        return [
            {
                "cycle": i,
                "triple_id": t["triple_id"][:8],
                "timestamp": t.get("timestamp_utc", ""),
                "edit_distance": t.get("diff", {}).get("edit_distance", 0.0),
                "edit_pattern": t.get("edit_pattern", "unknown"),
                "promotion_status": t.get("promotion_status", "PENDING"),
            }
            for i, t in enumerate(triples, start=1)
        ]
