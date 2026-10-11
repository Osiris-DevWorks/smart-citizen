# src/parser/CLAUDE.md

INI parsing and status classification. See the root `CLAUDE.md` for project context.

## Files

- `ini_parser.py` — line-by-line INI parsing (splits on first `=`), source loading via `load_sources_from_settings()`, and `load_overrides(target_path)` to read `user.ini` back as `dict[str, str]`. `_determine_status_from_source(...)` labels each entry: `Modified` (user set `custom_value`), `Enhanced` (value came from the enhancements pipeline), `Unmodified` (stock `base.ini` text), `New` (key only in user/enhancements, not base). Pre-1.3.0 had no "Enhanced" bucket — those entries showed as "Modified" and could not be told apart from real user edits. `count_enhancement_categories(sources_dict, enhancements_key_categories)` counts the enhancements source by the generator's category map (key-prefix fallback). The Apply success dialog and the Config tab's Apply Preview both use it, over the source with the discovered "New" keys dropped when Include discovered items is off, so their totals agree (#443).
