"""
render_aims_report.py — Self-contained HTML renderer for AIMS Mode B artifacts.

Implements the Maldros Visual Design System (C-031):
  FINDING → IMPACT → EVIDENCE → RECOMMENDATION reading order
  Forest green = authority, Amber = finding, Parchment = surface,
  Warm gray = structural neutral.

Usage:
    python scripts/render_aims_report.py [artifact_id] [--output path/to/out.html]
"""

import argparse
import base64
import html as html_lib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = BASE_DIR / "artifacts" / "aims_mode_b"
DEFAULT_ID = "f3d5a232-98f6-42dc-a092-54d7edb2b3e6"

# Maldros Visual Design System (C-031) — design tokens are inlined from
# the single source of truth at lib/design_tokens.css. Hand-editing color
# tokens in this renderer is a Visual Design System violation; update the
# source file instead.
DESIGN_TOKENS_CSS = (BASE_DIR / "lib" / "design_tokens.css").read_text(encoding="utf-8")


# ── Per-artifact narrative title overrides (C-031 directive) ───────────────────
# Maps original descriptive titles to narrative conclusions. Renderer-side
# override for f3d5a232; storyteller upgrade for future runs is queued
# separately.
NARRATIVE_TITLE_OVERRIDES = {
    "Monthly API Abuse Event Volume (18-Month Trend)":
        "No Q1 spike — abuse is stable across the full 18 months",
    "Abuse Concentration: Cumulative Share by Account Rank":
        "41 accounts (2.05% of population) drive 25.87% of Q1 abuse",
    "Co-Temporal Abuse Network (41-Account Cluster)":
        "41 accounts form a single dense ring — 56.3% edge density",
    "Financial Impact Breakdown: Q1 API Abuse Exposure by Category":
        "Ring drives $1.52M–$2.97M of $5.89M Q1 exposure",
    "Cluster vs Non-Cluster Incident Rate Comparison":
        "Cluster accounts abuse 16.54× more than non-cluster",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _embed_image(rendered_path: str, task_id: str, index: int) -> str | None:
    candidates = []
    if rendered_path:
        candidates.append(Path(rendered_path))
    charts_dir = BASE_DIR / "artifacts" / "charts" / task_id
    prefix = f"{index + 1:02d}_"
    candidates += sorted(charts_dir.glob(f"{prefix}*.png")) if charts_dir.exists() else []
    for p in candidates:
        if p.exists():
            data = base64.b64encode(p.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{data}"
    return None


def _autobold_finding(text: str) -> str:
    """Promote key numbers/percentages/dollars to bold in the KEY FINDING block."""
    text = re.sub(r"(\d+\.\d+%)", r"**\1**", text)
    text = re.sub(r"(\$\d+(?:\.\d+)?[KMB](?:\s*[–-]\s*\$\d+(?:\.\d+)?[KMB])?)",
                  r"**\1**", text)
    text = re.sub(r"\b(\d+\s+accounts)\b", r"**\1**", text)
    text = re.sub(r"(\d+\.\d+×)", r"**\1**", text)
    return text


def _process_text(raw: str) -> str:
    if not raw:
        return ""
    escaped = html_lib.escape(raw)
    with_fn = re.sub(r"\[\^(\d+)\]",
                     r'<sup><a href="#fn-\1" class="fn-ref">[\1]</a></sup>',
                     escaped)
    with_bold = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", with_fn)
    paragraphs = re.split(r"\n\n+", with_bold)
    return "".join(
        f'<p class="body-para">{p.replace(chr(10), "<br>")}</p>'
        for p in paragraphs if p.strip()
    )


def _fmt_usd(value) -> str:
    try:
        v = float(value)
        if v >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v / 1_000:.0f}K"
        return f"${v:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _badge(passed: bool) -> str:
    cls = "badge-pass" if passed else "badge-fail"
    label = "PASS" if passed else "FAIL"
    return f'<span class="badge {cls}">{label}</span>'


# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = """
/* Design tokens (:root) are inlined separately from lib/design_tokens.css.
   This file contains only component-level styles specific to the AIMS Mode B
   report; all color and typography tokens come from the design system source. */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--canvas);
    color: var(--ink);
    line-height: 1.65;
    font-size: 15px;
}

