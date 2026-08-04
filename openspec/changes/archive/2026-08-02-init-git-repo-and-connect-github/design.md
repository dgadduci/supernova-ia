## Context

The working directory `/Users/diegoadducilagreca/Documents/supernova-ia` currently has no `.git/` directory (confirmed: `git status` → `fatal: not a git repository`). The repository exists remotely at `https://github.com/dgadduci/supernova-ia` but has no local counterpart. The working tree contains a Python virtual environment (`venv/`), Python cache directories (`.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`), local-only secrets (`.env`), macOS metadata (`.DS_Store`), tool folders (`.opencode/`, `.atl/`), application code (`backend/`, `alembic.ini`, `requirements.txt`), an `openspec/` planning folder, and a scratch file (`ejemplo.py`).

The project has been developed across many subphases documented in `openspec/specs/project.md` (Phases 1, 2.1–2.14, 3.1–3.3 complete; Phase 3 continues) without version control. This subphase closes that gap. After completion, all subsequent subphases can `git add`, `git commit`, and `git push` their changes.

## Goals / Non-Goals

**Goals:**
- A working local Git repository at the project root with branch `main`.
- A `.gitignore` that prevents `venv/`, Python caches, `.env`, `.DS_Store`, and tool metadata folders from being tracked.
- An initial commit that snapshots the current working tree (excluding ignored paths) before any subphase change is made.
- The remote `origin` pointing at `https://github.com/dgadduci/supernova-ia.git`.
- Successful fetch from `origin` that confirms credentials and network reachability.
- A clearly documented push strategy that handles the common case where the remote already has commits (README, license, etc.).

**Non-Goals:**
- Setting or modifying `git config user.name` / `user.email` (assumed pre-configured globally; prompt the user during apply if not).
- Switching the remote to SSH (HTTPS is locked in by the user).
- Creating branches, tags, or release workflows beyond `main`.
- Configuring CI/CD, branch protection rules, or GitHub Actions.
- Migrating or rewriting history of any existing remote content.
- Tracking `.opencode/`, `.atl/`, or any other tool-specific metadata folder.

## Decisions

### D1 — HTTPS remote with the URL provided by the user
The remote is `https://github.com/dgadduci/supernova-ia.git`. HTTPS is portable across machines without SSH key setup; pushes/pulls will use the system Git credential helper or a Personal Access Token. No `.git/config` `insteadOf` rewrite rules are introduced.

### D2 — Default branch `main`
`git init -b main` so the local default branch matches GitHub's modern default. If the remote default branch is `master`, the local branch is still created as `main` and the push step aligns the remote tracking branch explicitly (`git push -u origin main`).

### D3 — `.gitignore` written before the first commit
The `.gitignore` is created as a real file before `git add .` runs. This guarantees that `.env`, `venv/`, and cache directories are excluded from the very first snapshot and never become tracked. Writing it after the fact would risk committing secrets.

Observed exclusion set (verified by listing the project root):
- `venv/` — local virtual environment (large, not portable)
- `__pycache__/` — Python bytecode
- `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` — tool caches
- `.env` — local environment variables (may contain DB credentials)
- `.DS_Store` — macOS Finder metadata
- `.opencode/`, `.atl/` — tool/IDE-specific state
- `node_modules/` — only present if any node tool is added later; safe to exclude preemptively
- Standard Python build artifacts: `*.py[cod]`, `*.egg-info/`, `dist/`, `build/`
- Editor configs: `.idea/`, `.vscode/`

### D4 — Initial commit message: `chore: bootstrap git repository`
Conventional-Commits-style prefix (`chore:`) signals infrastructure work with no production code change. The body lists the three actions taken (`.gitignore`, `git init`, `origin` remote) so future readers understand what the snapshot represents.

### D5 — Push strategy tolerates unrelated remote history
The remote may already contain commits (e.g., a GitHub-default `README.md` or `LICENSE`) from when the empty repo was created. Two acceptable resolution paths during apply:
1. **Preferred**: `git pull origin main --allow-unrelated-histories --rebase` then `git push origin main`. Preserves both histories.
2. **Fallback**: if the remote's only commit(s) are auto-generated and overlap nothing in the local snapshot, `git push origin main --force-with-lease` is acceptable after explicit user confirmation.

The apply step must surface which path it took and stop with an error if neither resolves cleanly.

### D6 — No submodules, no LFS, no signed commits
This subphase does not introduce Git submodules, Git LFS, or GPG-signed commits. Those can be layered on later if needed.

## Risks / Trade-offs

- **[Risk] Remote already has unrelated commits** → Mitigation: D5 documents the pull-rebase path as the preferred resolution; the apply step pauses if divergence exceeds a single trivial commit.
- **[Risk] `.env` already contains secrets that could be committed** → Mitigation: D3 writes `.gitignore` before the first `git add`; the apply step also verifies `.env` is untracked with `git check-ignore .env` before committing.
- **[Risk] `git config user.name` / `user.email` not set** → Mitigation: apply step runs `git config user.name`/`user.email` checks and prompts the user; it does not auto-set global config.
- **[Risk] HTTPS push fails due to missing credentials** → Mitigation: apply step runs `git fetch origin` first as a non-destructive credential check; if it fails, the step reports the error and stops without leaving the repo half-configured.
- **[Risk] Future subphases re-introduce ignored files by mistake** (e.g., `venv/` moved into a subdirectory) → Mitigation: the `.gitignore` is committed; future `git add` commands will respect it; CI (not in scope here) can later enforce.
- **[Trade-off] Forcing `main` over `master`** — if the remote's default branch is `master`, `git push -u origin main` will create `main` on the remote but the remote default may still be `master`. Acceptable for this subphase; a follow-up can rename the remote default.

## Migration Plan

This subphase is purely additive — there is no existing Git state to migrate. The steps executed during apply are:

1. Write `.gitignore` at the project root.
2. Run `git init -b main` in the project root.
3. Run `git check-ignore .env venv` to verify ignore patterns resolve correctly.
4. Run `git add .` and `git status` to confirm only intended files are staged.
5. Run `git commit -m "chore: bootstrap git repository"` (with a multi-line body listing the three actions).
6. Run `git remote add origin https://github.com/dgadduci/supernova-ia.git`.
7. Run `git fetch origin` to validate credentials and reachability.
8. Inspect divergence (`git log --oneline origin/main..HEAD` and the reverse) and apply D5's preferred or fallback strategy.
9. Run `git push` per the chosen strategy.
10. Run `git remote -v` and `git status` as the final verification step; report the result.

Rollback: if any step fails after `.git/` is created, `rm -rf .git` reverts to a clean working directory. The `.gitignore` file remains on disk and can be left in place (it is the only intentional non-Git artifact created).

## Open Questions

- **Q1 — Remote default branch**: is the existing GitHub repo's default branch `main` or `master`? The apply step will detect this via `git remote show origin` and adapt D5/D2 accordingly.
- **Q2 — Existing remote content**: does the remote already contain a `README.md`, `LICENSE`, or `.gitignore`? If so, the preferred rebase path (D5) is mandatory. The apply step will detect via `git ls-remote origin` before pushing.
- **Q3 — Git identity**: are `user.name` and `user.email` configured globally? If not, the apply step will ask the user before committing.
