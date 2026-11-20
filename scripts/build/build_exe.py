"""
Build script for creating Smart Citizen executable

Usage:
    python build_exe.py                    # Build without incrementing version
    python build_exe.py --increment patch  # Increment patch version (0.1.0 -> 0.1.1)
    python build_exe.py --increment minor  # Increment minor version (0.1.0 -> 0.2.0)
    python build_exe.py --increment major  # Increment major version (0.1.0 -> 1.0.0)
    python build_exe.py --portable         # Build standalone portable variant
                                           # (writes to <exe-dir>/data/, no registry)
    python build_exe.py --portable --zip-only
                                           # Zip the existing dist/ portable folder
                                           # again without rebuilding (release.yml
                                           # runs it after signing the .exe files)
    # Flags can combine, e.g. `--portable --increment patch`.
"""

import PyInstaller.__main__
import os
import sys
import shutil
import zipfile

# Get the project directory
project_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(project_dir))

# Add src to path for imports
sys.path.insert(0, os.path.join(root_dir, 'src'))

# Handle CLI flags. Position-independent parsing — a list of args we
# slowly drain, recognising known flags. Anything left over is unused
# but we don't error on it (forward-compat with future flags).
_args = sys.argv[1:]
increment_version = None
portable_mode = False
zip_only = False
i = 0
while i < len(_args):
    arg = _args[i]
    if arg == '--increment' and i + 1 < len(_args):
        increment_type = _args[i + 1].lower()
        if increment_type in ['major', 'minor', 'patch']:
            increment_version = increment_type
        else:
            print(f"Error: Invalid increment type '{increment_type}'. Use 'major', 'minor', or 'patch'")
            sys.exit(1)
        i += 2
        continue
    if arg == '--portable':
        portable_mode = True
        i += 1
        continue
    if arg == '--zip-only':
        zip_only = True
        i += 1
        continue
    i += 1

# Get version from VERSION.TXT
version_file = os.path.join(root_dir, 'VERSION.TXT')
with open(version_file, 'r') as f:
    current_version = f.read().strip()

print(f"\n{'='*60}")
print(f"Building version: {current_version}{' (PORTABLE)' if portable_mode else ''}")
print(f"{'='*60}\n")

# ── Portable-build flag plumbing ────────────────────────────────────────
# When --portable is set, write src/utils/_build_info.py with
# IS_PORTABLE = True before PyInstaller runs. build_mode.py imports
# IS_PORTABLE from _build_info if present; otherwise it defaults to
# False. After the PyInstaller run we delete _build_info.py so the
# repo stays in its default (registry-mode) state — protects against
# a developer running `python src/main.py` immediately after a
# portable build and getting silently switched to portable mode.
build_info_path = os.path.join(root_dir, 'src', 'utils', '_build_info.py')

def _write_build_info(is_portable: bool) -> None:
    """Generate src/utils/_build_info.py with the build-time flags.

    Module is git-ignored — never commit. Read by build_mode.py via
    a try/except ImportError fallback.
    """
    content = (
        '"""Build-time flags written by scripts/build/build_exe.py.\n'
        '\n'
        'DO NOT COMMIT. DO NOT EDIT BY HAND. Git-ignored — regenerated on every build.\n'
        '"""\n'
        f'IS_PORTABLE: bool = {is_portable!r}\n'
    )
    with open(build_info_path, 'w', encoding='utf-8') as f:
        f.write(content)

def _cleanup_build_info() -> None:
    """Remove the generated _build_info.py post-build.

    Idempotent — safe to call even if the file isn't there. We do this
    in a finally block so a PyInstaller failure mid-run doesn't leave
    the source tree in portable-mode state.
    """
    try:
        if os.path.exists(build_info_path):
            os.remove(build_info_path)
            print(f"  - Cleaned up {os.path.relpath(build_info_path, root_dir)}")
    except OSError as e:
        print(f"  WARNING: could not delete {build_info_path}: {e}")

# Build executable with PyInstaller.
# The registry / installer build uses a STABLE exe name (SmartCitizen.exe) so
# the installed path and the desktop / Start Menu shortcuts survive version
# updates (#104): a copied or pinned shortcut keeps working because the target
# no longer changes every release. The portable build keeps the versioned name
# so the downloadable zip and its folder identify the version at a glance.
exe_name = (
    f"SmartCitizen-Portable-v{current_version}" if portable_mode else "SmartCitizen"
)


