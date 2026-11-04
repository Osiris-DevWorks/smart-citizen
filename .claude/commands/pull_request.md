---
description: Open a draft PR for the current branch, run the standards self-review with checkpoints, then offer to mark it ready for review
---

# /pull_request

Open or update a **draft** PR for the current branch, run Smart Citizen's documented self-review with checkpoints between each section, then offer to mark it ready for review.

Work through every section in order. After each section, stop at the **CHECKPOINT** and wait for the user to confirm before continuing. Never auto-fix a standards violation without confirming first.

## Arguments

`$ARGUMENTS` may contain:

- `--testing "description"` — manual-test notes the user has already performed. These flow into the *Testing performed* block of the PR body.
- `--skip-draft` — open the PR as ready-for-review immediately and skip the self-review walkthrough. Use only when the user has run the checks elsewhere or is intentionally bypassing the gate.

If no flags are passed, proceed with the default draft-then-walkthrough flow.

## 1. Branching model

- Confirm the current branch is **not** `main`. PRs target the active `release/X.Y.Z` integration branch, never `main` directly.
- Identify the active integration branch: the highest `release/X.Y.Z` that exists on origin (`git ls-remote --heads origin 'release/*'`). The PR's base must match.
- The version suffix signals scope. A patch branch (e.g. `release/1.4.2`) is reserved for **bug fixes and minor polish**. If the diff includes new features or a meaningful behavior change, flag the scope mismatch — do not proceed silently.

**CHECKPOINT — confirm the branching model setup before proceeding.** Wait for the user.

## 2. PR scope

A PR should cover **one concern**: a single feature, a single bug fix, a batch of related bug fixes (same subsystem, same release-branch scope), a self-contained refactor, or a self-contained doc update. Mixed-concern PRs create review burden — surface candidate splits and let the user decide.

Run these against `git diff --name-only $(git merge-base HEAD origin/main)...HEAD` plus `git diff --shortstat`:

- **File-count signal**: more than 8 files touched outside a deliberate cross-cutting change (project-wide rename, doc reorganization, dep bump) → flag for scope review.
- **Net-line signal**: more than ~400 net lines changed, excluding generated files and lock files → flag for scope review.
- **Concern-mixing signal**: scan paths and patches. If any of these are mixed in one diff, list each cluster with its file list and ask the user to confirm or split:
  - feature work in one subsystem + unrelated bug fix in another
  - refactor of existing code + a new feature built on top of it (refactor first, ship, then build)
  - doc rewrite unrelated to the code change
  - "drive-by" formatting or rename edits in files not otherwise needed for the work
- **Title sanity**: if the working title needs "and" or a semicolon to describe both concerns, that's a split signal.

Surface clusters; do not auto-split. If the user confirms the PR is correctly scoped despite a signal trip (e.g. intentional wide-blast refactor), call out the rationale in the PR body so reviewers know what to focus on.

These thresholds are calibration, not laws. A 500-line PR doing one focused thing is easier to review than two 200-line PRs that overlap.

**CHECKPOINT — confirm scope (or explain why a flagged signal is intentional) before opening the draft PR.** Wait for the user.

## 3. Open the draft PR

- Check if a PR already exists for this branch: `gh pr view --json url,body,title,isDraft,number`.
  - **No PR exists**: build title and body per *PR title and body* below, then `gh pr create --base release/X.Y.Z --draft --title "..." --body "..."`.
  - **Draft PR exists**: refresh body (preserve any `- [x]` ticks the user has already applied) and title if needed via `gh pr edit <number>`.
  - **Non-draft PR exists**: pause and ask the user whether to operate on it as-is (no draft revert) or convert to draft (`gh pr ready --undo <number>`). Default: operate as-is.
- Print the PR URL.

If `--skip-draft` was passed, open with `gh pr create` (no `--draft`) and skip directly to step 5; the user takes responsibility for the self-review.

**CHECKPOINT — ready to start the self-review walkthrough?** Wait for the user.

