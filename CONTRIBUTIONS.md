# Team responsibilities and contribution record

Recorded: 2 November 2026.

## Declared responsibilities

The project lead supplied the following role allocation. It describes responsibility
areas; it does not establish who authored individual existing changes. Historical
contribution evidence and teammate confirmation have not yet been recorded here.

| Team member  | GitHub profile                                | Declared responsibility               | Relevant areas for contribution review                                                                                                                |
| ------------ | --------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Param        | [Param2725](https://github.com/Param2725)     | Backend                               | `backend/app/api/`, `core/`, `db/`, `repositories/`, `schemas/`, `pricing/`, `ingestion/`, `channels/`, `quotes/` and `workers/`; Alembic migrations. |
| Yash         | [tempyash007](https://github.com/tempyash007) | Frontend                              | `dashboard/src/` and `widget/src/`: pages, components, typed API clients, styles and user interactions.                                               |
| Panthil      | [PanthilShah](https://github.com/PanthilShah) | Testing                               | `backend/tests/`, `dashboard/e2e/`, frontend `*.test.ts` / `*.test.tsx` files and test configuration.                                                 |
| Project lead | [aum2606](https://github.com/aum2606)         | AI-related work and project oversight | `backend/app/agents/`, `llm/`, `orchestrator/`, `tools/`, AI evaluation design, architecture, integration and project coordination.                   |

These areas overlap. For example, AI evaluation work may involve the lead and Panthil;
API integration may involve Param and Yash. Assign credit to the actual contribution,
not automatically to everyone whose responsibility area includes a file.

Personal email addresses are omitted from this document. Where commit attribution is
appropriate, contributors should confirm their preferred GitHub-linked email or
GitHub-provided no-reply address before use.

## Historical attribution review

The existing repository history is preserved. Role allocation alone does not justify
changing past commit authors or dates. Record each substantiated contribution using:

| Field              | Information to record                                                                                     |
| ------------------ | --------------------------------------------------------------------------------------------------------- |
| Contributor        | Name and GitHub username.                                                                                 |
| Work performed     | A concrete description of implementation, testing, design, documentation or review.                       |
| Relevant changes   | File paths, original commit references, pull requests or identifiable sections.                           |
| Work period        | Actual dates supported by the available records; state when dates are unknown.                            |
| Evidence           | Original patch, draft, review discussion, issue, test report or other relevant work record.               |
| Confirmation       | Contributor confirmation of the work and preferred attribution.                                           |
| Attribution action | Contribution note, co-author credit for shared authorship, or correction of a genuinely incorrect author. |

No historical authorship corrections have been made as part of this responsibility
record. Repository commit dates and any separately evidenced work period are distinct
facts. Review credit should identify review work rather than imply code authorship.

## Collaboration workflow

1. Create an issue for a concrete task and identify its owner and acceptance criteria.
2. The contributor performs the work on a branch using their own Git identity and
   accurate commit dates. Shared authorship can be credited with consent.
3. Open a pull request describing what changed and the relevant verification.
4. Another teammate reviews it; the project lead coordinates integration. Keep the
   repository's pricing, tenant-isolation, model and testing requirements intact.
5. Link the merged change and any meaningful design or testing evidence in the
   contribution record. Describe AI assistance accurately where relevant.

Any proposed correction to published history should first have a recoverable backup,
a precise before/after attribution map and team coordination. It should correct the
record, not manufacture an earlier development timeline or unsupported participation.

## Current follow-up

- [x] Record the project lead's declared team responsibilities and relevant review areas.
- [ ] Obtain concrete contribution records and confirmation from each teammate.
- [ ] Review justified attribution corrections, if any, without inventing dates.
- [ ] Record subsequent individual work through issues, commits, pull requests and reviews.

The product specification is [BUILD_PLAN.md](BUILD_PLAN.md), the shared vocabulary is
[UBIQUITOUS_LANGUAGE.md](UBIQUITOUS_LANGUAGE.md), and verification and pending launch
work are recorded in [PROGRESS.md](PROGRESS.md).
