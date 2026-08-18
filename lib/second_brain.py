"""
lib/second_brain.py

Vault write module — feeds the Obsidian Second Brain continuously.

Every agent that produces an artifact calls the appropriate write function
here immediately after write_artifact(). No artifact may be produced without
a corresponding vault entry. This is not optional.

Vault location: Maldros 2.0 Brain/
Entry format:
  - Short summary at top (one line, human-scannable)
  - Source block: artifact_id, agent, phase, timestamp, content_hash
  - Relevance rationale
  - Substance section (findings / content)
  - Known limitations
  - [[wikilinks]] to all related components
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parents[1] / "Maldros 2.0 Brain"


# ─── helpers ────────────────────────────────────────────────────────────────

def _safe_filename(text: str, max_len: int = 80) -> str:
    import re
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", text)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len]


def _file_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _wikilink_block(links: list[str]) -> str:
    if not links:
        return ""
    return " · ".join(f"[[{l}]]" for l in links)


def write_vault_entry(
    subfolder: str,
    filename: str,
    summary: str,
    sections: dict,
    wikilinks: list[str],
    source_artifact_id: str,
    content_hash: str,
    producing_agent: str,
    timestamp_utc: str,
    phase: int,
    relevance_rationale: str,
) -> Path:
    """
    Write a markdown entry to the vault. Overwrites if file already exists
    (vault entries are living documents — re-runs update them).

    sections: ordered dict of {heading: body_text}
    """
    folder = VAULT / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{filename}.md"

    lines = [
        f"# {filename}",
        "",
        f"> **Summary:** {summary}",
        "",
        "---",
        "",
        f"**Source artifact:** `{source_artifact_id}`  ",
        f"**Producing agent:** {producing_agent}  ",
        f"**Phase:** {phase}  ",
        f"**Timestamp:** {timestamp_utc}  ",
        f"**Content hash:** `{content_hash}`  ",
        f"**Relevance:** {relevance_rationale}",
        "",
        "---",
        "",
    ]

    for heading, body in sections.items():
        if body:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(str(body).strip())
            lines.append("")

    if wikilinks:
        lines.append("## Links")
        lines.append("")
        lines.append(_wikilink_block(wikilinks))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ─── per-artifact-type writers ───────────────────────────────────────────────

def write_analysis_entry(evidence_artifact: dict) -> Path:
    """
    Write to analyses/ from an Evidence Bundle artifact.
    Called by Analyst Agent immediately after write_artifact().
    """
    c = evidence_artifact.get("content", {})
    question = c.get("investigation_question", "Unknown investigation")
    conclusion = c.get("primary_conclusion", "AMBIGUOUS")
    phase = evidence_artifact.get("phase_of_origin", 1)
    artifact_id = evidence_artifact.get("artifact_id", "unknown")
    content_hash = evidence_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = evidence_artifact.get("timestamp_utc", _now_iso())
    reasoning_mode = c.get("generation_mode", "ABDUCTIVE")

    analysis_results = c.get("analysis_results", {})
    vol = analysis_results.get("volume_analysis", {})
    graph = analysis_results.get("graph_analysis", {})
    fi = analysis_results.get("financial_impact_table", {})
    interpretation = c.get("llm_interpretation", {})
    limitations = evidence_artifact.get("known_limitations", [])

    summary = f"Phase {phase} analysis — {question[:80]} — Conclusion: {conclusion}"

    filename = _safe_filename(f"Analysis — {question[:60]} — Phase {phase}")

    findings_lines = [
        f"**Investigation question:** {question}",
        f"**Primary conclusion:** {conclusion}",
        f"**Reasoning mode:** {reasoning_mode}",
        "",
        "### Volume Analysis",
        f"- Q1 2024 abuse events: {vol.get('q1_2024_abuse_events', 'N/A')}",
        f"- Q1 spike ratio vs non-Q1: {vol.get('q1_spike_ratio', 'N/A')}",
        "",
        "### Graph Analysis",
        f"- Clustered accounts (≥3 co-temporal weeks): {graph.get('n_clustered_accounts_3plus', 'N/A')}",
        f"- Cluster Q1 abuse share: {graph.get('cluster_q1_abuse_share', 'N/A')}",
        f"- Edge density: {graph.get('cluster_edge_density', 'N/A')}",
        "",
        "### Financial Impact",
        f"- Q1 API abuse total: ${fi.get('q1_api_abuse_total', 0):,.0f}" if fi.get('q1_api_abuse_total') else "- Q1 API abuse total: N/A",
        "",
        "### Analyst Interpretation",
        interpretation.get("primary_conclusion_explanation", ""),
    ]

    countermeasure = interpretation.get("countermeasure", {})
    if countermeasure:
        findings_lines += [
            "",
            "### Recommended Countermeasure",
            f"- Primary: {countermeasure.get('primary', '')}",
            f"- Implementation: {countermeasure.get('implementation_path', '')}",
        ]

    sections = {
        "Findings": "\n".join(findings_lines),
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Evidence Bundle: `{artifact_id}`\n"
            f"- Capability Bundle: `{c.get('capability_bundle_id', 'N/A')}`\n"
            f"- Context Bundle: `{c.get('context_bundle_id', 'N/A')}`"
        ),
    }

    wikilinks = [
        "Analyst Agent",
        "Orchestrator",
        "Constraint Register",
        "api_abuse_rate",
        "fraud_loss_direct",
    ]

    path = write_vault_entry(
        subfolder="analyses",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="analyst",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Investigation into coordinated API abuse — {reasoning_mode} reasoning — "
            f"conclusion: {conclusion}"
        ),
    )

    # Store the path on the artifact for cross-linking by downstream agents
    evidence_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Analysis entry written: analyses/{filename}.md")
    return path


def write_statistical_addendum(stat_artifact: dict, analysis_vault_path: str = None) -> Path:
    """
    Write to analyses/ as a statistical addendum, linked to the parent analysis entry.
    Also writes a standalone entry under analyses/ for direct retrieval.
    Called by Statistician Agent immediately after write_artifact().
    """
    c = stat_artifact.get("content", {})
    verdict = c.get("statistical_verdict", "UNKNOWN")
    rationale = c.get("verdict_rationale", "")
    phase = stat_artifact.get("phase_of_origin", 1)
    artifact_id = stat_artifact.get("artifact_id", "unknown")
    content_hash = stat_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = stat_artifact.get("timestamp_utc", _now_iso())
    tests = c.get("tests", [])
    limitations = stat_artifact.get("known_limitations", [])
    eb_id = c.get("lineage", {}).get("evidence_bundle_id", "N/A")

    summary = f"Phase {phase} statistical validation — verdict: {verdict}"
    filename = _safe_filename(f"Statistical Result — {verdict} — Phase {phase} — {artifact_id[:8]}")

    test_lines = []
    for t in tests:
        test_lines.append(
            f"- **{t.get('test_name', '?')}**: stat={t.get('statistic', '?')}, "
            f"p={t.get('p_value', '?')}, effect={t.get('effect_size', 'N/A')}"
        )

    sections = {
        "Statistical Verdict": f"**{verdict}**\n\n{rationale}",
        "Tests Run": "\n".join(test_lines) if test_lines else "None recorded.",
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Statistical Result: `{artifact_id}`\n"
            f"- Parent Evidence Bundle: `{eb_id}`\n"
            + (f"- Vault analysis entry: `{analysis_vault_path}`" if analysis_vault_path else "")
        ),
    }

    wikilinks = [
        "Statistician Agent",
        "Analyst Agent",
    ]
    if analysis_vault_path:
        # Derive the analysis filename for wikilink
        parent_name = Path(analysis_vault_path).stem
        wikilinks.insert(0, parent_name)

    path = write_vault_entry(
        subfolder="analyses",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="statistician",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Statistical validation of analyst conclusion — verdict: {verdict}"
        ),
    )

    # Append a brief addendum to the parent analysis entry if it exists
    if analysis_vault_path:
        parent = Path(analysis_vault_path)
        if parent.exists():
            addendum = (
                f"\n---\n\n## Statistical Validation Addendum\n\n"
                f"**Verdict:** {verdict}  \n"
                f"**Rationale:** {rationale}  \n"
                f"**Statistical Result artifact:** `{artifact_id}`  \n"
                f"**Full entry:** [[{filename}]]\n"
            )
            with parent.open("a", encoding="utf-8") as f:
                f.write(addendum)

    stat_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Statistical addendum written: analyses/{filename}.md")
    return path


def write_discovery_entry(discovery_artifact: dict, chart_paths: list = None) -> Path:
    """
    Write to discoveries/ from a Discovery Report artifact.
    Called by Storyteller Agent immediately after write_artifact().
    """
    c = discovery_artifact.get("content", {})
    question = c.get("investigation_question", "Unknown")
    phase = discovery_artifact.get("phase_of_origin", 1)
    artifact_id = discovery_artifact.get("artifact_id", "unknown")
    content_hash = discovery_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = discovery_artifact.get("timestamp_utc", _now_iso())
    l1 = c.get("l1_compliance", {})
    status = c.get("status", "PRODUCED")
    limitations = discovery_artifact.get("known_limitations", [])

    dr = c.get("discovery_report", {})
    plain_summary = ""
    if isinstance(dr, dict):
        sec1 = dr.get("section_1_plain_language_summary", {})
        plain_summary = sec1.get("text", "") if isinstance(sec1, dict) else str(sec1)

    aims_summary = c.get("aims_mode_b_summary", {})
    financial = aims_summary.get("financial_projection", {})
    rec = aims_summary.get("recommended_action", {})

    summary = (
        f"Phase {phase} discovery — {question[:70]} — "
        f"L1: {'PASS' if l1.get('overall_passed') else 'BLOCKED'} — Status: {status}"
    )
    # Include artifact_id[:8] to prevent filename collision across multiple runs
    filename = _safe_filename(
        f"Discovery — {question[:40]} — Phase {phase} — {artifact_id[:8]}", max_len=120
    )

    findings_lines = [
        f"**Investigation:** {question}",
        f"**Status:** {status}",
        f"**L1 compliance:** {'PASS' if l1.get('overall_passed') else 'BLOCKED'}",
        "",
        "### Plain-Language Finding",
        plain_summary,
        "",
        "### Statistical Verdict",
        aims_summary.get("statistical_verdict", "N/A"),
        "",
        "### Financial Projection",
        f"- Cost of inaction: ${financial.get('cost_of_inaction_usd', 0):,.0f}" if financial.get('cost_of_inaction_usd') else "- Cost of inaction: N/A",
        f"- Cost of countermeasure: ${financial.get('cost_of_countermeasure_usd', 0):,.0f}" if financial.get('cost_of_countermeasure_usd') else "- Cost of countermeasure: N/A",
        f"- Net benefit: ${financial.get('net_benefit_usd', 0):,.0f}" if financial.get('net_benefit_usd') else "- Net benefit: N/A",
        "",
        "### Recommended Action",
        rec.get("primary", "N/A") if isinstance(rec, dict) else str(rec),
    ]

    lineage = c.get("lineage", {})
    sections = {
        "Findings": "\n".join(findings_lines),
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Discovery Report: `{artifact_id}`\n"
            f"- Capability Bundle: `{lineage.get('capability_bundle_id', 'N/A')}`\n"
            f"- Evidence Bundle: `{lineage.get('evidence_bundle_id', 'N/A')}`\n"
            f"- Statistical Result: `{lineage.get('statistical_result_id', 'N/A')}`"
        ),
    }

    chart_section = ""
    chart_wikilinks = []
    if chart_paths:
        chart_lines = [f"- [[{Path(p).name}]]" for p in chart_paths if p]
        chart_section = "\n".join(chart_lines)
        chart_wikilinks = [Path(p).stem for p in chart_paths if p]

    if chart_section:
        sections["Rendered Charts"] = chart_section

    wikilinks = [
        "Storyteller Agent",
        "Analyst Agent",
        "Statistician Agent",
        "Orchestrator",
        "api_abuse_rate",
        "fraud_loss_direct",
        "Constraint Register",
        "Design Invariants",
    ] + chart_wikilinks

    path = write_vault_entry(
        subfolder="discoveries",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="storyteller",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Completed investigation discovery — {question[:60]} — "
            f"routed to Second Brain for institutional memory"
        ),
    )

    discovery_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Discovery entry written: discoveries/{filename}.md")
    return path


def write_aims_entry(aims_artifact: dict, chart_paths: list = None) -> Path:
    """
    Write to aims/ from an AIMS Mode B artifact file (the JSON written to aims/mode_b/).
    Called by Storyteller Agent immediately after writing the AIMS Mode B file.
    """
    task_id = aims_artifact.get("task_id", "unknown")
    status = aims_artifact.get("status", "UNKNOWN")
    timestamp = aims_artifact.get("timestamp_utc", _now_iso())
    artifact_id = aims_artifact.get("aims_mode_b_artifact_id", task_id)
    assets = aims_artifact.get("assets", {})
    phase = assets.get("phase", 1) if isinstance(assets, dict) else 1

    executive_narrative = assets.get("executive_narrative", "") if isinstance(assets, dict) else ""
    rec = assets.get("recommended_action", {}) if isinstance(assets, dict) else {}
    fp = assets.get("financial_projection", {}) if isinstance(assets, dict) else {}
    ext_deps = assets.get("external_dependencies", []) if isinstance(assets, dict) else []
    viz = assets.get("visualizations_spec", []) if isinstance(assets, dict) else []
    footnotes = assets.get("footnotes", []) if isinstance(assets, dict) else []
    human_gate = aims_artifact.get("human_approval_required", True)
    content_hash = _file_hash(json.dumps(aims_artifact, sort_keys=True, default=str))

    summary = (
        f"AIMS Mode B — Phase {phase} — Status: {status} — "
        f"Human approval required: {human_gate}"
    )
    filename = _safe_filename(f"AIMS Mode B — Phase {phase} — {artifact_id[:8]}")

    chart_lines = []
    for v in viz:
        if isinstance(v, dict):
            chart_lines.append(
                f"- **{v.get('title', '?')}** ({v.get('chart_type', '?')}): "
                f"{v.get('insights', '')}"
            )

    dep_lines = []
    for d in ext_deps:
        if isinstance(d, dict):
            dep_lines.append(f"- {d.get('gate', str(d))}: {d.get('owner', '')}")

    rec_primary = rec.get("primary", "N/A") if isinstance(rec, dict) else str(rec)

    sections = {
        "Executive Narrative": executive_narrative,
        "Recommended Action": rec_primary,
        "Financial Projection": (
            f"- Cost of inaction: ${fp.get('cost_of_inaction_usd', 0):,.0f}\n"
            f"- Countermeasure cost: ${fp.get('cost_of_countermeasure_usd', 0):,.0f}\n"
            f"- Net benefit: ${fp.get('net_benefit_usd', 0):,.0f}\n"
            f"- Confidence: {fp.get('confidence', 'N/A')}"
        ) if fp else "Not recorded.",
        "Charts Produced": "\n".join(chart_lines) if chart_lines else "None.",
        "External Dependencies": "\n".join(dep_lines) if dep_lines else "None recorded.",
        "Human Approval Gate": (
            f"**Required:** {human_gate}  \n"
            f"**No auto-approve:** {aims_artifact.get('no_auto_approve', True)}  \n"
            f"**Routing:** CONFIRMATION_GATE"
        ),
        "Footnotes": "\n".join(
            f"[^{fn.get('marker', i+1)}] {fn.get('source', '')} — {fn.get('note', '')}"
            for i, fn in enumerate(footnotes) if isinstance(fn, dict)
        ) if footnotes else "None.",
        "Artifact Lineage": f"- AIMS Mode B artifact: `{artifact_id}`\n- Task ID: `{task_id}`",
    }

    chart_wikilinks = []
    if chart_paths:
        extra_chart_lines = [f"- [[{Path(p).name}]]" for p in chart_paths if p]
        if extra_chart_lines:
            existing = sections.get("Charts Produced", "")
            sections["Charts Produced"] = existing + "\n" + "\n".join(extra_chart_lines)
            chart_wikilinks = [Path(p).stem for p in chart_paths if p]

    wikilinks = [
        "Storyteller Agent",
        "Analyst Agent",
        "Statistician Agent",
        "Orchestrator",
        "Design Invariants",
        "Phase 0 — Foundation",
    ] + chart_wikilinks

    path = write_vault_entry(
        subfolder="aims",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="storyteller",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            "AIMS Mode B stakeholder briefing — novel finding — human approval gate open"
        ),
    )

    aims_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] AIMS Mode B entry written: aims/{filename}.md")
    return path


def write_capability_bundle_entry(artifact: dict) -> Path:
    """
    Write to agents/ vault from a Capability Bundle artifact.
    Called by Orchestrator immediately after write_artifact() for the Capability Bundle.
    """
    c = artifact.get("content", {})
    task_id = c.get("task_id", "unknown")
    question = c.get("question", "Unknown question")
    phase = artifact.get("phase_of_origin", 0)
    artifact_id = artifact.get("artifact_id", "unknown")
    content_hash = artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = artifact.get("timestamp_utc", _now_iso())

    active_modes = c.get("active_reasoning_modes", [])
    l1_nominal = c.get("l1_nominal", True)
    capabilities_met = c.get("capabilities_met", [])
    capabilities_not_met = c.get("capabilities_not_met", [])
    cdi_domains = c.get("cdi_context", {}).get("queried_domains", [])
    similarity = c.get("second_brain_result", {}).get("similarity_score", 0.0)

    summary = (
        f"Phase {phase} Capability Bundle — task {task_id[:8]} — "
        f"L1 nominal: {l1_nominal} — modes: {active_modes}"
    )
    filename = _safe_filename(f"Capability Bundle — Phase {phase} — {artifact_id[:8]}")

    cap_lines = [f"- {cap}" for cap in capabilities_met] if capabilities_met else ["None recorded."]
    not_met_lines = [f"- {cap}" for cap in capabilities_not_met] if capabilities_not_met else ["None — all capabilities met."]

    sections = {
        "Task Context": (
            f"**Task ID:** `{task_id}`\n"
            f"**Question:** {question}\n"
            f"**Active reasoning modes:** {active_modes}\n"
            f"**L1 nominal:** {l1_nominal}\n"
            f"**Second Brain similarity:** {similarity:.2f}"
        ),
        "CDI Layer Query": (
            f"**Domains queried:** {cdi_domains}\n"
        ),
        "Capabilities Met": "\n".join(cap_lines),
        "Capabilities Not Met (logged — never silently omitted)": "\n".join(not_met_lines),
        "Artifact Lineage": f"- Capability Bundle: `{artifact_id}`",
    }

    path = write_vault_entry(
        subfolder="agents",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=["Orchestrator", "CDI Layer", "AIMS Mode A"],
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="orchestrator",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Capability Bundle is the first artifact on every task — "
            f"records CDI Layer snapshot and active capabilities for task {task_id[:8]}"
        ),
    )

    artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Capability Bundle entry written: agents/{filename}.md")
    return path


def write_context_bundle_entry(artifact: dict) -> Path:
    """
    Write to agents/ vault from a Context Bundle artifact.
    Called by Orchestrator immediately after write_artifact() for the Context Bundle.
    """
    c = artifact.get("content", {})
    task_id = c.get("task_id", "unknown")
    question = c.get("question", "Unknown question")
    phase = artifact.get("phase_of_origin", 0)
    artifact_id = artifact.get("artifact_id", "unknown")
    content_hash = artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = artifact.get("timestamp_utc", _now_iso())

    generation_mode = c.get("generation_mode", "UNKNOWN")
    analogues = c.get("analogues_used", [])
    second_brain_findings = c.get("second_brain_findings", [])
    provenance = artifact.get("provenance", [])

    summary = (
        f"Phase {phase} Context Bundle — task {task_id[:8]} — "
        f"generation mode: {generation_mode}"
    )
    filename = _safe_filename(f"Context Bundle — Phase {phase} — {artifact_id[:8]}")

    analogue_lines = [f"- {a}" for a in analogues] if analogues else ["None — First-Principles mode."]
    sb_lines = [f"- {f}" for f in second_brain_findings] if second_brain_findings else ["No prior analyses found."]

    sections = {
        "Task Context": (
            f"**Task ID:** `{task_id}`\n"
            f"**Question:** {question}\n"
            f"**Generation mode:** {generation_mode}"
        ),
        "Second Brain Prior Findings": "\n".join(sb_lines),
        "CDI Analogues Used": "\n".join(analogue_lines),
        "Artifact Lineage": (
            f"- Context Bundle: `{artifact_id}`\n"
            f"- Provenance: {provenance}"
        ),
    }

    path = write_vault_entry(
        subfolder="agents",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=["Orchestrator", "CDI Layer"],
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="orchestrator",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Context Bundle records Second Brain query results and CDI analogues "
            f"for task {task_id[:8]} — generation mode: {generation_mode}"
        ),
    )

    artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Context Bundle entry written: agents/{filename}.md")
    return path


# ─── Phase 2: diagnostic + healing ───────────────────────────────────────────

def write_diagnostic_entry(diagnostic_artifact: dict) -> Path:
    """
    Write to pipelines/ from a diagnostic_result artifact.
    Called by Diagnostic Agent immediately after write_artifact().

    Routine L0 entries go to pipelines/diagnostic/; L2+ findings get a
    Postmortem-style note in postmortems/ so failure history is queryable.
    """
    c = diagnostic_artifact.get("content", {})
    level = c.get("level", "L0")
    status = c.get("status", "UNKNOWN")
    realm = c.get("realm", "artifact_envelope")
    subject = c.get("artifact_id", "unknown")
    message = c.get("message", "")
    phase = diagnostic_artifact.get("phase_of_origin", 2)
    artifact_id = diagnostic_artifact.get("artifact_id", "unknown")
    content_hash = diagnostic_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = diagnostic_artifact.get("timestamp_utc", _now_iso())
    limitations = diagnostic_artifact.get("known_limitations", [])

    summary = (
        f"Phase {phase} diagnostic — {realm} — level {level} ({status}) — "
        f"subject: {str(subject)[:40]}"
    )
    filename = _safe_filename(
        f"Diagnostic — {realm} — {level} — {artifact_id[:8]}", max_len=120
    )

    causal_chain = c.get("minimum_causal_chain", [])
    chain_lines = []
    for link in causal_chain:
        chain_lines.append(
            f"- **Step {link.get('step', '?')}:** {link.get('claim', '')} "
            f"_(evidence: {link.get('evidence', 'n/a')})_"
        )

    findings_lines = [
        f"**Subject artifact / pipeline:** `{subject}`",
        f"**Realm:** {realm}",
        f"**Level:** {level}",
        f"**Status:** {status}",
        f"**Message:** {message}",
        f"**Recommended escalation:** {c.get('recommended_escalation', 'log_only')}",
    ]
    if c.get("psi_score") is not None:
        findings_lines += [
            "",
            "### Pipeline Signals",
            f"- PSI: {c['psi_score']:.4f}",
            f"- Schema passed: {c.get('schema_passed', 'n/a')}",
            f"- Failure class: {c.get('failure_class', 'n/a')}",
            f"- Latency ratio vs. median: {c.get('latency_ratio', 'n/a')}",
            f"- Healing retry count: {c.get('healing_retry_count', 0)}",
        ]

    if c.get("palette_violations") or c.get("title_violations") or c.get("decorative_violations"):
        findings_lines += [
            "",
            "### Visual Conformance (C-032 Layer 5)",
            f"- Off-palette hex codes: {c.get('palette_violations', [])}",
            f"- Generic chart titles: {len(c.get('title_violations', []))}",
            f"- Decorative CSS patterns: {c.get('decorative_violations', [])}",
        ]

    sections = {
        "Findings": "\n".join(findings_lines),
        "Minimum Causal Chain": "\n".join(chain_lines) if chain_lines else "Not applicable (envelope realm).",
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Diagnostic result: `{artifact_id}`\n"
            f"- Subject: `{subject}`"
        ),
    }

    wikilinks = [
        "Diagnostic Agent",
        "Healing Agent" if level in ("L1", "L2") else "Orchestrator",
        "CDI Layer",
        "AIMS Mode A",
        "Inference Layers",
    ]

    path = write_vault_entry(
        subfolder="pipelines",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="diagnostic",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Diagnostic finding — {realm} realm — level {level}; "
            f"recommended action: {c.get('recommended_escalation', 'log_only')}"
        ),
    )

    diagnostic_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Diagnostic entry written: pipelines/{filename}.md")
    return path


def write_healing_entry(healing_artifact: dict) -> Path:
    """
    Write to pipelines/ from a healing_record artifact.
    Called by Healing Agent immediately after write_artifact().

    Records the full cycle: characterization, strategies considered,
    domains consulted, attempts, verification, MC conditions, escalation.
    """
    c = healing_artifact.get("content", {})
    pipeline_id = c.get("pipeline_id", "unknown")
    failure_class = c.get("failure_class", "unknown")
    strategy_applied = c.get("strategy_applied")
    verification = c.get("verification_result", "FAIL")
    domains = c.get("domains_consulted", [])
    attempts = c.get("attempts", [])
    mc = c.get("mc_conditions", {})
    escalated = c.get("escalated", False)
    phase = healing_artifact.get("phase_of_origin", 2)
    artifact_id = healing_artifact.get("artifact_id", "unknown")
    content_hash = healing_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = healing_artifact.get("timestamp_utc", _now_iso())
    limitations = healing_artifact.get("known_limitations", [])

    summary = (
        f"Phase {phase} healing — pipeline {pipeline_id} — class {failure_class} — "
        f"verdict: {verification}{' (ESCALATED)' if escalated else ''}"
    )
    filename = _safe_filename(
        f"Healing — {pipeline_id} — {failure_class} — {verification} — {artifact_id[:8]}",
        max_len=120,
    )

    attempt_lines = []
    for a in attempts:
        v = a.get("verification", {})
        attempt_lines.append(
            f"- **Attempt {a.get('attempt_idx', '?') + 1}:** `{a.get('strategy_name', '?')}` "
            f"({a.get('domain', '?')}) → {v.get('verification', '?')} "
            f"(level {v.get('final_level', '?')}, PSI {v.get('psi_post', '?')})"
        )

    mc_lines = []
    if mc:
        mc_lines = [
            f"- (a) Strategy exhaustion: {mc.get('a_strategy_exhaustion', False)}",
            f"- (b) Retry exhaustion: {mc.get('b_retry_exhaustion', False)}",
            f"- (c) Synthesis exhaustion: {mc.get('c_synthesis_exhaustion', False)}",
            f"- (d) Budget exhaustion: {mc.get('d_budget_exhaustion', False)}",
            f"- (e) No-progress: {mc.get('e_no_progress', False)}",
            f"- (f) Root reached / unreachable: {mc.get('f_root_reached_or_unreachable', False)}",
            f"- **All six hold (escalation gate):** {mc.get('all_six_hold', False)}",
        ]

    causal_chain = c.get("minimum_causal_chain", [])
    chain_lines = [
        f"- **Step {link.get('step', '?')}:** {link.get('claim', '')}"
        for link in causal_chain
    ]

    sections = {
        "Cycle Summary": (
            f"**Pipeline:** `{pipeline_id}`\n"
            f"**Failure class:** {failure_class}\n"
            f"**Strategy applied:** {strategy_applied or '— (no strategy succeeded)'}\n"
            f"**Verification:** {verification}\n"
            f"**Domains consulted:** {', '.join(domains) if domains else 'none'}\n"
            f"**Generation mode:** {c.get('generation_mode', 'ANALOGICAL')}\n"
            f"**Escalated:** {escalated}\n"
            f"**Elapsed:** {c.get('elapsed_seconds', 0):.1f}s"
        ),
        "Attempts": "\n".join(attempt_lines) if attempt_lines else "No attempts logged.",
        "Maximum-Capacity Conditions (all 6 required for escalation)":
            "\n".join(mc_lines) if mc_lines else "Not evaluated (safety-class bypass).",
        "Minimum Causal Chain": "\n".join(chain_lines) if chain_lines else "Not recorded.",
        "Draft PR": (
            f"`{c.get('draft_pr_path', 'none')}` — production merge requires "
            f"Confirmation Gate sign-off."
        ),
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Healing record: `{artifact_id}`\n"
            f"- Provenance: {healing_artifact.get('provenance', [])}"
        ),
    }

    wikilinks = [
        "Healing Agent",
        "Diagnostic Agent",
        "CDI Layer",
        "AIMS Mode A",
        "Cross-Domain Analogues",
    ]
    if escalated:
        wikilinks.append("Confirmation Gate")

    path = write_vault_entry(
        subfolder="pipelines",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="healing",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Healing cycle for {pipeline_id} — {failure_class} — "
            f"verdict: {verification}; draft PR — no production merge"
        ),
    )

    healing_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Healing entry written: pipelines/{filename}.md")
    return path


def write_red_team_entry(red_team_artifact: dict) -> Path:
    """
    Write to analyses/ from a red_team_report artifact.
    Called by Red-Team Agent immediately after write_artifact().

    Records the full E1–E12 adversarial evaluation: verdict, primary weakness,
    hardening steps, per-category assessments, and penetration difficulty score.
    """
    c = red_team_artifact.get("content", {})
    experiment_id = c.get("experiment_id", "unknown")
    verdict = c.get("overall_verdict", "UNKNOWN")
    primary_weakness = c.get("primary_weakness", "UNKNOWN")
    hardening_steps = c.get("hardening_steps", [])
    evasion_assessments = c.get("evasion_assessments", [])
    pds = c.get("penetration_difficulty_score", 0.5)
    phase = red_team_artifact.get("phase_of_origin", 3)
    artifact_id = red_team_artifact.get("artifact_id", "unknown")
    content_hash = red_team_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = red_team_artifact.get("timestamp_utc", _now_iso())
    limitations = red_team_artifact.get("known_limitations", [])

    summary = (
        f"Phase {phase} Red-Team — {experiment_id} — verdict: {verdict} "
        f"— primary weakness: {primary_weakness} — PDS: {pds:.2f}"
    )
    filename = _safe_filename(
        f"RedTeam — {experiment_id} — {verdict} — {artifact_id[:8]}",
        max_len=120,
    )

    evasion_lines = []
    for ea in evasion_assessments:
        evasion_lines.append(
            f"- **{ea.get('code', '?')}** ({ea.get('effort_to_exploit', '?')} effort): "
            f"{ea.get('verdict_contribution', '?')} — {ea.get('attack_path', 'no path described')[:120]}"
        )

    hardening_lines = [f"- {step}" for step in hardening_steps]

    pre_screens = c.get("deterministic_prescreens", {})
    prescreen_lines = []
    for code, sig in pre_screens.items():
        if sig.get("pre_screened"):
            prescreen_lines.append(
                f"- **{code}** [{sig.get('severity', '?')}]: {sig.get('evidence', '')}"
            )

    sections = {
        "Verdict Summary": (
            f"**Experiment:** `{experiment_id}`\n"
            f"**Overall verdict:** {verdict}\n"
            f"**Primary weakness:** {primary_weakness}\n"
            f"**Penetration difficulty score:** {pds:.2f} (0=trivially broken, 1=fully robust)\n"
            f"**Verdict rationale:** {c.get('verdict_rationale', 'not recorded')}"
        ),
        "Deterministic Pre-screens (L1-enforced)":
            "\n".join(prescreen_lines) if prescreen_lines else "None fired.",
        "E1–E12 Adversarial Assessments":
            "\n".join(evasion_lines) if evasion_lines else "Full assessment not recorded (LLM parse failure).",
        "Hardening Steps (priority order)":
            "\n".join(hardening_lines) if hardening_lines else "None specified.",
        "Known Limitations":
            "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Red-team report: `{artifact_id}`\n"
            f"- Provenance: {red_team_artifact.get('provenance', [])}"
        ),
    }

    wikilinks = [
        "Red-Team Agent",
        "Statistician Agent",
        "CDI Layer",
        "AIMS Mode B",
        "Confirmation Gate",
    ]
    if verdict == "Brittle":
        wikilinks.append("Review Queue")

    path = write_vault_entry(
        subfolder="analyses",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="red_team",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Red-Team E1–E12 evaluation of {experiment_id}: {verdict} — "
            f"primary weakness {primary_weakness} — hardening required before ship"
            if verdict != "Robust" else
            f"Red-Team E1–E12 evaluation of {experiment_id}: Robust — no hardening required"
        ),
    )

    red_team_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Red-Team entry written: analyses/{filename}.md")
    return path


def write_few_shot_entry(exemplar: dict, source_triple: dict) -> Path:
    """
    Write a Few-Shot Bank exemplar to the vault under exemplars/.
    Called by PromotionGate after CDIUpdater.promote_exemplar() succeeds.

    Records what was learned, why it generalizes, and the triple it came from.
    """
    exemplar_id = exemplar.get("id", "unknown")
    query_class = exemplar.get("query_class", "general")
    justification = exemplar.get("justification", "")
    edit_pattern = exemplar.get("edit_pattern", "unknown")
    source_triple_id = exemplar.get("source_triple_id", "unknown")
    agent_name = source_triple.get("agent_name", "unknown")
    diff = source_triple.get("diff", {})
    distance = diff.get("edit_distance", 0.0)
    change_summary = diff.get("change_summary", [])[:5]
    timestamp = _now_iso()

    summary = (
        f"Few-Shot Exemplar — class: {query_class} — pattern: {edit_pattern} — "
        f"promoted from triple {source_triple_id[:8]}"
    )
    filename = _safe_filename(
        f"FewShot — {query_class} — {edit_pattern} — {exemplar_id[:8]}",
        max_len=120,
    )

    accepted_preview = json.dumps(exemplar.get("output", {}), indent=2, default=str)[:1500]
    input_preview = json.dumps(exemplar.get("input", {}), indent=2, default=str)[:800]
    changes_lines = []
    for ch in change_summary:
        if isinstance(ch, dict):
            op = ch.get("op", "?")
            from_v = str(ch.get("from", ch.get("original", "")))[:80]
            to_v = str(ch.get("to", ch.get("edited", "")))[:80]
            changes_lines.append(f"- **{op}**: `{from_v}` → `{to_v}`")

    sections = {
        "Promotion Justification": justification,
        "Query Class": (
            f"**Class:** `{query_class}`  \n"
            f"**Edit pattern:** {edit_pattern}  \n"
            f"**Edit distance (source):** {distance:.3f}  \n"
            f"**Source agent:** {agent_name}  \n"
            f"**Source triple:** `{source_triple_id}`"
        ),
        "Input Context (prompt-side)": f"```json\n{input_preview}\n```",
        "Accepted Output (canonical exemplar)": f"```json\n{accepted_preview}\n```",
        "Original → Accepted Changes":
            "\n".join(changes_lines) if changes_lines else "(no structured change list)",
        "Retrieval Notes": (
            "Injected into agent prompts when query class matches. Retrieval is by "
            "exact `query_class` match in Phase 4; vector-similarity retrieval is a Phase 5 upgrade.\n\n"
            "Generalizable-class auto-promotion is a permanently-locked Design Invariant. "
            "If this exemplar produces regressions, quarantine via PromotionGate, do not edit in place."
        ),
    }

    wikilinks = [
        "Few-Shot Bank",
        "Promotion Gate",
        "Telemetry Capture",
        "CDI Layer",
        "exemplar_surface",
        "AIMS Mode A",
    ]

    path = write_vault_entry(
        subfolder="exemplars",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=exemplar_id,
        content_hash=_file_hash(exemplar_id + source_triple_id),
        producing_agent="orchestrator",  # gate acts under orchestrator authority
        timestamp_utc=timestamp,
        phase=4,
        relevance_rationale=(
            f"Generalizable correction promoted to Few-Shot Bank under query class "
            f"'{query_class}'; injected into future {agent_name} prompts for matching queries."
        ),
    )

    print(f"[SecondBrain] Few-Shot exemplar written: exemplars/{filename}.md")
    return path


def write_algorithmic_rule_entry(cycle_record: dict) -> Path:
    """
    Write to constraints/ when the Algorithmic Rule fires.
    Records the counter-intuitive hypothesis drawn from the Constraint Register,
    the cycle number, the source constraint, and the diversion outcome.
    """
    cycle = cycle_record.get("cycle_number", 0)
    constraint_id = cycle_record.get("constraint_id", "unknown")
    hypothesis = cycle_record.get("hypothesis", "")
    task_id = cycle_record.get("task_id", "unknown")
    timestamp = cycle_record.get("timestamp_utc", _now_iso())

    summary = (
        f"Algorithmic Rule cycle #{cycle} — diverted to counter-intuitive hypothesis "
        f"from {constraint_id}"
    )
    filename = _safe_filename(
        f"AlgorithmicRule — Cycle {cycle:04d} — {constraint_id} — {task_id[:8]}",
        max_len=120,
    )

    sections = {
        "Exploration Cycle": (
            f"**Cycle number:** {cycle} (every 10th cycle is diverted per the locked 10% budget)  \n"
            f"**Source constraint:** `{constraint_id}`  \n"
            f"**Task ID:** `{task_id}`"
        ),
        "Counter-intuitive Hypothesis": hypothesis,
        "Hard Rule Note": (
            "The Algorithmic Rule is a permanently-locked Design Invariant (#5). "
            "Mandatory Exploration Budget = 10% of investigation cycles. The system "
            "cannot skip these cycles. Analyst may adjust the percentage in either "
            "direction; system cannot."
        ),
        "Outcome": cycle_record.get("outcome", "(pending — cycle in flight)"),
    }

    wikilinks = [
        "Algorithmic Rule",
        "Constraint Register",
        "Orchestrator",
        "CDI Layer",
        "AIMS Mode A",
        constraint_id,
    ]

    path = write_vault_entry(
        subfolder="constraints",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=task_id,
        content_hash=_file_hash(f"{cycle}:{constraint_id}:{task_id}"),
        producing_agent="orchestrator",
        timestamp_utc=timestamp,
        phase=4,
        relevance_rationale=(
            f"10% exploration-budget cycle: cycle #{cycle} mandatorily diverted from "
            f"high-probability investigation queue to counter-intuitive hypothesis "
            f"drawn from open Constraint Register entry {constraint_id}."
        ),
    )

    print(f"[SecondBrain] Algorithmic Rule entry written: constraints/{filename}.md")
    return path


# ─── Phase 5: The Forge ───────────────────────────────────────────────────────

def write_forge_entry(ipr_artifact: dict) -> Path:
    """
    Write to discoveries/ from an invention_pipeline_report artifact.
    Called by Forge Agent immediately after write_artifact().

    Records the invented framework, derivation chain, Red-Team verdict,
    Pre-Screen Gate outcome, and Innovation Mandate compliance tracking.
    """
    c = ipr_artifact.get("content", {})
    task_id = c.get("task_id", "unknown")
    problem = c.get("problem_framing", "Unknown problem")
    gen_mode = c.get("generation_mode", "UNKNOWN")
    is_novel = c.get("is_novel", False)
    framework = c.get("proposed_framework", {})
    rt_verdict = c.get("red_team_verdict", "NOT_EVALUATED")
    gate_outcome = c.get("pre_screen_gate_outcome", "UNKNOWN")
    phase = ipr_artifact.get("phase_of_origin", 5)
    artifact_id = ipr_artifact.get("artifact_id", "unknown")
    content_hash = ipr_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = ipr_artifact.get("timestamp_utc", _now_iso())

    novel_label = "NOVEL INVENTION" if is_novel else "INCREMENTAL REFINEMENT"
    summary = (
        f"Forge Invention — {gen_mode} — {novel_label} — "
        f"Red-Team: {rt_verdict} — Gate: {gate_outcome} — "
        f"framework: {framework.get('name', 'unnamed')}"
    )
    filename = _safe_filename(
        f"Forge — {framework.get('name', 'Invention')} — {artifact_id[:8]}",
        max_len=120,
    )

    derivation = c.get("derivation_chain", [])
    derivation_text = "\n".join(f"{i+1}. {step}" for i, step in enumerate(derivation))

    stat_pre = c.get("statistical_pre_validation", {})
    cost_model = c.get("cost_model", {})
    gate_filters = c.get("pre_screen_gate_filters", [])

    filter_lines = [
        f"- **{f.get('filter', '?')}**: {f.get('outcome', '?')} — {f.get('rationale', '')}"
        for f in gate_filters
    ]

    hardening = c.get("red_team_hardening_steps", [])
    cross_refs = c.get("cross_references", [])

    sections = {
        "Problem Framing": problem,
        "Generation Mode (DI #7)": (
            f"**Mode declared:** {gen_mode}  \n"
            f"**Innovation Mandate (DI #12):** {novel_label}  \n"
            f"**Novel invention typology:** {c.get('novel_invention_typology', 'N/A')}"
        ),
        "Proposed Framework": (
            f"**Name:** {framework.get('name', 'N/A')}  \n"
            f"**Description:** {framework.get('description', '')}  \n"
            f"**Detection principle:** {framework.get('detection_principle', '')}  \n"
            f"**Mathematical foundation:** {framework.get('mathematical_foundation', '')}"
        ),
        "Derivation Chain": derivation_text or "(not recorded)",
        "Red-Team Verdict": (
            f"**Verdict:** {rt_verdict}  \n"
            f"**Primary weakness:** {c.get('red_team_primary_weakness', 'N/A')}  \n"
            f"**Hardening steps:**\n" + "\n".join(f"- {s}" for s in hardening)
        ),
        "Statistical Pre-Validation": (
            f"**Precision estimate:** {stat_pre.get('precision_estimate', 'N/A')} "
            f"(CI: {stat_pre.get('precision_ci', 'N/A')})  \n"
            f"**Recall estimate:** {stat_pre.get('recall_estimate', 'N/A')} "
            f"(CI: {stat_pre.get('recall_ci', 'N/A')})  \n"
            f"**FPR estimate:** {stat_pre.get('false_positive_rate_estimate', 'N/A')} "
            f"(CI: {stat_pre.get('fpr_ci', 'N/A')})  \n"
            f"**Confidence:** {stat_pre.get('confidence_in_estimates', 'N/A')}"
        ),
        "Cost Model": (
            f"**User friction:** {cost_model.get('user_friction', 'N/A')}  \n"
            f"**Infrastructure load:** {cost_model.get('infrastructure_load', 'N/A')}  \n"
            f"**False-positive harm:** {cost_model.get('false_positive_harm', 'N/A')}  \n"
            f"**Stakeholder trust impact:** {cost_model.get('stakeholder_trust_impact', 'N/A')}"
        ),
        "Pre-Screen Gate Outcome": (
            f"**Overall outcome:** {gate_outcome}  \n"
            f"**Filter results:**\n" + ("\n".join(filter_lines) if filter_lines else "N/A")
        ),
        "Recommended Deployment Tier": c.get("recommended_deployment_tier", "N/A"),
        "Known Limitations": "\n".join(
            f"- {lim}" for lim in ipr_artifact.get("known_limitations", [])
        ) or "None recorded.",
        "Cross-References": "\n".join(f"- {r}" for r in cross_refs) or "None.",
        "Lineage Trace": (
            f"- Forge artifact: `{artifact_id}`  \n"
            f"- Task ID: `{task_id}`  \n"
            f"- Provenance: {ipr_artifact.get('provenance', [])}"
        ),
    }

    wikilinks = [
        "Forge Agent",
        "Red-Team Agent",
        "Design Invariant 7 — Generation Mode Declaration",
        "Design Invariant 12 — Innovation Mandate",
        "CDI Layer",
        "AIMS Mode B",
        "Constraint Register",
    ]

    path = write_vault_entry(
        subfolder="discoveries",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="forge",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Phase 5 Forge invention — {gen_mode} — {novel_label} — "
            f"Red-Team verdict {rt_verdict} — Pre-Screen Gate: {gate_outcome} — "
            f"Innovation Mandate DI #12 compliance tracked."
        ),
    )

    print(f"[SecondBrain] Forge invention entry written: discoveries/{filename}.md")
    return path


# ─── Phase 6: Full AIMS + Recursive Self-Improvement ─────────────────────────

def write_bottleneck_entry(bottleneck_artifact: dict) -> Path:
    """
    Write to pipelines/ from a bottleneck_report artifact.
    Called by BottleneckDetector immediately after write_artifact().

    Records all identified bottleneck candidates with evidence, confidence,
    priority, and recommended proposals for each.
    """
    c = bottleneck_artifact.get("content", {})
    phase = bottleneck_artifact.get("phase_of_origin", 6)
    artifact_id = bottleneck_artifact.get("artifact_id", "unknown")
    content_hash = bottleneck_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = bottleneck_artifact.get("timestamp_utc", _now_iso())
    limitations = bottleneck_artifact.get("known_limitations", [])

    candidates = c.get("bottleneck_candidates", [])
    n = len(candidates)
    top = candidates[0] if candidates else {}
    top_id = top.get("bottleneck_id", "NONE")
    top_priority = top.get("priority", "UNKNOWN")
    top_confidence = top.get("confidence_score", 0.0)

    telemetry = c.get("telemetry_summary", {})
    analysis_window = c.get("analysis_window_hours", 0)

    summary = (
        f"Phase {phase} bottleneck analysis — {n} candidates identified — "
        f"top: {top_id} ({top_priority}, confidence {top_confidence:.2f})"
    )
    filename = _safe_filename(
        f"Bottleneck Report — Phase {phase} — {artifact_id[:8]}",
        max_len=120,
    )

    candidate_lines = []
    for cand in candidates:
        b_id = cand.get("bottleneck_id", "?")
        desc = cand.get("description", "")
        conf = cand.get("confidence_score", 0.0)
        prio = cand.get("priority", "?")
        evidence = cand.get("evidence", {})
        recs = cand.get("recommendations", [])
        candidate_lines += [
            f"### {b_id} — {prio} Priority (confidence: {conf:.2f})",
            f"**Description:** {desc}",
            f"**Evidence:** {json.dumps(evidence, default=str)[:300]}",
            "**Recommendations:**",
        ] + [f"- {r}" for r in recs] + [""]

    tel_lines = [
        f"- Analysis window: {analysis_window}h",
        f"- LLM calls analyzed: {telemetry.get('llm_calls_analyzed', 'N/A')}",
        f"- Avg latency (s): {telemetry.get('avg_latency_seconds', 'N/A')}",
        f"- P95 latency (s): {telemetry.get('p95_latency_seconds', 'N/A')}",
        f"- Token overhead domains: {telemetry.get('top_token_overhead_domains', [])}",
        f"- Promotion gate pass rate: {telemetry.get('promotion_gate_pass_rate', 'N/A')}",
        f"- FSB age median (days): {telemetry.get('fsb_age_median_days', 'N/A')}",
        f"- FSB age max (days): {telemetry.get('fsb_age_max_days', 'N/A')}",
    ]

    sections = {
        "Telemetry Summary": "\n".join(tel_lines),
        "Bottleneck Candidates": "\n".join(candidate_lines) if candidate_lines else "No candidates identified.",
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Bottleneck report: `{artifact_id}`\n"
            f"- Provenance: {bottleneck_artifact.get('provenance', [])}"
        ),
    }

    wikilinks = [
        "Bottleneck Detector",
        "Phase 7 Proposer",
        "CDI Layer",
        "AIMS Mode A",
        "Few-Shot Bank",
        "Statistician Agent",
        "Orchestrator",
        "Review Queue",
    ]

    path = write_vault_entry(
        subfolder="pipelines",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="bottleneck_detector",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Phase 6 bottleneck analysis — {n} structural bottlenecks identified "
            f"from AIMS Mode A telemetry — top priority: {top_id}"
        ),
    )

    bottleneck_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Bottleneck report written: pipelines/{filename}.md")
    return path


def write_phase7_proposal_entry(proposal_artifact: dict) -> Path:
    """
    Write to aims/ from a phase7_proposal artifact.
    Called by Phase7Proposer immediately after write_artifact().

    Records the improvement proposal, sandbox test result, Proposal Gate
    outcome, and Confirmation Gate routing (DI #2: no auto-approve).
    """
    c = proposal_artifact.get("content", {})
    phase = proposal_artifact.get("phase_of_origin", 6)
    artifact_id = proposal_artifact.get("artifact_id", "unknown")
    content_hash = proposal_artifact.get("content_hash", _file_hash(artifact_id))
    timestamp = proposal_artifact.get("timestamp_utc", _now_iso())
    limitations = proposal_artifact.get("known_limitations", [])

    proposal = c.get("proposal", {})
    bottleneck_id = c.get("bottleneck_id", "UNKNOWN")
    proposal_type = proposal.get("type", "UNKNOWN")
    title = proposal.get("title", "Untitled Proposal")
    description = proposal.get("description", "")
    expected_improvement = proposal.get("expected_improvement", "")
    risk_assessment = proposal.get("risk_assessment", "")
    impl_steps = proposal.get("implementation_steps", [])

    sandbox = c.get("sandbox_test_result", {})
    sandbox_outcome = sandbox.get("outcome", "NOT_RUN")
    sandbox_findings = sandbox.get("findings", [])

    gate = c.get("proposal_gate", {})
    gate_passed = gate.get("gate_passed", False)
    queue_depth = gate.get("queue_depth", 0)
    queue_color = gate.get("queue_color", "UNKNOWN")
    capacity_ceiling = gate.get("capacity_ceiling", 12)

    confirmation_status = c.get("confirmation_gate_status", "AWAITING_DECISION")
    aims_mode = c.get("aims_routing", {}).get("mode", "B")

    summary = (
        f"Phase 7 Proposal — {title[:60]} — "
        f"bottleneck {bottleneck_id} — sandbox: {sandbox_outcome} — "
        f"gate: {'PASSED' if gate_passed else 'BLOCKED'} — Confirmation: {confirmation_status}"
    )
    filename = _safe_filename(
        f"Phase7 Proposal — {bottleneck_id} — {proposal_type} — {artifact_id[:8]}",
        max_len=120,
    )

    impl_lines = [f"{i+1}. {step}" for i, step in enumerate(impl_steps)]
    finding_lines = [f"- {f}" for f in sandbox_findings]

    sections = {
        "Proposal": (
            f"**Title:** {title}  \n"
            f"**Type:** {proposal_type}  \n"
            f"**Addresses bottleneck:** `{bottleneck_id}`  \n"
            f"**Description:** {description}  \n"
            f"**Expected improvement:** {expected_improvement}  \n"
            f"**Risk assessment:** {risk_assessment}"
        ),
        "Implementation Steps": "\n".join(impl_lines) if impl_lines else "Not specified.",
        "Sandbox Test Result": (
            f"**Outcome:** {sandbox_outcome}  \n"
            f"**Findings:**\n" + ("\n".join(finding_lines) if finding_lines else "None recorded.")
        ),
        "Proposal Gate (DI #4 — rate ≤ review capacity)": (
            f"**Gate passed:** {gate_passed}  \n"
            f"**Queue depth:** {queue_depth} / {capacity_ceiling} (ceiling)  \n"
            f"**Queue color:** {queue_color}  \n"
            f"**Rationale:** {gate.get('rationale', 'N/A')}"
        ),
        "Confirmation Gate (DI #2 — no auto-approve)": (
            f"**Status:** {confirmation_status}  \n"
            f"**AIMS routing:** Mode {aims_mode}  \n"
            f"**Human sign-off required:** YES — no auto-approve under any condition.  \n"
            f"Silence ≠ approval. No timeout approval path exists."
        ),
        "Known Limitations": "\n".join(f"- {l}" for l in limitations) if limitations else "None recorded.",
        "Artifact Lineage": (
            f"- Phase 7 proposal: `{artifact_id}`\n"
            f"- Bottleneck report: `{c.get('bottleneck_artifact_id', 'N/A')}`\n"
            f"- Capability Bundle: `{c.get('capability_bundle_id', 'N/A')}`\n"
            f"- Provenance: {proposal_artifact.get('provenance', [])}"
        ),
    }

    wikilinks = [
        "Phase 7 Proposer",
        "Bottleneck Detector",
        "Confirmation Gate",
        "Review Queue",
        "Design Invariant 2 — No Auto-Approve",
        "Design Invariant 4 — Proposal Rate Ceiling",
        "CDI Layer",
        "AIMS Mode B",
        bottleneck_id,
    ]

    path = write_vault_entry(
        subfolder="aims",
        filename=filename,
        summary=summary,
        sections=sections,
        wikilinks=wikilinks,
        source_artifact_id=artifact_id,
        content_hash=content_hash,
        producing_agent="phase7_proposer",
        timestamp_utc=timestamp,
        phase=phase,
        relevance_rationale=(
            f"Phase 7 improvement proposal for {bottleneck_id} — "
            f"type {proposal_type} — sandbox {sandbox_outcome} — "
            f"awaiting operator Confirmation Gate sign-off (DI #2)"
        ),
    )

    proposal_artifact["_vault_path"] = str(path)
    print(f"[SecondBrain] Phase 7 proposal entry written: aims/{filename}.md")
    return path