def _write_portable_zip() -> None:
    """Zip dist/<exe_name>/ into dist/<exe_name>.zip, files at the top level."""
    zip_name = f"{exe_name}.zip"
    zip_path = os.path.join(root_dir, 'dist', zip_name)
    onedir_path = os.path.join(root_dir, 'dist', exe_name)
    print(f"Packaging portable zip: dist/{zip_name}")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _dirs, files in os.walk(onedir_path):
            for fname in files:
                full = os.path.join(root, fname)
                # Inside the zip: files sit at the top level (no extra
                # SmartCitizen-Portable-vX.Y.Z/ wrapper). Explorer's
                # "Extract All" already creates an enclosing folder
                # named after the zip, so wrapping here too used to
                # double that prefix on the common extraction path —
                # exactly the kind of redundant length that tips deep
                # _internal/ paths over MAX_PATH. Recipients who
                # manually unzip into an already-open folder instead
                # of using Extract All will get the files loose there.
                arcname = os.path.relpath(full, onedir_path)
                zf.write(full, arcname=arcname)
    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  Portable zip ready: dist/{zip_name} ({zip_size_mb:.1f} MB)")
    print()


if zip_only:
    # Re-package an existing portable build, e.g. after its .exe files
    # were signed. No clean, no PyInstaller run.
    if not portable_mode:
        print("Error: --zip-only needs --portable")
        sys.exit(1)
    if not os.path.isdir(os.path.join(root_dir, 'dist', exe_name)):
        print(f"Error: dist/{exe_name}/ not found; build it first")
        sys.exit(1)
    _write_portable_zip()
    sys.exit(0)

# Clean previous builds
print("Cleaning old builds...")
for folder in ['build', 'dist']:
    path = os.path.join(root_dir, folder)
    if os.path.exists(path):
        shutil.rmtree(path)
        print(f"  - Removed {folder}/")
# Also clean any stale _build_info.py from an interrupted prior build.
_cleanup_build_info()

print()

# Write PyInstaller's generated .spec into build/ (ephemeral, wiped each run)
# instead of the repo root, so the stable --name never clobbers the
# hand-maintained root SmartCitizen.spec or litters the root with per-version
# spec files.
spec_path = os.path.join(root_dir, 'build')
os.makedirs(spec_path, exist_ok=True)

assets_dir   = os.path.join(root_dir, 'assets')
icon_path    = os.path.join(assets_dir, 'logo.ico')
about_file   = os.path.join(root_dir, 'docs', 'ABOUT.md')
help_file    = os.path.join(root_dir, 'docs', 'HELP.md')
legal_file   = os.path.join(root_dir, 'docs', 'LEGAL.md')
faq_file     = os.path.join(root_dir, 'docs', 'FAQ.md')
patches_dir  = os.path.join(root_dir, 'patches')
languages_dir = os.path.join(root_dir, 'languages')
enhancements_script = os.path.join(root_dir, 'scripts', 'generate_enhancements_ini.py')

