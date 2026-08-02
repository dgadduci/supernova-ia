## 1. Add the Phase 2 subphase template

- [x] 1.1 In `openspec/specs/project.md`, under `### Phase 2 — FastAPI API` and after the existing `General Rules` block, add a `### Subphase Template` section that enumerates the required headings: Scope, Required files, [resource-specific endpoint block], Schemas, Repository responsibilities, Service responsibilities, Router responsibilities, Minimum tests, Completion criteria

## 2. Augment Subphase 2.1 with a Purpose summary

- [x] 2.1 In `openspec/specs/project.md`, prepend a short `Purpose` paragraph (one to two sentences) to the `### Subphase 2.1 — Comercios` entry, summarizing why this subphase exists (minimum FastAPI infrastructure + first vertical slice anchored on the existing `Comercio` model) and what it delivers (three commerce endpoints under the documented layering)

## 3. Add the Subphase 2.2 placeholder

- [x] 3.1 In `openspec/specs/project.md`, immediately after Subphase 2.1, add a `### Subphase 2.2 — TBD` entry with the same heading sections as Subphase 2.1 (Scope, Required files, Schemas, Repository responsibilities, Service responsibilities, Router responsibilities, Minimum tests, Completion criteria), each with body content set to `TBD` and no specific resource name, endpoint, schema, or test scenario mentioned

## 4. Verification

- [x] 4.1 Read `openspec/specs/project.md` end-to-end and confirm: (a) the new `### Subphase Template` section appears exactly once under Phase 2; (b) Subphase 2.1 opens with the new Purpose paragraph; (c) Subphase 2.2 placeholder appears after 2.1 and contains only `TBD` bodies
- [x] 4.2 Confirm no file under `backend/`, `backend/models/`, `backend/alembic/`, `backend/db/`, or `backend/tests/` was modified by this change (`git status` would show only `openspec/specs/project.md`, but this is a non-git repo, so verify by listing file mtimes against the change's start time)
- [x] 4.3 Confirm no Alembic revision was created (`ls backend/alembic/versions/` shows only the original `7f9610191db8_initial_schema.py`)