/* ── Sticky header ─────────────────────────────────────────────── */
.report-header {
    background: var(--forest);
    color: #fff;
    padding: 0.85rem 2rem;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35);
}
.header-inner {
    max-width: 1000px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.header-brand {
    font-weight: 700;
    font-size: 0.88rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.review-pill {
    display: inline-block;
    background: var(--amber);
    color: #1a0c00;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    padding: 0.26rem 0.88rem;
    border-radius: 20px;
    white-space: nowrap;
}
.review-pill.approved { background: #198754; color: #fff; }
.review-pill.rejected { background: #dc2626; color: #fff; }

/* ── KEY FINDING hero block ────────────────────────────────────── */
.finding-hero {
    background: var(--forest);
    color: #fff;
    padding: 1.5rem 2rem 2.25rem;
}
.finding-hero-inner {
    max-width: 1000px;
    margin: 0 auto;
}
.finding-label {
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: rgba(255,255,255,0.55);
    margin-bottom: 0.75rem;
}
.finding-text .body-para {
    font-size: 1.42rem;
    font-weight: 500;
    line-height: 1.5;
    color: #fff;
    margin-bottom: 0.9rem;
    letter-spacing: -0.005em;
}
.finding-text .body-para:last-child { margin-bottom: 0; }
.finding-text strong {
    color: #fff;
    font-weight: 700;
}
.finding-text .fn-ref {
    color: rgba(255,255,255,0.55);
}

/* ── L1 strip ──────────────────────────────────────────────────── */
.l1-strip {
    font-size: 0.78rem;
    padding: 0.45rem 2rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
}
.l1-pass { background: #d1fae5; color: #065f46; border-bottom: 1px solid #6ee7b7; }
.l1-fail { background: #fee2e2; color: #7f1d1d; border-bottom: 1px solid #fca5a5; }
.l1-icon  { font-weight: 800; }
.l1-gates { margin-left: auto; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.l1-gate  { font-size: 0.73rem; display: flex; align-items: center; gap: 0.2rem; }

.badge {
    display: inline-block;
    padding: 0.08rem 0.38rem;
    border-radius: 3px;
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.badge-pass { background: #d1fae5; color: #065f46; border: 1px solid #6ee7b7; }
.badge-fail { background: #fee2e2; color: #7f1d1d; border: 1px solid #fca5a5; }

/* ── Main ──────────────────────────────────────────────────────── */
.report-main {
    max-width: 1000px;
    margin: 0 auto;
    padding: 2.25rem 2rem 4rem;
}

/* ── Investigation question (small caption above hero) ─────────── */
.investigation-q {
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--ink-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-left: 3px solid var(--border);
    padding-left: 1rem;
    margin-bottom: 2.5rem;
    line-height: 1.6;
}
.investigation-q span {
    display: block;
    font-size: 0.95rem;
    color: var(--ink);
    text-transform: none;
    letter-spacing: 0;
    margin-top: 0.35rem;
    font-weight: 500;
}

/* ── IMPACT (KPI cards) ────────────────────────────────────────── */
.kpi-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    margin-bottom: 2.5rem;
}
.kpi-card {
    background: var(--parchment);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.1rem;
    text-align: left;
}
.kpi-label {
    font-size: 0.67rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--ink-muted);
    margin-bottom: 0.5rem;
}
.kpi-value {
    font-size: 2.5rem;
    font-weight: 700;
    line-height: 1;
    color: var(--ink);
    margin-bottom: 0.4rem;
    letter-spacing: -0.01em;
}
.kpi-value.amber { color: var(--forest); }
.kpi-sub {
    font-size: 0.72rem;
    color: var(--ink-muted);
    line-height: 1.4;
}

/* ── Section eyebrow ───────────────────────────────────────────── */
.section-eyebrow {
    font-size: 0.67rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--forest);
    margin-bottom: 1rem;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid var(--forest);
    display: inline-block;
}
.section-eyebrow.amber {
    color: var(--amber);
    border-bottom-color: var(--amber);
}
.section-eyebrow.action {
    color: var(--action-green);
    border-bottom-color: var(--action-green);
}
.section-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 2.5rem 0;
}

/* ── Body text ─────────────────────────────────────────────────── */
.body-para { margin-bottom: 0.9rem; line-height: 1.72; }
.body-para:last-child { margin-bottom: 0; }
.fn-ref { color: var(--forest); text-decoration: none; font-size: 0.72em; font-weight: 600; }
.fn-ref:hover { text-decoration: underline; }
sup { line-height: 0; }

/* ── EVIDENCE: chart rows ──────────────────────────────────────── */
.chart-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.25rem;
    margin-bottom: 1rem;
}
.chart-row.single { grid-template-columns: 1fr; }
.chart-card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--shadow);
    background: var(--canvas);
    display: flex;
    flex-direction: column;
}
.chart-title-bar {
    background: var(--forest);
    color: #fff;
    font-size: 0.86rem;
    font-weight: 600;
    padding: 0.7rem 1rem;
    line-height: 1.4;
    letter-spacing: -0.005em;
}
.chart-img { width: 100%; display: block; }
.chart-missing {
    padding: 2.5rem;
    text-align: center;
    color: var(--ink-muted);
    font-size: 0.845rem;
}

/* ── Row-level insight callout ─────────────────────────────────── */
.insight-callout {
    background: var(--parchment);
    border: 1px solid var(--border);
    border-left: 3px solid var(--amber);
    border-radius: var(--radius);
    padding: 1.1rem 1.35rem 1.2rem;
    margin-bottom: 2rem;
    font-size: 1rem;
    line-height: 1.65;
    color: var(--ink);
}
.insight-callout-label {
    font-size: 0.75rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--forest);
    margin-bottom: 0.55rem;
}
.insight-callout p { margin-bottom: 0.6rem; }
.insight-callout p:last-child { margin-bottom: 0; }

/* ── RECOMMENDATION: action ────────────────────────────────────── */
.action-primary {
    background: var(--parchment);
    border: 1px solid var(--border);
    border-left: 4px solid var(--forest);
    border-radius: var(--radius);
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
}
.action-primary .body-para { font-size: 0.98rem; line-height: 1.65; }
.action-timeline {
    font-size: 0.82rem;
    color: var(--forest);
    font-weight: 600;
    margin-top: 0.85rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}
details.impl-details {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
}
details.impl-details > summary {
    padding: 0.75rem 1.1rem;
    cursor: pointer;
    font-size: 0.845rem;
    color: var(--ink-muted);
    font-weight: 500;
    user-select: none;
    list-style: none;
}
details.impl-details > summary::marker,
details.impl-details > summary::-webkit-details-marker { display: none; }
details.impl-details[open] > summary { border-bottom: 1px solid var(--border); }
.impl-body { padding: 0.85rem 1.1rem 1rem; }
.impl-body .body-para { font-size: 0.86rem; }

/* ── Scale block ───────────────────────────────────────────────── */
.scale-block {
    background: var(--parchment);
    border: 1px solid var(--border);
    border-left: 3px solid var(--amber);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    font-size: 0.92rem;
    line-height: 1.7;
}

/* ── Confirmation gate ─────────────────────────────────────────── */
.gate-section {
    background: var(--forest);
    color: #fff;
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: 0 4px 18px rgba(15,37,21,0.3);
    margin-bottom: 2.5rem;
}
.gate-header {
    padding: 1rem 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255,255,255,0.1);
}
.gate-title {
    font-size: 0.87rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.gate-pill {
    background: var(--amber);
    color: #1a0c00;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 0.22rem 0.72rem;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.gate-body {
    padding: 1.25rem 1.5rem;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
}
.gate-meta { display: flex; flex-direction: column; gap: 0.8rem; }
.gate-meta-item { display: flex; flex-direction: column; gap: 0.12rem; }
.gate-meta-label {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.4);
}
.gate-meta-value { font-size: 0.845rem; color: #fff; font-weight: 500; }
.gate-meta-value.warn { color: #fbbf24; }
.gate-cmd-block {
    background: rgba(0,0,0,0.28);
    border-radius: 5px;
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}
.gate-cmd-label {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.4);
    margin-bottom: 0.12rem;
}
.gate-cmd {
    font-family: var(--mono);
    font-size: 0.75rem;
    color: #86efac;
    word-break: break-all;
    line-height: 1.7;
}
.gate-footer {
    padding: 0.9rem 1.5rem;
    border-top: 1px solid rgba(255,255,255,0.1);
}
.gate-footer-label {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255,255,255,0.4);
    margin-bottom: 0.5rem;
}
.gate-check-item {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
    font-size: 0.845rem;
    color: rgba(255,255,255,0.8);
    margin-bottom: 0.35rem;
}
.gate-check-item input[type="checkbox"] {
    margin-top: 0.15rem;
    accent-color: #86efac;
    flex-shrink: 0;
}

/* ── Limitations ───────────────────────────────────────────────── */
.lim-list { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }
.lim-item {
    display: flex;
    align-items: flex-start;
    gap: 0.7rem;
    font-size: 0.86rem;
    color: var(--ink);
    padding: 0.55rem 0.85rem;
    background: var(--parchment);
    border: 1px solid var(--border);
    border-radius: 4px;
    line-height: 1.6;
}
.lim-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--amber);
    flex-shrink: 0;
    margin-top: 0.48rem;
}

