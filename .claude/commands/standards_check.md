---
description: Lint the current diff against Smart Citizen's documented standards
---

# /standards_check

Audit the working-tree diff (staged + unstaged) against the project's documented standards. Report findings with file:line references and severity. **Do not auto-fix without confirmation.**

Each check carries a severity:

- **Critical** — breaks correctness, threading, or release-mode invariants. Must fix before merge.
- **Major** — wrong but won't immediately break. Should fix before merge.
- **Minor** — stylistic or "consider" notes. Optional.

## Checks

- **Portable mode** *(Critical)*: direct `QSettings(...)` constructor calls outside `src/utils/settings.py` and `src/utils/json_settings.py` break portable mode silently. Must use `AppSettings` helpers.
- **Worker progress** *(Critical)*: `QProgressBar.setValue(...)` invoked from inside a `QThread` worker — must route through `ProgressSink` (`src/utils/progress_sink.py`).
- **Worker settings access** *(Critical)*: workers in `src/gui/workers.py` that read `QSettings`/`JsonSettings` directly. Settings must be pre-fetched on the main thread and handed to the worker via `__init__`.
- **DataForge coverage** *(Critical)*: new read paths in `scripts/generate_enhancements_ini.py` without a matching entry in `DATAFORGE_KEEP_SUBPATHS` (`src/utils/pak_extractor.py`).
- **Row→entry lookup** *(Critical)*: any `self.entries[row]` indexing or equivalent in `src/gui/` — row index ≠ entry index when filtered/sorted. Must use `_entry_index_for_row(row)`.
- **Frontend stamp** *(Major)*: any code that writes to the `Frontend_PU_Version` loc-key without going through `_stamp_frontend_version` in `src/gui/main_window.py` — bypasses the no-double-stamp guard.
- **Table column indices** *(Major)*: hard-coded literal column numbers in `src/gui/` instead of the `COL_*` constants exported from `src/gui/string_table_model.py`.
- **base.ini vs global.ini** *(Major)*: cached source must be `base.ini`. New code calling the cached source `global.ini` is wrong — that name is reserved for the game's file.

## Code duplication / DRY

See root `CLAUDE.md` → *Code deduplication (DRY)* for calibration. Surface candidates:

- **Copy-paste blocks** *(Major)*: 5+ line blocks in the diff that appear verbatim (or near-verbatim) elsewhere in the codebase. Report both locations.
- **Magic literals** *(Minor)*: string or integer literals used in 2+ places without a named constant. Common offenders to grep for: settings keys, source names (`"global"`, `"user"`, `"enhancements"`), channel names (`"LIVE"`, `"PTU"`, `"EPTU"`, `"HOTFIX"`, `"TECH-PREVIEW"`), column indices, file extensions, path segments.
- **Near-duplicate functions** *(Minor)*: a new function whose body is structurally similar to an existing one, differing only in a literal or a single call target — flag as a parameterization candidate.

Calibration:
- 3+ occurrences → recommend extraction.
- 2 occurrences → note as "consider," not a hard finding.
- Single-use helper proposals → do not recommend; premature abstraction is worse than inline duplication.

## Output

Group findings by severity. Within each group, one finding per line: `file:line — short description — fix hint`.

```
**Critical** (blocking):
  src/foo.py:42 — direct QSettings(...) call — use AppSettings.get_user_data_dir()
  src/bar.py:13 — QProgressBar.setValue() from worker — route through ProgressSink

**Major** (should fix):
  src/baz.py:99 — hard-coded column index 4 — use COL_STATUS

**Minor** (consider):
  src/qux.py:7 — "LIVE" string literal repeated 3x — extract a constant
```

End with a one-line **verdict**:

- **Clean** — no findings.
- **Minor issues** — only Minor findings.
- **Needs attention** — any Critical or Major findings.

After the verdict, **CHECKPOINT — pause and ask the user whether to draft fixes for the Critical/Major findings, or move on.** Wait for the answer before doing anything else.
