# Capability: completed-subphase-context-condensation

## Purpose

Keep `openspec/specs/project.md` concise by replacing each completed subphase entry with a short summary that preserves only what future work needs.

## Requirements

### Requirement: Completed subphase entries are condensed
When a subphase is marked completed (`[x]`), its entry in `openspec/specs/project.md` SHALL be replaced by a short summary that preserves only:
- permanent implementation decisions;
- completed outcomes;
- architectural constraints introduced;
- relevant files or components created or modified;
- context required by future work.

The summary SHALL NOT contain:
- procedural steps;
- implementation instructions already executed;
- examples;
- temporary prompts;
- detailed test procedures;
- repeated explanations;
- discarded alternatives;
- rules already defined elsewhere.

The requirement applies to every completed subphase of every phase.

#### Scenario: Completed subphase summary preserves required categories
- **WHEN** a completed subphase entry is read in `project.md`
- **THEN** its content maps only to one of the five preserved categories (decisions, outcomes, constraints, files, future context)

#### Scenario: Completed subphase summary excludes disallowed categories
- **WHEN** a completed subphase entry is read in `project.md`
- **THEN** it does not contain procedural steps, executed instructions, examples, temporary prompts, detailed test procedures, repeated explanations, discarded alternatives, or rules already defined elsewhere

#### Scenario: Condensation applies across all phases
- **WHEN** the entries for all completed subphases across all phases are read
- **THEN** each one satisfies the two preceding scenarios