## 4. Self-review walkthrough

Run the three focused checks one at a time. After each check, present findings grouped by severity and stop at the section's CHECKPOINT.

### 4a. Test coverage check
Follow the procedure in `.claude/commands/test_coverage_check.md`. Present findings grouped by severity (Critical / Major / Minor) and end with the verdict line.

**CHECKPOINT — ready for the next check?** Wait for the user.

### 4b. UI / docs / tutorial sync check
Follow the procedure in `.claude/commands/docs_sync_check.md`. Present findings grouped by severity and end with the verdict line.

**CHECKPOINT — ready for the next check?** Wait for the user.

### 4c. Standards spot-check
Follow the procedure in `.claude/commands/standards_check.md`. Present findings grouped by severity and end with the verdict line.

**CHECKPOINT — self-review complete.** Summarize the combined verdict (worst-case of the three). Ask the user one of:

- *"Draft fixes for the Critical/Major findings before marking ready?"*
- *"Mark ready as-is (accepting open findings as known)?"*
- *"Pause — leave the PR as draft, I'll come back to it?"*

Wait for the answer.

## 5. Mark ready (if requested)

When the user is satisfied and explicitly asks to mark ready:

- `gh pr ready <number>`
- Confirm the PR is no longer marked draft.
- Print the final URL.

If the user paused or chose to draft fixes, leave the PR as draft and stop — the user will come back later.

## PR title and body

### Title
- Under 70 chars, imperative, no trailing period.
- Match the repo prefix style when appropriate (`docs:`, `apply:`, `generator:`, `assets:`, etc.).
- If the work was launched via `/begin_work` and the GitHub issue number is known, prefix with `[#NN]`: e.g. `[#42] fix: channel switch loses user.ini overrides`.

### Body

Use a HEREDOC to preserve formatting. When updating an existing PR, fetch the current body, **preserve any `- [x]` ticks** the human has already applied, and refresh items whose surrounding context has changed.

```
## Summary
<1-3 bullets describing what changed and why. If linked to an issue, cite it: "Closes #42.">

## Testing Checklist
- [ ] PR is scoped to one concern (single feature, single bug fix, batch of related bug fixes, self-contained refactor, or self-contained doc update)
- [ ] `pytest tests/` passes locally
- [ ] App launches: `python src/main.py`
- [ ] Affected user-facing flow exercised manually (note which: Apply / Restore / Extract / Reset / Export / Tutorial / other)
- [ ] User-facing strings, `docs/HELP.md`, `docs/ABOUT.md`, and `src/gui/coach_mark.py` reviewed for drift
- [ ] New non-exempt code has matching test coverage in `tests/`
- [ ] Target branch is the active `release/X.Y.Z`, not `main`
- [ ] No direct `QSettings` calls, no hard-coded column indices, no `QProgressBar.setValue()` from workers
- [ ] If new enhancement category: `DATAFORGE_KEEP_SUBPATHS` updated
- [ ] `VERSION.TXT` matches the active release branch

## Testing performed
<!-- If --testing "..." was passed, paste that description here verbatim. Otherwise: "Per the Testing Checklist above." -->

## Post-merge QA
Things to validate after this lands on the integration branch:
- [ ] App launches from a clean checkout of the integration branch (no leftover state)
- [ ] The user-facing flow this PR touches works end-to-end on a real Star Citizen install (note channel: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW)
- [ ] Tutorial coach-marks still land on the correct widgets if any UI controls moved
- [ ] (Add PR-specific items here — e.g. "Verify channel switch preserves `user.ini` overrides," "Verify new enhancement INI is generated for the ships category," "Verify Apply rolls back correctly on validator failure")

---
🤖 PR description generated with [Claude Code](https://claude.com/claude-code) and reviewed by @<github_username>
```

Fetch `<github_username>` via `gh api user --jq '.login'`. If the call fails (no auth, no network), omit the attribution footer rather than blocking the PR.