common_args = [
    os.path.join(root_dir, 'src', 'main.py'),
    '--name', exe_name,
    '--windowed',
    '--icon', icon_path,
    '--add-data', f'{version_file}{os.pathsep}.',
    '--add-data', f'{about_file}{os.pathsep}docs',
    '--add-data', f'{help_file}{os.pathsep}docs',
    '--add-data', f'{legal_file}{os.pathsep}docs',
    '--add-data', f'{faq_file}{os.pathsep}docs',
    '--add-data', f'{assets_dir}{os.pathsep}assets',
    '--add-data', f'{patches_dir}{os.pathsep}patches',
    # UI translation files. Without this the frozen app can't resolve any
    # tr() key (get_resource_path misses languages/<lang>/ui.json), so the
    # whole UI renders raw keys like 'branding.title'. Mirrors the
    # ('languages', 'languages') entry in SmartCitizen.spec.
    '--add-data', f'{languages_dir}{os.pathsep}languages',
    '--add-data', f'{enhancements_script}{os.pathsep}scripts',
    '--workpath', os.path.join(root_dir, 'build'),
    '--specpath', spec_path,
    '--hidden-import=PyQt6',
    '--hidden-import=src.gui',
    '--hidden-import=src.parser',
    '--hidden-import=src.merger',
    '--hidden-import=src.models',
    '--hidden-import=src.utils',
    # Modules that are only referenced from files PyInstaller loads as *data*
    # (not as code) need to be listed explicitly, or they silently miss the
    # bundle. scripts/generate_enhancements_ini.py is added via --add-data
    # and therefore never parsed for imports — its
    # `from src.utils.progress_sink import ProgressSink` then hits the
    # `except ImportError: _sink = None` branch in the frozen build, and
    # Generate Enhancements runs with an indeterminate progress bar the
    # whole time even though the determinate plumbing works in dev. We
    # pre-empted `--collect-submodules=src.utils` as a broader fix but it
    # didn't pick up progress_sink (pyinstaller's module-graph walk still
    # needs some in-graph reference to the package to expand it on our
    # src/ layout). Explicit hidden-import for the two script-only helpers
    # is the robust fix.
    '--hidden-import=src.utils.progress_sink',
    '--hidden-import=src.utils.dataforge_patcher',
    '--collect-all=lxml',
    # scripts/generate_enhancements_ini.py is loaded dynamically via
    # importlib at runtime (see EnhancementsGeneratorWorker), so
    # PyInstaller's static import graph can't see its dependencies.
    # --collect-all is stronger than --hidden-import: it forces every
    # submodule + data file into the bundle regardless of whether the
    # module graph finds a reference. Earlier hidden-import flags alone
    # silently no-op'd for concurrent.futures on PyInstaller 6 / Py 3.12.
    '--collect-all=concurrent',
]

# Build --onedir version only — feeds the Inno Setup installer. The portable
# --onefile build was retired because we release the installer as the sole
# distribution artifact.
print("Building --onedir version (for installer)...")
print(f"  Output: dist/{exe_name}/")
print()

onedir_args = common_args + [
    '--onedir',
    '--distpath', os.path.join(root_dir, 'dist'),
]

try:
    # Write the build-time flag module BEFORE PyInstaller scans imports
    # (PyInstaller bundles whatever's on disk at run-time, so the file
    # must exist before its module-graph walk starts).
    if portable_mode:
        _write_build_info(is_portable=True)
        print(f"  Wrote {os.path.relpath(build_info_path, root_dir)} with IS_PORTABLE = True")
        print()

    PyInstaller.__main__.run(onedir_args)
    print(f"\n{'='*60}")
    print("Build successful!")
    print(f"{'='*60}")
    print(f"Installer dir: dist/{exe_name}/")
    print()

    # --collect-all=lxml (needed so dynamically-imported lxml submodules
    # aren't missed) also drags in isoschematron's bundled reference-XSLT
    # resources — used only if code calls lxml.isoschematron.Schematron(),
    # which nothing here does. Those files add ~100+ chars of nested path
    # depth (_internal/lxml/isoschematron/resources/xsl/iso-schematron-xslt1/...)
    # for zero functional benefit, and combined with the patches/ tree's own
    # depth that's enough to push some paths past Windows' 260-char MAX_PATH
    # once extracted — which is what makes Explorer refuse to Recycle-Bin
    # them on delete. Safe to strip post-build: doesn't touch lxml's actual
    # etree/XPath parsing (compiled extension code, unaffected).
    isoschematron_resources = os.path.join(
        root_dir, 'dist', exe_name, '_internal', 'lxml', 'isoschematron', 'resources'
    )
    if os.path.exists(isoschematron_resources):
        shutil.rmtree(isoschematron_resources)
        print("  - Removed unused lxml isoschematron resources (dead weight, deep paths)")
        print()

    # Portable distribution: zip up the onedir output for a no-install
    # USB-stick-friendly download. Recipients extract anywhere, run the
    # .exe inside; portable mode writes its data/ folder right there.
    # The standard build doesn't get a zip — Inno Setup is its
    # distribution artifact, attached separately by release.yml.
    if portable_mode:
        _write_portable_zip()
except Exception as e:
    print(f"\nError building --onedir executable: {e}")
    sys.exit(1)
finally:
    # Always remove the generated _build_info.py — keeps the source
    # tree in default (registry) mode for any subsequent dev runs.
    if portable_mode:
        _cleanup_build_info()
