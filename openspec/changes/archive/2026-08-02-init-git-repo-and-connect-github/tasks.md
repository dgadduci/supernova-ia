## 1. Pre-flight Checks

- [x] 1.1 Verify `git` is installed and on PATH (`git --version`)
- [x] 1.2 Verify `git config user.name` and `git config user.email` return non-empty values; if either is empty, prompt the user and stop before any commit

## 2. Author the `.gitignore`

- [x] 2.1 Create `.gitignore` at the project root containing patterns for `venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.env`, `.DS_Store`, `.opencode/`, `.atl/`, `node_modules/`, `*.py[cod]`, `*.egg-info/`, `dist/`, `build/`, `.idea/`, `.vscode/`
- [x] 2.2 Run `git check-ignore .env venv/bin/python .mypy_cache .pytest_cache .ruff_cache .DS_Store` and confirm every path returns exit status `0`

## 3. Initialize the Local Repository

- [x] 3.1 Run `git init -b main` at the project root
- [x] 3.2 Confirm with `git rev-parse --is-inside-work-tree` (expect `true`) and `git symbolic-ref --short HEAD` (expect `main`)

## 4. Create the Initial Commit

- [x] 4.1 Run `git status` to confirm only intended, non-ignored paths appear (no `venv/`, `.env`, caches, or tool folders)
- [x] 4.2 Run `git add .`
- [x] 4.3 Run `git commit -m "chore: bootstrap git repository"` with a body listing the three actions (`.gitignore`, `git init`, `origin` remote)
- [x] 4.4 Confirm `git log --oneline` lists the commit and `git show --stat HEAD` shows no `venv/` or `.env` paths

## 5. Add the GitHub Remote

- [x] 5.1 Run `git remote add origin https://github.com/dgadduci/supernova-ia.git`
- [x] 5.2 Confirm `git remote -v` shows the URL under both `fetch` and `push`

## 6. Verify Remote Reachability

- [x] 6.1 Run `git fetch origin` and confirm exit status `0` (no authentication or network errors)
- [x] 6.2 Inspect `git remote show origin` (or `git ls-remote origin`) to detect the remote's default branch and any existing commits

## 7. Push the Initial Commit

- [x] 7.1 If `origin/main` does not yet exist, run `git push -u origin main`
- [x] 7.2 If `origin/main` exists with unrelated history, run `git pull origin main --allow-unrelated-histories --rebase` then `git push origin main`
- [x] 7.3 If divergence cannot be resolved by rebase, stop and ask the user before any force-push

## 8. Final Verification

- [x] 8.1 Run `git rev-parse --abbrev-ref --symbolic-full-name @{u}` and confirm it returns `origin/main`
- [x] 8.2 Run `git rev-list --left-right --count origin/main...HEAD` and confirm the left column is `0`
- [x] 8.3 Run `git status` and confirm a clean working tree (no uncommitted changes)
- [x] 8.4 Run `git log --oneline` and report the initial commit hash to the user