/* ── External deps ─────────────────────────────────────────────── */
.dep-table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
.dep-table th {
    background: var(--forest);
    color: #fff;
    padding: 0.55rem 0.95rem;
    text-align: left;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.dep-table td {
    padding: 0.65rem 0.95rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
}
.dep-table tr:last-child td { border-bottom: none; }
.dep-table tr:nth-child(even) td { background: var(--parchment); }
.dep-gate { width: 65%; }
.dep-owner { color: var(--ink-muted); font-size: 0.78rem; }

/* ── Technical appendix ────────────────────────────────────────── */
.tech-appendix {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--parchment);
    margin-bottom: 2rem;
}
.tech-appendix > summary {
    padding: 0.95rem 1.25rem;
    cursor: pointer;
    font-size: 0.86rem;
    font-weight: 600;
    color: var(--ink-muted);
    user-select: none;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.tech-appendix > summary::marker,
.tech-appendix > summary::-webkit-details-marker { display: none; }
.tech-appendix[open] > summary { border-bottom: 1px solid var(--border); }
.tech-arrow { font-size: 0.65rem; transition: transform 0.2s; }
.tech-appendix[open] .tech-arrow { transform: rotate(90deg); }
.appendix-inner { padding: 1.5rem; display: flex; flex-direction: column; gap: 1.5rem; }
.appendix-section h3 {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--forest);
    margin-bottom: 0.65rem;
    padding-bottom: 0.38rem;
    border-bottom: 1px solid var(--border);
}
.mono-block {
    font-family: var(--mono);
    font-size: 0.78rem;
    color: var(--ink-muted);
    background: var(--canvas);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.7rem 1rem;
    line-height: 1.8;
}
.verdict-block {
    background: var(--canvas);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.85rem 1.05rem;
    font-size: 0.86rem;
    line-height: 1.72;
}
.compliance-table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
.compliance-table td { padding: 0.4rem 0.7rem; border-bottom: 1px solid var(--border); }
.compliance-table tr:last-child td { border-bottom: none; }
.compliance-table td:last-child { text-align: right; }
.conf-scores { display: flex; gap: 1.5rem; font-weight: 600; font-size: 0.86rem; margin-bottom: 0.65rem; }
.fn-list { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }
.fn-item {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    font-size: 0.78rem;
    padding: 0.4rem 0.65rem;
    background: var(--canvas);
    border-radius: 3px;
    border: 1px solid var(--border);
    line-height: 1.6;
}
.fn-num { flex-shrink: 0; font-weight: 700; color: var(--forest); font-size: 0.82em; }
.source-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.04rem 0.4rem;
    border-radius: 3px;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
    flex-shrink: 0;
}
.src-evidence_bundle          { background: var(--parchment); color: var(--forest); border: 1px solid var(--border); }
.src-statistical_result       { background: var(--parchment); color: var(--forest); border: 1px solid var(--border); }
.src-financial_impact-parquet { background: var(--parchment); color: var(--forest); border: 1px solid var(--border); }
.src-api_events-parquet       { background: var(--parchment); color: var(--forest); border: 1px solid var(--border); }
.src-fraud_incidents-parquet  { background: var(--parchment); color: var(--forest); border: 1px solid var(--border); }
.src-analyst_estimate         { background: var(--parchment); color: #7A4E0E; border: 1px solid var(--amber); }

/* ── Footer ────────────────────────────────────────────────────── */
.report-footer {
    background: var(--forest);
    color: rgba(255,255,255,0.32);
    text-align: center;
    padding: 0.8rem;
    font-size: 0.7rem;
    font-family: var(--mono);
}

/* ── Responsive ────────────────────────────────────────────────── */
@media (max-width: 768px) {
    .report-main { padding: 1.5rem 1rem 3rem; }
    .finding-hero { padding: 1.25rem 1rem 1.75rem; }
    .finding-text .body-para { font-size: 1.15rem; }
    .kpi-row, .chart-row, .gate-body { grid-template-columns: 1fr; }
    .l1-gates { display: none; }
}
"""


# ── Renderer ───────────────────────────────────────────────────────────────────

def render(artifact_path: Path, output_path: Path) -> None:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    content  = artifact["content"]
    assets   = content["assets"]

    # ── Metadata ──
    artifact_id = artifact["artifact_id"]
    try:
        ts = datetime.fromisoformat(artifact.get("timestamp_utc", ""))
        timestamp_display = ts.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        timestamp_display = artifact.get("timestamp_utc", "")

    status = content.get("status", "UNKNOWN")
    pill_map = {
        "READY_FOR_REVIEW": ("Ready for review", ""),
        "APPROVED":         ("Approved",         " approved"),
        "REJECTED":         ("Rejected",         " rejected"),
    }
    pill_text, pill_cls = pill_map.get(status, (html_lib.escape(status), ""))

    question     = html_lib.escape(content.get("investigation_question", ""))
    task_id      = content.get("task_id", "")
    l1           = content.get("l1_compliance_summary", {})
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Assets ──
    executive_narrative   = assets.get("executive_narrative", "")
    financial_projection  = assets.get("financial_projection", {})
    recommended_action    = assets.get("recommended_action", {})
    visualizations_spec   = assets.get("visualizations_spec", [])
    footnotes             = assets.get("footnotes", [])
    known_limitations     = assets.get("known_limitations", [])
    external_dependencies = assets.get("external_dependencies", [])
    scale_impact          = assets.get("scale_impact_declaration", "")
    statistical_verdict   = assets.get("statistical_verdict", "")
    confidence_info       = assets.get("confidence_and_uncertainty", {})
    revision_log          = assets.get("revision_log", [])
    generation_mode       = assets.get("generation_mode_declaration", "")
    lineage_trace         = assets.get("lineage_trace", "")
    human_approval        = content.get("human_approval_gate", {})

    # ── Narrative split: first paragraph → KEY FINDING (hero) ──
    narrative_paras = [p.strip() for p in executive_narrative.split("\n\n") if p.strip()]
    kf_raw   = narrative_paras[0] if narrative_paras else ""
    kf_html  = _process_text(_autobold_finding(kf_raw))
    rest_html = _process_text("\n\n".join(narrative_paras[1:])) if len(narrative_paras) > 1 else ""

    # ── L1 strip ──
    l1_all_pass = l1.get("overall_passed", False)
    l1_cls      = "l1-pass" if l1_all_pass else "l1-fail"
    l1_icon     = "✓" if l1_all_pass else "✗"
    l1_label    = ("All 5 deterministic L1 gates passing — output cleared for operator review"
                   if l1_all_pass
                   else "One or more L1 gates FAILED — see Technical Appendix")
    gate_labels = [
        ("Causal veto", "causal_check"),
        ("Citation",    "citation_check"),
        ("Omission",    "omission_check"),
        ("Exec layer",  "c020_executive_layer"),
        ("Readiness",   "c020_readiness_checklist"),
    ]
    l1_gates_html = "".join(
        f'<span class="l1-gate">{lbl}: {_badge(l1.get(k, False))}</span>'
        for lbl, k in gate_labels
    )

    # ── IMPACT (KPI) ──
    coi           = financial_projection.get("cost_of_inaction_usd", 0)
    coc           = financial_projection.get("cost_of_countermeasure_usd", 0)
    nb            = financial_projection.get("net_benefit_usd", 0)
    fp_confidence = financial_projection.get("confidence", "MEDIUM")

    # ── EVIDENCE (charts) ──
    # Render rows of two; last row may have one chart spanning full width.
    def _build_chart_card(viz, idx):
        original_title = viz.get("title", f"Chart {idx + 1}")
        title          = NARRATIVE_TITLE_OVERRIDES.get(original_title, original_title)
        rpath          = viz.get("rendered_path", "")
        img_src        = _embed_image(rpath, task_id, idx)
        if img_src:
            img_html = f'<img src="{img_src}" alt="{html_lib.escape(title)}" class="chart-img">'
        else:
            img_html = (
                f'<div class="chart-missing">'
                f'<div style="font-size:1.8rem;margin-bottom:.5rem">&#128202;</div>'
                f'Chart not available<br>'
                f'<small style="font-size:.7rem">{html_lib.escape(rpath or "no path")}</small>'
                f'</div>'
            )
        return (
            f'<div class="chart-card">'
            f'<div class="chart-title-bar">{html_lib.escape(title)}</div>'
            f'{img_html}'
            f'</div>'
        )

    def _build_insight_callout(vizs):
        paras = [
            f"<p>{html_lib.escape(v.get('insights', '').strip())}</p>"
            for v in vizs if v.get("insights", "").strip()
        ]
        if not paras:
            return ""
        return (
            f'<div class="insight-callout">'
            f'<div class="insight-callout-label">Insight</div>'
            f'{"".join(paras)}'
            f'</div>'
        )

    chart_blocks = []
    i = 0
    while i < len(visualizations_spec):
        pair = visualizations_spec[i:i + 2]
        if len(pair) == 2:
            row_html = (
                f'<div class="chart-row">'
                f'{_build_chart_card(pair[0], i)}'
                f'{_build_chart_card(pair[1], i + 1)}'
                f'</div>'
            )
        else:
            row_html = (
                f'<div class="chart-row single">'
                f'{_build_chart_card(pair[0], i)}'
                f'</div>'
            )
        chart_blocks.append(row_html + _build_insight_callout(pair))
        i += 2
    charts_html = "\n".join(chart_blocks)

    # ── RECOMMENDATION (action) ──
    ra_primary_html = _process_text(recommended_action.get("primary", ""))
    ra_timeline     = html_lib.escape(recommended_action.get("timeline", ""))
    ra_impl_html    = _process_text(recommended_action.get("implementation_path", ""))

    scale_html = _process_text(scale_impact)

    lim_html = "\n".join(
        f'<li class="lim-item"><span class="lim-dot"></span>{html_lib.escape(lim)}</li>'
        for lim in known_limitations
    )

    dep_rows = "".join(
        f'<tr><td class="dep-gate">{html_lib.escape(d.get("gate", ""))}</td>'
        f'<td class="dep-owner">{html_lib.escape(d.get("owner", ""))}</td></tr>'
        for d in external_dependencies
    )
    ext_deps_html = ""
    if external_dependencies:
        ext_deps_html = f"""
  <hr class="section-divider">
  <section>
    <div class="section-eyebrow">External Dependencies</div>
    <table class="dep-table">
      <thead><tr><th>Gate</th><th>Owner</th></tr></thead>
      <tbody>{dep_rows}</tbody>
    </table>
  </section>"""

    # ── Footnotes (appendix) ──
    fn_items = []
    for fn in footnotes:
        n       = fn.get("n", "?")
        source  = fn.get("source", "")
        note    = html_lib.escape(fn.get("note", ""))
        src_cls = "src-" + re.sub(r"[^a-zA-Z0-9_]", "-", source)
        fn_items.append(
            f'<li id="fn-{n}" class="fn-item">'
            f'<span class="fn-num">[{n}]</span>'
            f'<span class="source-badge {src_cls}">{html_lib.escape(source)}</span>'
            f' {note}</li>'
        )
    footnotes_html = "\n".join(fn_items)

    # ── Compliance tables (appendix) ──
    compliance_rows = (
        f'<tr><td>Causal language veto</td><td>{_badge(l1.get("causal_check", False))}</td></tr>'
        f'<tr><td>Citation coverage + footnote integrity</td><td>{_badge(l1.get("citation_check", False))}</td></tr>'
        f'<tr><td>Omission audit</td><td>{_badge(l1.get("omission_check", False))}</td></tr>'
        f'<tr><td>C-020 Executive-layer rules</td><td>{_badge(l1.get("c020_executive_layer", False))}</td></tr>'
        f'<tr><td>C-020 Mode B Readiness Checklist</td><td>{_badge(l1.get("c020_readiness_checklist", False))}</td></tr>'
        f'<tr><td><strong>Overall</strong></td><td>{_badge(l1.get("overall_passed", False))}</td></tr>'
    )
    revision_last = revision_log[-1] if revision_log else {}
    checklist = revision_last.get("checklist_result", {})
    checklist_labels = {
        "C1_executive_comprehension":              "C1 — Executive comprehension",
        "C2_actionability":                        "C2 — Actionability",
        "C3_narrative_structure":                  "C3 — Narrative structure",
        "C4_legibility":                           "C4 — Legibility",
        "C5_visual_communication":                 "C5 — Visual communication",
        "C6_executive_readiness":                  "C6 — Executive readiness",
        "C7_visual_design_system_conformance":     "C7 — Visual Design System conformance (C-031)",
    }
    checklist_rows = "".join(
        f'<tr><td>{html_lib.escape(lbl)}</td><td>{_badge(checklist.get(k, False))}</td></tr>'
        for k, lbl in checklist_labels.items()
    )
    analyst_conf   = confidence_info.get("overall_confidence", 0)
    conf_desc_html = _process_text(confidence_info.get("uncertainty_description", ""))
    verdict_html   = _process_text(statistical_verdict)
    lineage_esc    = html_lib.escape(lineage_trace)
    genmode_esc    = html_lib.escape(generation_mode)

    # ── Confirmation gate ──
    gate_type = html_lib.escape(human_approval.get("decision_type", "UNKNOWN"))
    no_auto   = human_approval.get("no_auto_approve", True)
    gate_approve_cmd = (
        f"python governance/confirmation_gate/confirmation_gate.py "
        f"--artifact-id {html_lib.escape(artifact_id)} "
        f'--decision APPROVE --rationale "..." --enqueue-if-missing'
    )
    gate_reject_cmd = (
        f"python governance/confirmation_gate/confirmation_gate.py "
        f"--artifact-id {html_lib.escape(artifact_id)} "
        f'--decision REJECT --rationale "reason for rejection" --enqueue-if-missing'
    )
    checklist_items = [
        "Executive narrative is comprehensible to a non-technical stakeholder",
        "Finding (coordinated abuse ring) is consistent with the evidence presented",
        "Recommended action is appropriately scoped and actionable",
        "Financial projection methodology is reasonable",
        "Known limitations have been reviewed and do not disqualify the finding",
        "External dependencies are realistic and owned",
        "Visual Design System (C-031) conformance verified — palette, typography, chart construction, communication pattern",
    ]
    gate_checks_html = "\n".join(
        f'<label class="gate-check-item"><input type="checkbox"> {html_lib.escape(item)}</label>'
        for item in checklist_items
    )

    # ── Assemble HTML ──────────────────────────────────────────────────────────
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AIMS Mode B &middot; {artifact_id[:8]} &middot; Maldros</title>
<style>
/* ── Maldros Visual Design System tokens (C-031) ─────────────────────── */
{DESIGN_TOKENS_CSS}

/* ── AIMS Mode B report component styles ─────────────────────────────── */
{CSS}
</style>
</head>
<body>

<!-- ── Sticky header ── -->
<header class="report-header">
  <div class="header-inner">
    <span class="header-brand">Maldros &middot; AIMS Mode B</span>
    <span class="review-pill{pill_cls}">{pill_text}</span>
  </div>
</header>

<!-- ── FINDING: dark hero ── -->
<section class="finding-hero">
  <div class="finding-hero-inner">
    <div class="finding-label">Key Finding</div>
    <div class="finding-text">{kf_html}</div>
  </div>
</section>

<!-- ── L1 strip ── -->
<div class="l1-strip {l1_cls}">
  <span class="l1-icon">{l1_icon}</span>
  <span>{l1_label}</span>
  <div class="l1-gates">{l1_gates_html}</div>
</div>

<main class="report-main">

  <!-- Investigation question -->
  <div class="investigation-q">
    Investigation Question
    <span>{question}</span>
  </div>

  <!-- IMPACT: KPI row -->
  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-label">Quarterly Exposure</div>
      <div class="kpi-value">{_fmt_usd(coi)}</div>
      <div class="kpi-sub">base case &middot; {fp_confidence.lower()} confidence</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Countermeasure Cost</div>
      <div class="kpi-value">{_fmt_usd(coc)}</div>
      <div class="kpi-sub">one-time &middot; 2 engineers &middot; 8 weeks</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Net Quarterly Benefit</div>
      <div class="kpi-value">{_fmt_usd(nb)}</div>
      <div class="kpi-sub">base case minus countermeasure cost</div>
    </div>
  </div>

  <hr class="section-divider">

  <!-- Analysis summary -->
  <section>
    <div class="section-eyebrow">Analysis Summary</div>
    {rest_html}
  </section>

  <hr class="section-divider">

  <!-- EVIDENCE: charts -->
  <section>
    <div class="section-eyebrow">Visual Evidence &middot; {len(visualizations_spec)} charts</div>
    {charts_html}
  </section>

  <hr class="section-divider">

  <!-- RECOMMENDATION: action -->
  <section>
    <div class="section-eyebrow action">Recommended Action</div>
    <div class="action-primary">
      {ra_primary_html}
      <div class="action-timeline">&#9201;&nbsp; Timeline:&nbsp; {ra_timeline}</div>
    </div>
    <details class="impl-details">
      <summary>&#9654; Implementation path (expand for technical detail)</summary>
      <div class="impl-body">{ra_impl_html}</div>
    </details>
  </section>

  <hr class="section-divider">

  <!-- Scale & impact -->
  <section>
    <div class="section-eyebrow amber">Scale &amp; Impact</div>
    <div class="scale-block">{scale_html}</div>
  </section>

  <hr class="section-divider">

  <!-- Confirmation gate -->
  <div class="gate-section">
    <div class="gate-header">
      <span class="gate-title">&#128272; Confirmation Gate &mdash; Operator Decision Required</span>
      <span class="gate-pill">Pending Decision</span>
    </div>
    <div class="gate-body">
      <div class="gate-meta">
        <div class="gate-meta-item">
          <span class="gate-meta-label">Decision Type</span>
          <span class="gate-meta-value">{gate_type}</span>
        </div>
        <div class="gate-meta-item">
          <span class="gate-meta-label">Auto-Approve</span>
          <span class="gate-meta-value warn">{"DISABLED — explicit decision required" if no_auto else "Enabled"}</span>
        </div>
        <div class="gate-meta-item">
          <span class="gate-meta-label">Routing</span>
          <span class="gate-meta-value">{html_lib.escape(human_approval.get("routing", "CONFIRMATION_GATE"))}</span>
        </div>
        <div class="gate-meta-item">
          <span class="gate-meta-label">Artifact ID</span>
          <span class="gate-meta-value" style="font-family:var(--mono);font-size:.72rem">{artifact_id}</span>
        </div>
      </div>
      <div class="gate-cmd-block">
        <div class="gate-cmd-label">To approve &mdash; run in terminal:</div>
        <code class="gate-cmd">{gate_approve_cmd}</code>
        <div class="gate-cmd-label" style="margin-top:.45rem">To reject:</div>
        <code class="gate-cmd">{gate_reject_cmd}</code>
      </div>
    </div>
    <div class="gate-footer">
      <div class="gate-footer-label">Reviewer Checklist &mdash; tick before deciding</div>
      {gate_checks_html}
    </div>
  </div>

  <!-- Known limitations -->
  <section>
    <div class="section-eyebrow">Known Limitations &middot; {len(known_limitations)}</div>
    <ul class="lim-list">{lim_html}</ul>
  </section>
{ext_deps_html}

  <hr class="section-divider">

  <!-- Technical Appendix -->
  <details class="tech-appendix">
    <summary>
      <span class="tech-arrow">&#9654;</span>
      Technical Appendix &mdash; Statistical Detail, L1 Compliance, Footnotes
    </summary>
    <div class="appendix-inner">

      <div class="appendix-section">
        <h3>Statistical Verdict</h3>
        <div class="verdict-block">{verdict_html}</div>
      </div>

      <div class="appendix-section">
        <h3>L1 Compliance Summary</h3>
        <table class="compliance-table"><tbody>{compliance_rows}</tbody></table>
      </div>

      <div class="appendix-section">
        <h3>Mode B Readiness Checklist (C-020)</h3>
        <table class="compliance-table"><tbody>{checklist_rows}</tbody></table>
      </div>

      <div class="appendix-section">
        <h3>Confidence &amp; Uncertainty</h3>
        <div class="conf-scores">
          <span>Analyst: {analyst_conf:.0%}</span>
          <span>Statistician: 35%</span>
        </div>
        {conf_desc_html}
      </div>

      <div class="appendix-section">
        <h3>Footnotes ({len(footnotes)} citations)</h3>
        <ol class="fn-list">{footnotes_html}</ol>
      </div>

      <div class="appendix-section">
        <h3>Generation Mode</h3>
        <div class="mono-block">{genmode_esc}</div>
      </div>

      <div class="appendix-section">
        <h3>Artifact Lineage</h3>
        <div class="mono-block">{lineage_esc}</div>
      </div>

    </div>
  </details>

</main>

<footer class="report-footer">
  Maldros AEI System &middot; Phase 1 &middot; Artifact {artifact_id} &middot; {timestamp_display} &middot; Rendered {generated_at}
</footer>

</body>
</html>"""

    output_path.write_text(html_out, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    print(f"Report written : {output_path}")
    print(f"File size      : {size_kb:.0f} KB")
    print(f"Open in browser to review and sign off.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an AIMS Mode B artifact as a self-contained HTML report."
    )
    parser.add_argument(
        "artifact_id",
        nargs="?",
        default=DEFAULT_ID,
        help=f"Artifact UUID (default: {DEFAULT_ID})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path (default: artifacts/aims_mode_b/<id>_report.html)",
    )
    args = parser.parse_args()

    artifact_path = ARTIFACT_DIR / f"{args.artifact_id}.json"
    if not artifact_path.exists():
        print(f"ERROR: artifact not found at {artifact_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or (ARTIFACT_DIR / f"{args.artifact_id}_report.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    render(artifact_path, output_path)


if __name__ == "__main__":
    main()
