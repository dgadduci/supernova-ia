## Context

`openspec/specs/project.md` defines Phase 2 — FastAPI API with general rules followed by a detailed Subphase 2.1 (Comercios) block. The rules establish layering (Router → Service → Repository → Model), one resource per subphase, no generic abstractions until at least two resources need them, tests against `supernova_test`, and minimum-test discipline.

Subphase 2.1 was implemented (the `implement-phase-2` change, archived). Its `project.md` entry has the right heading sections (Scope, Required files, Health endpoint, Commerce endpoints, Schemas, Repository responsibilities, Service responsibilities, Router responsibilities, Minimum tests, Completion criteria) but lacks an explicit two-sentence `Purpose` summary at the top, and the Phase 2 rules are not formalized as a reusable subphase template.

Future subphases (2.2, 2.3, …) will each need their own entry. Without a template, contributors risk drifting in shape (e.g., omitting Router responsibilities, or inventing a new "Auth" section that doesn't belong). Without a placeholder for the next subphase, the roadmap below 2.1 is invisible.

## Goals / Non-Goals

**Goals:**

- Record the canonical Phase 2 subphase template once, in `project.md`, so every future subphase entry follows the same shape.
- Augment the existing Subphase 2.1 entry with a `Purpose` summary paragraph (two sentences) that captures WHY this subphase exists, mirroring the Phase 1 subphase style.
- Add a `Subphase 2.2 — TBD` placeholder in `project.md` so the roadmap below 2.1 has a visible anchor.

**Non-Goals:**

- Pre-scoping Subphase 2.2 (which resource, which endpoints). The placeholder is structural, not prescriptive.
- Modifying the Phase 2 General Rules.
- Touching any `backend/` code, SQLAlchemy models, Alembic config, seed scripts, or databases.
- Creating an OpenSpec change for Subphase 2.2 itself.

## Decisions

- **D1 — Template lives in `project.md` itself, not in a separate file.** Future subphase authors will read `project.md` top-to-bottom; the template sits right under the Phase 2 General Rules, before any subphase, so it is the natural reference.
- **D2 — Template lists the section headings, not their prose content.** The template specifies what sections each subphase must contain; the prose for each section is the per-subphase author's responsibility. This matches how the existing Phase 2 General Rules read.
- **D3 — Subphase 2.1 gets a `Purpose` paragraph added; the rest of its content is left as-is.** Subphase 2.1's section headings already follow the established pattern; only the missing purpose summary is added.
- **D4 — `Subphase 2.2 — TBD` placeholder uses the exact same section headings as Subphase 2.1, with `TBD` in every body.** This makes the placeholder look like a real subphase, signaling that it will be filled in following the template rather than treated as a different kind of entry.
- **D5 — No model/code change.** This is a documentation-only change; `alembic check` is not even required (no model files touched), and no integration tests are added.

## Risks / Trade-offs

- **[Risk] Future subphase authors still drift from the template.** → Mitigation: the template's headings are explicit, and any new subphase that omits one will look visibly different from 2.1 in the diff.
- **[Trade-off] `Subphase 2.2 — TBD` is structurally identical to 2.1 but with `TBD` everywhere.** Acceptable — the placeholder is intentionally content-free; its value is signaling "next subphase to be defined", not pre-deciding scope.
- **[Trade-off] No automated check that a new subphase matches the template.** A future contributor could add a subphase that drifts and the project would not enforce conformance. Acceptable for now; project.md is human-edited, and the next subphase's OpenSpec proposal/design review will catch drift.

## Migration Plan

Not applicable. No code, schema, or runtime change. Only `openspec/specs/project.md` is modified.

## Open Questions

- Which resource is Subphase 2.2? (Out of scope for this change — to be decided when 2.2 is opened.)
- Should future subphases follow a single-resource pattern or batch related resources? The Phase 2 General Rules say "one resource per subphase", so single-resource; this is reaffirmed by adding the placeholder template.
