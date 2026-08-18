"""
Notification Mechanism — governance/notification/notification.py
Deliverable 0.11.

In-app notification tray + AIMS Mode A integration.
HIGH/CRITICAL notifications are routed prominently.
Review Queue monitoring is always live.

HIGH/CRITICAL notification channels cannot be disabled — Design Invariant enforcement.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from enum import Enum

BASE = Path(__file__).resolve().parents[2]
NOTIFICATION_LOG = BASE / "governance" / "notification" / "notification_log.jsonl"
AIMS_MODE_A_DIR = BASE / "aims" / "mode_a"
REVIEW_QUEUE_FILE = BASE / "governance" / "review_queue" / "review_queue.json"


class Severity(str, Enum):
    INFO = "INFO"
    OPERATIONAL = "OPERATIONAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NotificationCategory(str, Enum):
    GOVERNANCE = "Governance"
    OPERATIONAL = "Operational"
    CAPACITY = "Capacity"
    INTELLIGENCE = "Intelligence"
    SYSTEM = "System"


# Design Invariant: HIGH and CRITICAL channels cannot be disabled
UNDISABLEABLE_SEVERITIES = {Severity.HIGH, Severity.CRITICAL}


class NotificationMechanism:
    """
    Central notification system.
    All notifications route through here — never sent directly to AIMS Mode A.
    """

    def __init__(self):
        NOTIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        severity: Severity,
        category: NotificationCategory,
        title: str,
        message: str,
        source_agent: str,
        artifact_ref: Optional[str] = None,
        requires_action: bool = False,
        action_deadline: Optional[str] = None,
    ) -> str:
        """
        Send a notification. Returns notification_id.
        HIGH/CRITICAL notifications are always delivered — cannot be disabled.
        """
        notification_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        notification = {
            "notification_id": notification_id,
            "timestamp_utc": timestamp,
            "severity": severity.value,
            "category": category.value,
            "title": title,
            "message": message,
            "source_agent": source_agent,
            "artifact_ref": artifact_ref,
            "requires_action": requires_action,
            "action_deadline": action_deadline,
            "acknowledged": False,
            "acknowledged_at": None,
        }

        # Write to notification log
        with open(NOTIFICATION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(notification) + "\n")

        # HIGH/CRITICAL also write to AIMS Mode A
        if severity in (Severity.HIGH, Severity.CRITICAL):
            self._write_to_aims_mode_a(notification)

        # Console output for in-app display
        prefix = "🔴 CRITICAL" if severity == Severity.CRITICAL else \
                 "🟠 HIGH" if severity == Severity.HIGH else \
                 "🔵 OPERATIONAL" if severity == Severity.OPERATIONAL else \
                 "ℹ️  INFO"
        print(f"\n[{prefix}] {title}")
        print(f"  {message}")
        if requires_action:
            print(f"  → ACTION REQUIRED" + (f" by {action_deadline}" if action_deadline else ""))

        return notification_id

    def _write_to_aims_mode_a(self, notification: dict) -> None:
        """Write HIGH/CRITICAL notifications to AIMS Mode A log."""
        log_file = AIMS_MODE_A_DIR / "notification_log.jsonl"
        entry = {
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": notification["timestamp_utc"],
            "event_type": f"NOTIFICATION_{notification['severity']}",
            "notification_id": notification["notification_id"],
            "title": notification["title"],
            "message": notification["message"],
            "source_agent": notification["source_agent"],
            "artifact_ref": notification["artifact_ref"],
            "requires_action": notification["requires_action"],
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_pending_notifications(
        self,
        min_severity: Optional[Severity] = None,
        unacknowledged_only: bool = True,
    ) -> list[dict]:
        """Return pending notifications from the log."""
        severity_order = [Severity.INFO, Severity.OPERATIONAL, Severity.HIGH, Severity.CRITICAL]
        min_idx = severity_order.index(min_severity) if min_severity else 0

        if not NOTIFICATION_LOG.exists():
            return []

        notifications = []
        with open(NOTIFICATION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                n = json.loads(line.strip())
                n_severity = Severity(n["severity"])
                if severity_order.index(n_severity) < min_idx:
                    continue
                if unacknowledged_only and n.get("acknowledged"):
                    continue
                notifications.append(n)

        return sorted(notifications, key=lambda x: x["timestamp_utc"], reverse=True)

    def acknowledge(self, notification_id: str) -> None:
        """Mark a notification as acknowledged."""
        if not NOTIFICATION_LOG.exists():
            return
        lines = []
        with open(NOTIFICATION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                n = json.loads(line.strip())
                if n["notification_id"] == notification_id:
                    n["acknowledged"] = True
                    n["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                lines.append(json.dumps(n))
        with open(NOTIFICATION_LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


class ReviewQueueMonitor:
    """
    Monitors the Review Queue depth and triggers notifications at thresholds.
    Always live — cannot be disabled.
    """

    THRESHOLDS = {
        "green": (0, 4),
        "yellow": (5, 7),
        "orange": (8, 10),
        "red": (11, 12),
        "critical": (13, None),
    }

    def __init__(self):
        REVIEW_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.notifier = NotificationMechanism()
        if not REVIEW_QUEUE_FILE.exists():
            self._init_queue()

    def _init_queue(self):
        queue = {
            "queue_state": "green",
            "item_count": 0,
            "items": [],
            "history": [],
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
        with open(REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)

    def get_queue(self) -> dict:
        if not REVIEW_QUEUE_FILE.exists():
            self._init_queue()
        with open(REVIEW_QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_queue(self, queue: dict) -> None:
        queue["last_checked"] = datetime.now(timezone.utc).isoformat()
        with open(REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)

    def add_item(self, item: dict) -> str:
        """Add an item to the Review Queue. Returns item_id."""
        queue = self.get_queue()
        item_id = str(uuid.uuid4())
        item["item_id"] = item_id
        item["added_at"] = datetime.now(timezone.utc).isoformat()
        item["status"] = "pending"
        queue["items"].append(item)
        queue["item_count"] = len([i for i in queue["items"] if i["status"] == "pending"])

        old_state = queue["queue_state"]
        new_state = self._compute_state(queue["item_count"])
        queue["queue_state"] = new_state

        self._save_queue(queue)

        if new_state != old_state:
            self._notify_state_change(old_state, new_state, queue["item_count"])

        return item_id

    def _compute_state(self, count: int) -> str:
        for state, (lo, hi) in self.THRESHOLDS.items():
            if hi is None:
                if count >= lo:
                    return state
            elif lo <= count <= hi:
                return state
        return "green"

    def _notify_state_change(self, old_state: str, new_state: str, count: int) -> None:
        state_severity = {
            "green": Severity.INFO,
            "yellow": Severity.OPERATIONAL,
            "orange": Severity.OPERATIONAL,
            "red": Severity.HIGH,
            "critical": Severity.CRITICAL,
        }
        severity = state_severity[new_state]
        self.notifier.send(
            severity=severity,
            category=NotificationCategory.CAPACITY,
            title=f"Review Queue: {old_state.upper()} → {new_state.upper()}",
            message=f"Review Queue now has {count} pending items (state: {new_state}). "
                    + ("Phase 7 PAUSED." if new_state == "red" else "")
                    + ("ALL PHASE 7 SUSPENDED. Team expansion flag activated." if new_state == "critical" else ""),
            source_agent="system",
            requires_action=new_state in ("red", "critical"),
        )
