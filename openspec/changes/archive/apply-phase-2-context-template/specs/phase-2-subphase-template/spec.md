## ADDED Requirements

### Requirement: Phase 2 subphase template exists in project.md
The system SHALL record, in `openspec/specs/project.md` under `### Phase 2 — FastAPI API`, a `### Subphase Template` section that names every heading each Phase 2 subphase entry must contain (Scope, Required files, [resource-specific endpoint block], Schemas, Repository responsibilities, Service responsibilities, Router responsibilities, Minimum tests, Completion criteria).

#### Scenario: Subphase 2.1 already conforms to the template
- **WHEN** the Subphase 2.1 entry is compared against the template headings
- **THEN** every template heading has a corresponding section in Subphase 2.1

#### Scenario: Template is recorded once
- **WHEN** the template section is added
- **THEN** the project.md diff contains exactly one `### Subphase Template` heading under `### Phase 2 — FastAPI API`

### Requirement: Subphase 2.1 has a Purpose summary
The system SHALL prepend a `Purpose` paragraph (one to two sentences) to the Subphase 2.1 entry in `openspec/specs/project.md`, summarizing why this subphase exists and what it delivers, mirroring the Phase 1 subphase style.

#### Scenario: Purpose paragraph is present
- **WHEN** the Subphase 2.1 entry is read in `project.md`
- **THEN** the entry opens with a short paragraph before its Scope section

### Requirement: Subphase 2.2 placeholder exists
The system SHALL add a `### Subphase 2.2 — TBD` entry in `openspec/specs/project.md` immediately after Subphase 2.1, using the same section headings as Subphase 2.1 with `TBD` in every body field, and no content beyond the template headings.

#### Scenario: Placeholder exists and is content-free
- **WHEN** the Subphase 2.2 placeholder is read
- **THEN** every body field under the template headings is `TBD`

#### Scenario: Placeholder does not pre-scope a resource
- **WHEN** the Subphase 2.2 placeholder is read
- **THEN** no specific resource name, endpoint, schema name, or test scenario is mentioned beyond `TBD`
