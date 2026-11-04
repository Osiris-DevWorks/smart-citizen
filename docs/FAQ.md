# Frequently Asked Questions

Quick answers to the things people ask most. If your question isn't here, hit the **Feedback** link in the footer and ask us on Discord.

## How do I undo the changes Smart Citizen makes?

Easily, and at any time. Smart Citizen never edits the game's original files in place, so going back to vanilla is one click:

- **Toolbar → More → Clear Localization** deletes the custom `global.ini` Smart Citizen wrote. The game falls back to its built-in text immediately. Your edits aren't lost, they stay saved in the app and you can re-apply them whenever you like.
- Prefer to step back one version instead of all the way? **Toolbar → More → Restore Backup** rolls the game file back to a timestamped backup (Smart Citizen keeps the last 5, and makes a fresh one every time you Apply).

Your personal edits live in `user.ini` in your Smart Citizen data folder, separate from the game, so clearing the game file never touches them.

## Will I get banned for using Smart Citizen?

Smart Citizen only edits localization text (the words the game shows you), it doesn't touch game logic, give you any advantage, or talk to CIG's servers. Our modifications **should** be fine.

The optional **Smart Citizen Overlay** (Overlay tab) works the same hands-off way. It draws ordinary windows on top of the game, reads pixels from your screen like a screenshot tool does, and reads the game's `Game.log` file. It never injects into or hooks the game, never opens the game's process or reads its memory, and never sends keyboard or mouse input. If you set a drawer hotkey, it registers that one key combination with Windows, the standard way a program asks for a hotkey. Star Citizen keeps registered hotkeys from other programs while it has focus, so while a hotkey is set the overlay also takes the keyboard's raw input, the read-only way Windows tells a background program about key presses. That is not a keyboard hook: it holds up, changes and sends no key, keeps no record, and acts only on your combination. CIG has not said anything about overlays like this, so the same at-your-own-risk note below applies.

CIG has publicly backed community localization. Their [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) post lays out official support for player-made translations, which we understand to explicitly allow the kind of localization editing Smart Citizen does.

High-visibility streamers run similar localization projects out in the open, and none of them have been told to stop.

That said: the way you use Smart Citizen is at your own risk. Our changes should be okay, but anything you do yourself, you and your associates are liable for the damages that may occur. If you're ever unsure whether a change is appropriate, keep it cosmetic and keep a backup.

## What files does Smart Citizen modify?

Just one, and only when you click **Apply Enhancements**:

- `StarCitizen\<channel>\data\Localization\<language>\global.ini` — the game's localization file for the channel (LIVE, PTU, etc.) and language you've selected. Smart Citizen backs up the existing file first, then writes the merged result.
- It also makes sure `g_language` is set in your `user.cfg` so the game loads the right localization. Nothing else in your game install is touched.

Everything Smart Citizen generates for its own use (the source cache, enhancement files, backups, your `user.ini`) lives in your Smart Citizen data folder, not in the game.

## Why does Windows say this app is unrecognized?

Because Smart Citizen isn't code-signed yet. Windows SmartScreen and Smart App Control flag any new app from a publisher they don't have a signing certificate on file for, even a completely safe one. It's a "we haven't seen this before" warning, not a "this is dangerous" one.

To run it: on the SmartScreen prompt click **More info → Run anyway**. If Smart App Control is blocking it outright, you can allow the app from its prompt, or temporarily turn Smart App Control off, install, and turn it back on.

Code signing is on our roadmap, which will make this warning go away. Until then, only download Smart Citizen from our official GitHub releases so you know you've got the genuine build.
