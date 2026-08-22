# `docs/`

Process documentation and the figures used by the repository README and the knowledge-vault sample.

| Path | What it is |
|---|---|
| `engineering_process.md` | How the system was built: the three-document specification hierarchy, the persistent continuity layer, the operating directives, the phase gates, and seven worked entries from the change log. |
| `images/banner.png` | Repository banner, 1320×330. Used as the README hero image. |
| `images/social-preview.png` | The same artwork padded to 1320×660 for GitHub's 2:1 social card, which centre-crops anything wider. Uploaded under Settings → General → Social preview; not referenced inline. |
| `images/repo_structure.png` | Annotated top-level directory structure, labelled by the architectural role each folder plays. |
| `images/knowledge_architecture.png` | How notes, metrics, dimensions, agents and governance records interlink across the knowledge vault. |

`engineering_process.md` is the file to read if the build methodology interests you more than the architecture. Its change-log section is not a highlight reel — the seven entries were chosen because they record friction. They include a deterministic veto that blocked 14 of 18 Storyteller runs during Phase 1 development before it was calibrated correctly; a design specification rewritten into five enforcement layers because a document alone could not bind anything; an automated conformance audit that found sixteen palette violations in an artifact already reviewed by eye; a compliance audit that found thirteen gaps, of which eleven were closed and two formally deferred; a documentation-drift pass whose five findings produced three fixes and two refusals; a correct fix logged as a violation *because it had not been logged*; and a session that exceeded its own context budget, skipped its closing obligations, and was logged against itself.

The last one is the reason this folder exists in the repository rather than as a private note. A process that only records the cases where it worked is not evidence that the process works.
