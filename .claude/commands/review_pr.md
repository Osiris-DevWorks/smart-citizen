---
description: Review a single GitHub PR with checkpoints between summary, file-by-file walk, and final verdict
---

# /review_pr

Drive a structured review of one PR with human-in-the-loop checkpoints. Adapted from the team's `review_all.md` pattern but scoped to a single PR and tailored to Smart Citizen's layer ordering and standards.

Work through every step in order. After each step, stop at the **CHECKPOINT** and wait for the user before continuing.

## Argument

`$ARGUMENTS` — required, one of:

- A PR number (e.g. `48`)
- A PR URL (e.g. `https://github.com/Osiris-DevWorks/smart-citizen/pull/48`)
- The literal token `current` — resolve the PR for the current branch

If missing or malformed, abort with: */review_pr requires a PR number, URL, or `current`.*

## 1. Gather PR context

Resolve the PR number, then fetch in parallel:

- `gh pr view <N> --json title,body,state,baseRefName,headRefName,author,changedFiles,files,statusCheckRollup,url,isDraft,labels`
- `gh pr diff <N>` — full unified diff (cache this; you'll slice per-file from it later)
- `gh api repos/Osiris-DevWorks/smart-citizen/pulls/<N>/comments` — code-review comments
- `gh api repos/Osiris-DevWorks/smart-citizen/issues/<N>/comments` — general PR conversation
- If the title or body references a GitHub issue (`#NN` or `closes #NN`), fetch it: `gh issue view <NN> --json title,body,labels,state` for context.

Compute the GitHub diff-anchor MD5 for each changed file path upfront so you can link to file diffs in the walkthrough below. Use Python: `hashlib.md5(path.encode()).hexdigest()`. The anchor URL pattern is:

```
https://github.com/Osiris-DevWorks/smart-citizen/pull/<N>/files#diff-<md5>
```

## 2. Summarize the PR

Present a concise summary:

- **What** — scope in plain language.
- **Why** — linked GitHub issue summary if present; otherwise note "no linked issue."
- **Base / head** — target branch and source branch. **Flag if base is not the active `release/X.Y.Z`** — per root `CLAUDE.md` → *Version & Release → Branching model*, PRs target the active integration branch, not `main`.
- **CI status** — pass / fail / pending (from `statusCheckRollup`).
- **Existing comments** — short summary of any prior review comments or conversation.
- **Files changed (N)** — list each file with a one-line description of what it does.

Format example:

```
## PR #48 — [title](url)

**What:** ...
**Why:** linked to #42 — <issue summary>
**Base / head:** release/1.4.2 ← feature/foo-bar
**CI:** ✓ all checks passing
**Existing comments:** none
**Files to review (5):**
  1. src/utils/foo.py — adds Foo helper
  2. tests/test_foo.py — coverage for Foo
  ...
```

**CHECKPOINT — does this summary look right? Ready to start the file-by-file review?** Wait for the user.

## 3. File-by-file review

Order the changed files by Smart Citizen's **layer dependency direction** — most upstream layer first, downstream last. Issues in foundational layers get caught before reviewing code that depends on them.

Layer order (innermost → outermost):

1. `src/models/` — `StringEntry` and domain models
2. `src/parser/` — INI parsing, status classification
3. `src/merger/` — source merge engine
4. `src/utils/` — settings, paths, P4K extraction, pure helpers
5. `src/gui/` — widgets, workers, table model
6. `scripts/` — CLI scripts
7. `tests/` — test suites
8. `docs/` — markdown docs
9. Repo root / config — `CLAUDE.md`, `installer.iss`, `.github/`, `.gitignore`, etc.

For each file in that order:

1. Slice the diff for this file from the cached `gh pr diff` output.
2. Read the **relevant per-directory `CLAUDE.md`** for the file's layer (root `CLAUDE.md` → *Per-directory guides*). That guide is the convention contract for the layer.
3. Review for:
   - **Correctness and logic** — does the change do what the PR description claims?
   - **Project standards** (full list in `.claude/commands/standards_check.md`): direct `QSettings(...)`, hard-coded column indices vs `COL_*` constants, `self.entries[row]` vs `_entry_index_for_row()`, `QProgressBar.setValue()` from worker threads, DataForge subtree coverage (`DATAFORGE_KEEP_SUBPATHS`), `Frontend_PU_Version` stamp bypass, `base.ini` vs `global.ini` naming.
   - **Threading** — workers cleaned up with `quit()` + `wait()`; settings pre-fetched on the main thread; progress through `ProgressSink`; bulk table updates wrapped in `setUpdatesEnabled(False)`.
   - **DRY** (root `CLAUDE.md` → *Code deduplication (DRY)*) — copy-paste blocks ≥5 lines, magic literals in 2+ places, near-duplicate functions.
   - **Test coverage** — non-exempt logic changes need matching tests in `tests/` (exemption table in `.claude/commands/test_coverage_check.md`).
   - **Docs / tutorial drift** — user-facing strings in `src/gui/` should match `docs/HELP.md`, `docs/ABOUT.md`, `src/gui/coach_mark.py`.
4. Present the review for this file:
   - Header is the **linked file path** to the GitHub diff anchor computed in step 1.
   - Plain, simple language — no jargon or hedge phrases.
   - For each issue: relevant line(s), a one-line description, a suggested fix, and a **severity tag** (Critical / Major / Minor) per `/standards_check`'s calibration. Link back to the convention being violated (e.g. *"see `src/gui/CLAUDE.md` → Sortable columns require indirect row lookup"*).
   - If no issues: say so briefly.
   - End with a one-line **file verdict**: **Clean / Minor issues / Needs attention**.

**CHECKPOINT — ready to move to the next file?** Wait for the user. If this is the last file, ask instead: *"Ready for the final verdict?"*

## 4. Final verdict

After every file is reviewed:

- **Overall recommendation** — one of:
  - **Approve** (`gh pr review <N> --approve`)
  - **Request Changes** (`gh pr review <N> --request-changes`)
  - **Comment** (`gh pr review <N> --comment`)
- **Issue acceptance check** — for each acceptance criterion or task in the linked GitHub issue, state whether the diff satisfies it. If no issue is linked, note this and skip the AC check.
- **Summary of all issues found**, grouped by severity:
  - **Critical** (blocking merge) — what they are, where, fix hint.
  - **Major** (should fix before merge).
  - **Minor** (consider).
- **Action items** as a checklist the PR author can work through.

Include the full PR URL at the end so the user can click through.

**CHECKPOINT — pause and ask:** *"Post the review now (`gh pr review` with the chosen recommendation), draft inline comments for specific findings before posting, or just print the summary and stop?"* Wait for the user. **Do not post a review or any comments without explicit confirmation.**

## Tone

- Be constructive and educational.
- Assume positive intent.
- Explain *why* behind each suggestion — link to the relevant `CLAUDE.md` section when it documents the convention being violated.
- Offer specific examples, not vague principles.
- Balance criticism with notes on what was done well.
- Focus on the code, not the person.
