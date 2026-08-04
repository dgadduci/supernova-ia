## Why

The local working directory has no Git repository and is therefore not connected to the existing remote `supernova-ia` on GitHub. Without version control, every change to the codebase is lost on disk failure, collaboration is impossible, and there is no audit trail of what was implemented across the many subphases already documented in `openspec/specs/project.md`. This subphase establishes local version control and wires the local repo to the upstream remote so subsequent subphases can commit, push, and pull.

## What Changes

- Initialize a Git repository at the project root (currently `fatal: not a git repository`).
- Add a project `.gitignore` that excludes `venv/`, Python cache directories (`__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`), `.env`, `.DS_Store`, and editor/metadata folders not relevant to the application.
- Create an initial commit that snapshots the current working tree under that `.gitignore`. The commit message records the bootstrap intent.
- Add the GitHub remote `https://github.com/dgadduci/supernova-ia.git` as `origin` (HTTPS; credential helper or PAT expected).
- Verify the connection by inspecting `git remote -v` and fetching (without merging) to confirm credentials and network reachability.

No application code, FastAPI endpoints, SQLAlchemy models, Alembic migrations, or Pydantic schemas are introduced. No existing file outside `.gitignore` is modified — only added to version control.

## Capabilities

### New Capabilities

- `git-repository-bootstrap`: Establishes a local Git repository, a project `.gitignore`, an initial commit, and the `origin` remote pointing at the existing GitHub repository `supernova-ia`.

### Modified Capabilities

None. No existing capability's REQUIREMENTS change; this subphase only adds infrastructure.

## Impact

- New file: `.gitignore` at the project root.
- New directory: `.git/` at the project root (created by `git init`).
- New Git config: `remote.origin.url = https://github.com/dgadduci/supernova-ia.git`.
- No application source files (`backend/**`, `openspec/**`, `alembic.ini`, `requirements.txt`, `ejemplo.py`) are modified — they become tracked under the initial commit.
- Excluded from tracking: `venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.env`, `.DS_Store`, `.opencode/`, `node_modules/` (only relevant if present at root).
- Credentials: HTTPS remote — push/pull will use the configured Git credential helper or a Personal Access Token. No SSH key configuration is in scope.
