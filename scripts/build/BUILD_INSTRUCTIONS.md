# Build Instructions for Smart Citizen

## Quick Start

**Build executable (recommended):**
```bash
cd scripts/build
.venv\Scripts\python.exe build_exe.py
```

**Build everything (executable + installer):**
```bash
cd scripts/build
build_all.bat
```

---

## Prerequisites

### Required Software

1. **Python 3.9+** - Already installed in your `.venv`
2. **PyInstaller** - Auto-installed by build scripts

### Download Inno Setup (Optional)

For creating the installer, download Inno Setup 6.6.0 or newer from: https://jrsoftware.org/isdl.php (`installer.iss` stops with an error on older versions)
- Install the Unicode version
- Default installation is fine

---

## Step 0 (Optional): Clean Cache for Distribution

If distributing to users, optionally clean the DataForge cache to reduce user data size:

```bash
cd scripts/build
.venv\Scripts\python.exe clean_cache_for_distribution.py
```

This removes the `raw/` DataForge extraction (keeping the filtered `libs/` which has all necessary stats data). 
Users can regenerate raw/ if needed by re-extracting their P4K.

**Note:** The executable doesn't bundle user cache data - it's created at runtime. This script is only 
useful if you've manually included cache in any distribution package.

---

## Step 1: Build the Executable

Run the build script from the project root:

```bash
cd scripts/build
.venv\Scripts\python.exe build_exe.py
```

This will:
- Clean previous builds
- Package the application into a single `.exe` file
- Include all necessary data files (global.ini)
- Create the onedir build at `dist/SmartCitizen/` with a stable `SmartCitizen.exe` (the name no longer carries the version, so installed shortcuts survive updates)

**Testing the EXE:**
```bash
dist\SmartCitizen\SmartCitizen.exe
```

---

## Step 2: Create the Installer (Recommended)

### Option A: Using build_all.bat (Automated)

```bash
cd scripts/build
build_all.bat
```

This runs both build_exe.py and Inno Setup automatically.

### Option B: Using Inno Setup GUI

1. Open Inno Setup Compiler
2. File → Open → Select `installer.iss` (in project root)
3. Build → Compile
4. The installer will be created in project root

### Option C: Using Command Line

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

The installer will be created in the project root as:
```
SmartCitizen-v0.1.0-Setup.exe
```

---

## Step 3: Test the Installer

1. Run the installer: `SmartCitizen-v0.1.0-Setup.exe`
2. Follow the installation wizard
3. Test the installed application:
   - Launch the app
   - Load global.ini file
   - Edit some strings
   - Apply to game
   - Check that files are in the right location

---

## Distribution Package Contents

The installer includes:
- ✅ Main executable (`SmartCitizen.exe`)
- ✅ Data files (default global.ini)
- ✅ Start menu shortcuts
- ✅ User config setup

---

## File Sizes (Approximate)

- **Executable**: ~60-100 MB (includes Python runtime, PyQt6, and all dependencies)
- **Installer**: ~30-50 MB (compressed)

---

## Version Update Checklist

For future versions:

1. Update version in:
   - `VERSION.TXT` (e.g., `0.2.0`)
   - `installer.iss` (line ~5)

2. Rebuild:
   ```bash
   cd scripts/build
   build_all.bat
   ```

3. Test installer and executable

4. Create release notes

5. Tag in git:
   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```

6. Create GitHub release with:
   - Release notes
   - Installer executable
   - Standalone executable

---

## Troubleshooting

### "PyInstaller not found"
```bash
.venv\Scripts\pip install pyinstaller
```

### "Module not found" errors
Make sure all dependencies are installed:
```bash
.venv\Scripts\pip install -r requirements.txt
```

### Executable is too large
This is normal for PyQt6 applications. PyInstaller bundles the entire Python runtime and all libraries (60-100MB is standard).

### Inno Setup not found
Install Inno Setup 6.6.0 or newer from: https://jrsoftware.org/isdl.php

Or compile the installer manually by:
1. Opening `installer.iss` in Inno Setup Compiler
2. Clicking Build → Compile

---

**Ready to build!** Run `build_all.bat` or follow the steps above.
