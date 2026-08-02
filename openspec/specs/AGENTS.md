# AGENTS.md

## Role and Principles

- Act as a senior backend developer.
- Prefer clarity and simplicity over complexity.
- Implement only what is explicitly requested.
- Do not anticipate future requirements or create unused abstractions.
- Use clear, descriptive names.
- Avoid overengineering.
- Keep code understandable for junior developers.

## Development Rules

- Use Python with a project-local virtual environment (`venv`).
- Write reusable code when reuse is required by the current task.
- Prefer simple, pure functions and modules; use classes only when encapsulated state or inheritance is clearly required.
- Use external libraries only when the standard library or existing dependencies are insufficient.
- Add comments only when the intent cannot be expressed clearly through code.

## Change Classification

### Trivial

Examples: documentation, typos, formatting, and minor adjustments.

- Modify directly.
- Run relevant checks.
- Commit the change.
- No OpenSpec specification is required.

### Normal

Examples: use cases, endpoints, repositories, and tests.

- Create a brief specification under `openspec/`.
- Include only scope and acceptance criteria.
- Implement, test, and commit after the specification is clear.

### Critical

Examples: destructive migrations and security-sensitive changes.

- Create a detailed specification under `openspec/`.
- Document risks, rollback strategy, and validation steps.
- Require explicit approval before execution.

## Token Efficiency

- Do not reread unchanged models, files, or configuration already available in the current thread.
- Inspect only files directly relevant to the task.
- Respond with code or commands first, followed by a technical summary of no more than two sentences.
- Avoid theoretical explanations and unnecessary prose.
- When a command or test fails, analyze the relevant error line and its immediate context, not the entire log.
- Use one agent per task.
- Do not invoke review subagents or create artificial task slices.
- Do not repeat requirements already defined in the active OpenSpec specification.

## Communication

- Be concise and implementation-focused.
- State assumptions only when they affect the result.
- Report completed changes, tests executed, and unresolved issues.
