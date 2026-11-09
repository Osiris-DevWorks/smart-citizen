# Running Smart Citizen on Linux

This guide explains how to run Smart Citizen on Linux through the same Wine prefix used by Star Citizen.

> Originally contributed by [@PinkFloyd1213](https://github.com/PinkFloyd1213) in [issue #33](https://github.com/Osiris-DevWorks/smart-citizen/issues/33#issuecomment-4460305053).

> [!IMPORTANT]
> **The Smart Citizen Overlay needs an X11 session, not Wayland.** It does not work on Wayland. If you want the overlay to work:
>
> 1. Log out of your desktop.
> 2. On the login screen, pick your user, then use the session menu (often a gear icon) to choose the **X11** or **Xorg** session (for example "Plasma (X11)" or "GNOME on Xorg").
> 3. Log in and run Star Citizen and Smart Citizen as usual.
>
> To check which one you're on, run `echo $XDG_SESSION_TYPE` in a terminal: it prints `x11` or `wayland`. The rest of Smart Citizen works on either.

## Prerequisites

You need a working Star Citizen installation on Linux before installing Smart Citizen. If you haven't set that up yet, we strongly recommend the **[Star Citizen LUG](https://wiki.starcitizen-lug.org/)** community — they maintain scripts (notably the LUG-Helper) and have an active community that makes running SC on Linux relatively painless.

The rest of this guide assumes Star Citizen is installed and running correctly through a Wine prefix.

## Step 1 — Download Smart Citizen

Grab the latest release from the [releases page](https://github.com/Osiris-DevWorks/smart-citizen/releases). **Make sure you download the portable version** (the installer version won't work cleanly inside a Wine prefix).

## Step 2 — Extract Smart Citizen inside your Wine prefix

Extract the zip somewhere accessible inside the Wine prefix that runs Star Citizen. We recommend placing it at the root of your user profile inside the prefix, for example:

```
<WINE_PREFIX>/drive_c/users/<USER>/SmartCitizen/
```

Drop the full contents of the zip into that folder.

## Step 3 — Identify the Wine runner used by Star Citizen

Smart Citizen needs to run with the **same Wine runner** as the game. To find which one you're using:

1. Open **LUG-Helper**
2. Go to **Manage Wine Runners**
3. Look for the runner marked as **"in-use"** — that's the one you need

Note the full path to the runner's `wine` binary, you'll need it in the next step. It usually looks something like:
```
<WINE_PREFIX>/runners/<RUNNER_NAME>/bin/wine
```

## Step 4 — Create the launch script

We recommend creating the launch script inside your LUG-Helper folder so everything stays in one place. Create a file named `launch_smartcitizen.sh` with the following content:

```bash
#!/bin/bash
# Path configuration
export WINEPREFIX="/home/USER/Games/star-citizen"
WINE_RUNNER="/home/USER/Games/star-citizen/runners/<RUNNER_NAME>/bin/wine"
APP_DIR="/home/USER/Games/star-citizen/drive_c/users/USER/SmartCitizen-Portable-vX.Y.Z"
EXE_NAME="SmartCitizen-Portable-vX.Y.Z.exe"

# Move into the app directory
cd "$APP_DIR" || exit 1

# Launch
echo "Starting SmartCitizen with the LUG runner..."
"$WINE_RUNNER" start /unix "$EXE_NAME"
```

### How to fill in each variable

- **`WINEPREFIX`** — the absolute path to your Star Citizen Wine prefix. If you installed SC through LUG-Helper with default settings, it's typically `/home/USER/Games/star-citizen`.
- **`WINE_RUNNER`** — the full path to the `wine` binary of the runner you identified in Step 3. Replace `<RUNNER_NAME>` with the folder name of your in-use runner (e.g. `lug-wine-tkg-staging-experimental-git-11.8-2`). Make sure the path ends with `/bin/wine`.
- **`APP_DIR`** — the folder where you extracted Smart Citizen in Step 2. Replace `vX.Y.Z` with the version you downloaded (e.g. `v1.3.1`).
- **`EXE_NAME`** — the name of the Smart Citizen executable inside `APP_DIR`. It matches the version you downloaded.

> **Tip:** replace every `USER` placeholder with your own Linux username.

## Step 5 — Make the script executable and run it

From a terminal, in the folder where you saved the script:

```bash
chmod +x launch_smartcitizen.sh
./launch_smartcitizen.sh
```

Smart Citizen should now launch. From there, usage is identical to the Windows version. Once you've applied your changes through Smart Citizen, you can close it and launch Star Citizen normally.

## Troubleshooting

**Don't run Star Citizen and Smart Citizen at the same time:**
Smart Citizen modifies the game's files (translations, etc.) and is not meant to run alongside the game — once your changes are applied, you can close it before launching Star Citizen. On top of that, running two applications concurrently inside the same Wine prefix tends to cause conflicts. Always run one *or* the other, never both at once.

**Smart Citizen doesn't detect the Star Citizen installation:**
This should be auto-detected since both apps share the same Wine prefix. If it isn't, point Smart Citizen manually to the Star Citizen install folder inside the prefix (typically `<WINE_PREFIX>/drive_c/Program Files/Roberts Space Industries/StarCitizen/`).

**Keep your launch script in sync with your setup:**
The script hardcodes paths and version-specific folder names, so it will break if anything changes. Remember to update it whenever:
- You change your Wine prefix location or switch to a different Wine runner → update `WINEPREFIX` and `WINE_RUNNER`.
- You update Smart Citizen to a new version → update `APP_DIR` and `EXE_NAME` to match the new folder and executable name (the version number is part of both).
