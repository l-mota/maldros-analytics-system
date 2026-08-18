"""
Maldros Visual Design System (C-031) — design tokens.

SINGLE SOURCE OF TRUTH for all data-meaning colors, canvas/ink infrastructure
values, and typography constants used across the Maldros ecosystem.

Python consumers (storyteller chart renderer, future Python-side renderers,
operator UI code generators) import constants from this module.

HTML consumers (render_aims_report.py, operator_ui_mockup.html, future
HTML renderers) inline lib/design_tokens.css which mirrors these values
as CSS custom properties.

Spec authority: Maldros_working_files/visual_design_system.md
Change control: any modification requires explicit operator approval (D-7)
and a new C-NNN entry in Maldros_Change_Tracker.md.
"""

# ── Data-meaning colors (the four) ────────────────────────────────────────────
# Each color carries semantic meaning. Use of a color outside its assigned
# slot is a Visual Design System violation.

FOREST    = "#0F2515"   # PRIMARY   — authority, structure, baseline
AMBER     = "#C8882A"   # SECONDARY — finding, focal subject, anomaly
PARCHMENT = "#EDE8D0"   # TERTIARY  — supporting surfaces, KPI cards
NEUTRAL   = "#A8A092"   # NEUTRAL   — gridlines, structural lines, idle states

# Slot aliases (semantic names)
PRIMARY   = FOREST
SECONDARY = AMBER
TERTIARY  = PARCHMENT

# ── Canvas / ink infrastructure (not data-meaning colors) ─────────────────────
# These are substrate/ink, never used to carry data meaning. They exist
# because content has to sit somewhere and be readable.

CANVAS    = "#FFFAFA"   # page background (never pure white)
INK       = "#252525"   # primary body text (never pure black)
INK_MUTED = "#6B6559"   # muted text, axis labels, captions, footnote sources
BORDER    = "#D6CEB8"   # card and container borders (parchment-derived)

# ── Semantic accent (C-031.1 iteration) ───────────────────────────────────────
# A second forest tone used specifically for the Recommended Action section
# eyebrow. Differentiates the decision section from neutral structure while
# staying anchored to the PRIMARY forest family.

ACTION_GREEN = "#2D5A3D"

# ── Typography hierarchy (rem multipliers for HTML) ───────────────────────────
TIER_1_REM_FINDING    = 1.42   # Primary Finding (KEY FINDING hero block)
TIER_2_REM_KPI        = 2.50   # KPI Value
TIER_3_REM_SECTION    = 0.86   # Section / Chart titles, KPI labels
TIER_4_REM_ANNOTATION = 0.78   # Annotations, axis labels, footnotes

# ── Chart typography (matplotlib pt sizes) ────────────────────────────────────
# Sized for readability in the AIMS Mode B HTML report at 150 DPI in
# 2-column grid layout.
CHART_TICK_PT      = 11
CHART_LEGEND_PT    = 11
CHART_VALUE_PT     = 12
CHART_AXIS_PT      = 11
CHART_SUBTITLE_PT  = 10.5
CHART_XLABEL_PT    = 10.5  # stacked-bar category labels

# ── Layout primitives ─────────────────────────────────────────────────────────
RADIUS    = "6px"
SHADOW    = "0 1px 4px rgba(0,0,0,0.07)"
MONO_FONT = "'Courier New', Courier, monospace"

# ── Communication pattern (C-031 §1) ──────────────────────────────────────────
# Permanently locked. Every artifact follows this reading order at every level.
COMMUNICATION_PATTERN = ("FINDING", "IMPACT", "EVIDENCE", "RECOMMENDATION")

# ── Information hierarchy (C-031 §5) ──────────────────────────────────────────
INFORMATION_HIERARCHY = (
    "L1 — Executive Summary",
    "L2 — KPI Metrics",
    "L3 — Supporting Charts and Evidence",
    "L4 — Interpretation and Recommendations",
)

# ── Approved palette set (for L1 conformance checks, Phase 2) ────────────────
# Any hex code in a rendered artifact must belong to this set or be a
# justified exception logged in artifact metadata.
APPROVED_HEXES = frozenset({
    FOREST.lower(),
    AMBER.lower(),
    PARCHMENT.lower(),
    NEUTRAL.lower(),
    CANVAS.lower(),
    INK.lower(),
    INK_MUTED.lower(),
    BORDER.lower(),
    ACTION_GREEN.lower(),
})

__all__ = [
    "FOREST", "AMBER", "PARCHMENT", "NEUTRAL",
    "PRIMARY", "SECONDARY", "TERTIARY",
    "CANVAS", "INK", "INK_MUTED", "BORDER",
    "ACTION_GREEN",
    "TIER_1_REM_FINDING", "TIER_2_REM_KPI",
    "TIER_3_REM_SECTION", "TIER_4_REM_ANNOTATION",
    "CHART_TICK_PT", "CHART_LEGEND_PT", "CHART_VALUE_PT",
    "CHART_AXIS_PT", "CHART_SUBTITLE_PT", "CHART_XLABEL_PT",
    "RADIUS", "SHADOW", "MONO_FONT",
    "COMMUNICATION_PATTERN", "INFORMATION_HIERARCHY",
    "APPROVED_HEXES",
]
