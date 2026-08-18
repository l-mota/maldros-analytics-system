# `case-study/`

The published case study and its derivative formats. The HTML page is the source of truth; every other format here was built from it rather than authored independently, so a discrepancy between them is a defect, not a variation.

**Viewing these.** GitHub renders Markdown and PDF in the file browser but displays `.html` as source, so the three HTML documents are served from GitHub Pages instead: [the case study](https://l-mota.github.io/maldros-analytics-system/case-study/), [the AIMS Mode B report](https://l-mota.github.io/maldros-analytics-system/case-study/aims_mode_b_report.html), and [the operator console mockup](https://l-mota.github.io/maldros-analytics-system/case-study/operator_ui_mockup.html). The PDF is readable from this folder directly; the deck downloads.

| File | What it is |
|---|---|
| `index.html` | The full case study. Long-form, self-contained, with interactive architecture and lifecycle diagrams. Start here. |
| `maldros_executive_summary.pdf` | Two pages: finding, KPIs, recommendation. Static fallbacks only — no interactive elements. |
| `maldros_case_study_deck.pptx` | Eleven slides, one primary statement each. |
| `aims_mode_b_report.html` | **A real generated output** — the actual stakeholder briefing the pipeline produced, rendered by `scripts/render_aims_report.py`. Not a description of one. |
| `operator_ui_mockup.html` | The six-dashboard operator console as an approved design-system reference. **Not running software, not wired to data, and not a screenshot of anything.** |

Every file here implements the project's visual design system: four data-meaning colours with permanently locked semantics, a four-tier typography hierarchy, and a conclusion-first construction rule requiring every chart to carry a narrative title and an insight summary before its body. The tokens are defined once in `lib/design_tokens.css` and `lib/design_tokens.py` — hand-editing a colour in a consumer file instead of the token source is itself a design-system violation.

Two of these files are worth opening for opposite reasons. `aims_mode_b_report.html` is evidence: it shows what the pipeline actually emits. `operator_ui_mockup.html` is a design artifact and proves nothing about runtime behaviour — it is captioned that way everywhere it appears, and it is captioned that way here.
