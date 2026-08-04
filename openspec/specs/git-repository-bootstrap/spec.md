## Purpose

Define the required bootstrap state for the project's local Git repository and GitHub connection.

## Requirements

### Requirement: Local Git Repository Initialized
The project root SHALL contain a working Git repository with branch `main` as the default local branch.

#### Scenario: Repository exists at the project root
- **WHEN** `git rev-parse --is-inside-work-tree` is run from the project root
- **THEN** it returns `true`

#### Scenario: Default branch is `main`
- **WHEN** `git symbolic-ref --short HEAD` is run from the project root
- **THEN** it returns `main`

### Requirement: Project `.gitignore` Excludes Non-Source Paths
A `.gitignore` file at the project root MUST exclude the local virtual environment, Python tool caches, local environment variables, macOS metadata, and tool-specific state folders from version control.

#### Scenario: `.env` is ignored
- **WHEN** `git check-ignore .env` is run from the project root
- **THEN** it exits with status `0` and prints `.env`

#### Scenario: `venv/` is ignored
- **WHEN** `git check-ignore venv/bin/python` is run from the project root
- **THEN** it exits with status `0` and prints `venv/bin/python`

#### Scenario: Python tool caches are ignored
- **WHEN** `git check-ignore .mypy_cache .pytest_cache .ruff_cache` is run from the project root
- **THEN** it exits with status `0` for every path printed

#### Scenario: macOS metadata is ignored
- **WHEN** `git check-ignore .DS_Store` is run from the project root
- **THEN** it exits with status `0` and prints `.DS_Store`

### Requirement: Initial Commit Snapshots the Working Tree
A commit MUST exist on the `main` branch that snapshots the project root's tracked files (every file the `.gitignore` does not exclude) as they were immediately after repository initialization.

#### Scenario: An initial commit exists
- **WHEN** `git log --oneline` is run from the project root
- **THEN** at least one commit is listed and its subject begins with `chore: bootstrap git repository`

#### Scenario: The initial commit excludes `venv/`
- **WHEN** `git show --stat HEAD` is run from the project root
- **THEN** no path under `venv/` appears in the changed-files list

#### Scenario: The initial commit excludes `.env`
- **WHEN** `git show --stat HEAD` is run from the project root
- **THEN** `.env` does not appear in the changed-files list

### Requirement: GitHub Remote Configured as `origin`
A Git remote named `origin` MUST point at `https://github.com/dgadduci/supernova-ia.git`.

#### Scenario: `origin` remote URL matches the GitHub repository
- **WHEN** `git remote get-url origin` is run from the project root
- **THEN** it returns `https://github.com/dgadduci/supernova-ia.git`

### Requirement: Remote Connection Is Verified
A successful `git fetch origin` MUST confirm that credentials resolve and the remote repository is reachable from the local machine.

#### Scenario: `git fetch origin` exits successfully
- **WHEN** `git fetch origin` is run from the project root
- **THEN** it exits with status `0` and emits no error output

### Requirement: Local Commits Reachable From `origin/main` After Push
After the apply step completes, the local `main` branch MUST have `origin/main` as its upstream and MUST NOT be behind `origin/main` by any commit.

#### Scenario: Local `main` tracks `origin/main`
- **WHEN** `git rev-parse --abbrev-ref --symbolic-full-name @{u}` is run from the project root
- **THEN** it returns `origin/main`

#### Scenario: Local `main` is not behind `origin/main`
- **WHEN** `git rev-list --left-right --count origin/main...HEAD` is run from the project root
- **THEN** the left column (`origin/main` not in `HEAD`) is `0`
