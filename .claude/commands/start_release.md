---
description: Open the next release/X.Y.Z branch off main and bump VERSION.TXT (major|minor|patch)
---

# /start_release

Open the next integration branch per the documented release model. Bumps `VERSION.TXT` and commits the kickoff change locally. Does **not** push — the user pushes when ready.

## Argument

`$ARGUMENTS` — required, one of `major`, `minor`, `patch`. Determines how to bump the current `VERSION.TXT`:

- `major`: `X.Y.Z` → `(X+1).0.0`
- `minor`: `X.Y.Z` → `X.(Y+1).0`
- `patch`: `X.Y.Z` → `X.Y.(Z+1)`

If `$ARGUMENTS` is empty or not exactly one of the three values, abort and ask the user for the missing arg. Do not guess.

## Procedure

Stop on the first failure of any step. Never proceed past a failed check.

### 1. Validate the argument
`$ARGUMENTS` must be exactly `major`, `minor`, or `patch` (case-sensitive). Otherwise abort with: `"/start_release requires one of: major, minor, patch"`.

### 2. Read and parse VERSION.TXT
Read `VERSION.TXT`. Strip whitespace. Split on `.` — must yield exactly three non-negative integers. If parsing fails, abort with the offending content.

### 3. Compute the next version
- `major` → bump first part, reset second and third to `0`
- `minor` → bump second part, reset third to `0`
- `patch` → bump third part only

Build `NEW_VERSION = "X.Y.Z"` and `NEW_BRANCH = "release/X.Y.Z"`.

### 4. Safety preconditions
Run each. Abort on the first failure.

- **On main**: `git branch --show-current` must equal `main`. If not, abort: *"Switch to main before starting a release."*
- **Clean working tree**: `git status --porcelain` must be empty. If dirty, abort and list the offending files: *"Working tree has uncommitted changes; commit or stash before starting a release."*
- **main up to date with origin** (best-effort): try `git fetch origin main`. If the fetch succeeds, check `git rev-list --count main..origin/main`. If > 0, abort: *"Local main is behind origin/main. Pull before starting a release."* If the fetch itself fails (no network, no origin), warn the user but proceed — don't block on offline work.
- **Branch does not already exist**:
  - Local: `git rev-parse --verify NEW_BRANCH` must fail (exit non-zero). If it succeeds, abort: *"NEW_BRANCH already exists locally."*
  - Remote: `git ls-remote --heads origin NEW_BRANCH` must return empty. If non-empty, abort: *"NEW_BRANCH already exists on origin."*

**CHECKPOINT — about to create `NEW_BRANCH` and bump `VERSION.TXT` from `<current>` → `NEW_VERSION`. Confirm to proceed.** Wait for the user before doing anything in steps 5–7.

### 5. Create the branch
`git checkout -b NEW_BRANCH` from `main`.

### 6. Update VERSION.TXT
Overwrite `VERSION.TXT` with `NEW_VERSION` followed by a single newline. Preserve UTF-8 / no-BOM.

### 7. Commit the kickoff
Stage `VERSION.TXT` only — nothing else should be touched at this point. Commit message:

```
git add VERSION.TXT && git commit -m "$(cat <<'EOF'
Bump version to NEW_VERSION

Branch-opening commit for the NEW_VERSION integration target.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Substitute `NEW_VERSION` literally in the message.)

### 8. Report

Print:
- `Branch created: NEW_BRANCH`
- `VERSION.TXT: <old> → NEW_VERSION`
- Scope reminder based on the bump type:
  - `patch` → *"Patch branches accept only bug fixes and minor polish. Flag any feature work as scope-mismatch."*
  - `minor` → *"Minor branches accept features and polish."*
  - `major` → *"Major branches accept breaking changes."*
- *"Branch is local only — push with `git push -u origin NEW_BRANCH` when ready. Features are pushed straight to this branch (no feature PRs); only the release PR goes to main."*

## Notes

- This command never pushes. The session pattern is: open locally, commit the kickoff, let the user push when they're ready.
- This command never tags. Tags are part of the release-ship checklist (root `CLAUDE.md` → *Release checklist*), not the open-branch step.
- If a previous release was not merged to `main` yet (i.e. there is still an open `release/X.Y.Z` integration branch), this command will still proceed once the user is back on `main` — but the user should know that opening the *next* release branch before the *current* one ships is unusual. Surface the existence of any open `release/X.Y.*` branches in the final report.
