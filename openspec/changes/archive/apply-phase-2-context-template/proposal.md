## Why

Phase 2 was scoped with "General Rules" + a fully detailed Subphase 2.1, but no explicit subphase template was recorded, and no placeholders for the next subphases exist in `openspec/specs/project.md`. Without a template, future subphase entries are at risk of drifting in shape (different headings, missing sections, inconsistent depth). Without placeholders, there is no roadmap signal for what comes after 2.1.

## What Changes

- Add a `### Subphase Template` section to `openspec/specs/project.md` under `Phase 2 — FastAPI API`, describing the consistent shape each Phase 2 subphase entry must follow (Scope, Required files, [resource-specific endpoint block], Schemas, Repository responsibilities, Service responsibilities, Router responsibilities, Minimum tests, Completion criteria).
- Augment Subphase 2.1 with an explicit `### Subphase 2.1 — Comercios` heading block whose purpose statement summarizes the goal in two sentences, mirroring the Phase 1 subphase style.
- Add a placeholder `### Subphase 2.2 — TBD` entry with the same shape as Subphase 2.1 but with `TBD` in every field. The actual scope of 2.2 will be defined when the next resource is chosen; this placeholder exists only to anchor the roadmap and signal "next".

## Capabilities

### New Capabilities

- `phase-2-subphase-template`: The structural template that every Phase 2 subphase entry in `openspec/specs/project.md` must follow, plus a `Subphase 2.2 — TBD` placeholder.

### Modified Capabilities

_None._ No requirements for application behavior change; this is a documentation/roadmap update only.

## Impact

- **Modified file**: `openspec/specs/project.md`.
- **Untouched**: all `backend/` code, all SQLAlchemy models, all Alembic migrations, all seed scripts, both databases.
- **Out of scope**: defining what 2.2 actually builds (no resource chosen yet). The placeholder exists only to anchor the next entry, not to pre-scope it.
