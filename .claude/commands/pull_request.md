---
description: Open (or update) the release/X.Y.Z -> main release PR, or a hotfix PR into main, then run the one code review
---

# /pull_request

Under the Osiris DevWorks pipeline (root `CLAUDE.md`, top section) there are no feature PRs: features are pushed straight to the active `release/X.Y.Z`. This command opens the PRs that remain: the release PR (`release/X.Y.Z` → `main`) and, with `--hotfix`, a hotfix PR from a branch cut off `main` into `main`. CI, the Claude review workflow and the preview builds all run on these PRs.

Contributor PRs into a release branch are opened by their authors; review them with `/review_pr` (CI runs on them, the Claude review bot does not).

## Arguments

`$ARGUMENTS` may contain:

- `--hotfix` — the current branch is a hotfix branch off `main`; open its PR into `main`.
- `--testing "description"` — manual-test notes for the *Testing performed* block.

## 1. Preflight

- Release: identify the active integration branch, the highest unmerged `release/X.Y.Z` on origin (`git ls-remote --heads origin 'release/*'`), and confirm `VERSION.TXT` on it matches. `/PRE_RELEASE` normally opens this PR as part of its tester-build step; if it already did, just refresh the body.
- Hotfix: confirm the branch is based on `origin/main` (`git merge-base --is-ancestor origin/main HEAD`) and holds only the fix.

## 2. Open or update the PR

- Check for an existing PR with the same head and base (`gh pr view` / `gh pr list --head <branch> --base main`) and update it rather than opening a second.
- Release title: `Release X.Y.Z`. Hotfix title: `Hotfix X.Y.Z: <summary>` (bump the patch version on the hotfix branch).
- Build the body per *PR title and body* below, listing every feature commit in `git log --oneline origin/main..HEAD`.

## 3. Review

- Run `/review_pr <number>` and walk Amr through its findings one by one. Fix them with commits pushed to the release branch (or the hotfix branch).
- **Never merge.** Merging the release PR is Amr's ship trigger (`/SHIP_RELEASE`). After a hotfix merges, merge `main` back into the active release branch and push.

## PR title and body

### Body

Use a HEREDOC to preserve formatting. When updating an existing PR, fetch the current body, **preserve any `- [x]` ticks** Amr has already applied, and refresh the commit list.

```
## Summary
<one bullet per feature commit, citing its issue: "#42: ...">

## Release checklist
- [ ] CI green on this PR (tests + PyInstaller build)
- [ ] `/PRE_RELEASE` complete (Test Plan current, language coverage, security, acknowledgements)
- [ ] Tester preview builds produced (`build-installer` / `build-portable` labels)
- [ ] Amr has run the in-app Test Plan on the preview build
- [ ] Code review findings addressed
- [ ] `VERSION.TXT` matches the release branch

## Testing performed
<!-- If --testing "..." was passed, paste that description here verbatim. Otherwise: "Per the in-app Test Plan." -->

---
🤖 PR description generated with [Claude Code](https://claude.com/claude-code) and reviewed by @<github_username>
```

Fetch `<github_username>` via `gh api user --jq '.login'`. If the call fails (no auth, no network), omit the attribution footer rather than blocking the PR.
