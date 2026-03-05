# In This Version — v9.8

*SOUL · Build date: 2026-03-05*

---

## What's new

### Core fixes

**type_text now targets the right window**
The poem typed itself into SOUL's own input bar instead of Notepad. Fixed: `type_text` now accepts a `window_title` parameter. When provided, it calls `SetForegroundWindow` on the target process and waits 600ms before firing `SendKeys` — all in a single PowerShell invocation so there's no race between focus and typing.

**create_file no longer crashes with Access Denied**
The LLM was generating paths like `C:\Users\username\...` with the literal string "username". A new `_resolve_path()` helper intercepts any `C:\Users\<anything>\` pattern and remaps it to the real `Path.home()` — silently, before the file operation runs.

**Actions stopped timing out silently**
`open_app`, `play_media`, `create_file`, `take_screenshot`, `copy_to_clipboard`, `open_folder`, `open_url`, and `web_search` were missing from `AUTO_CONFIRM`. They required the user to manually click a confirm button that nobody saw. Everything user-initiated is now auto-confirmed. Only `delete_file`, `kill_process`, and `run_command` still require confirmation.

**Conversational messages no longer type into open windows**
If the active window was PowerShell and you said "Hi", SOUL was generating a `type_text` action and typing "Hi" into your terminal. System prompt now has an explicit hard rule: `type_text` is only for explicit write/type requests. Conversational messages never trigger actions.

**Empty responses fixed**
When the LLM returned an empty string, SOUL showed a blank message bubble and saved `""` to history — which taught it that empty was acceptable. Now: empty responses trigger a single retry with a nudge. If still empty, fallback to `"..."` and don't save the blank to history.

**Fake `<angle bracket>` narration stripped**
`_parse` now strips any `<Checking logs...>` or `<Opening window>` roleplay markup from LLM output before it reaches the UI.

**Auto action results no longer spam the chat**
Every completed action was printing "Typed 335 chars into Notepad" or "Opening app..." as SOUL messages in chat. These are now silent — the Workspace panel already shows every step with its result. Chat only surfaces errors.

**Spotify liked songs now actually plays**
Opening `spotify://collection/tracks` launched the liked songs view but didn't start playback. Fixed: after navigating to liked songs, SOUL now focuses the Spotify window and sends `Space` (the Spotify play key) within the same PowerShell invocation.

---

### Memory & identity

**"Aryan" permanently purged**
On every startup, SOUL now runs `scrub_stale_names()` against `soul_memory.db` — deleting any `session_history` rows containing previous user names before loading memory. The memory formatter also filters out raw context packets that were accidentally saved as SOUL messages.

**Context packets no longer echo as responses**
The `[HH:MM] Active: ...\nCPU:...` context block was injected as a plain system message. When the LLM was confused, it echoed this verbatim as its reply. Now wrapped as `<context>...</context>` XML — the model treats it as metadata, not dialogue.

**SOUL no longer describes her own windows**
Screen vision was picking up SOUL's own interface ("I can see the SOUL workspace panel..."). SOUL's own windows (`thinkiee`, `soul`, `workspace`) are now filtered from active window detection.

**Wake messages stopped reporting stats and screen content**
Wake prompt now explicitly forbids: stat mentions, `"I see that..."`, `"The screen shows..."`, `"I notice..."`. Greets naturally or references recent memory.

---

### Model / API

**Deprecated model removed**
`llama-3.1-70b-versatile` was removed from Groq in early 2025 but was still first in the fallback chain, causing silent 400 errors on every session start. Removed. Chain is now: `llama-3.3-70b-versatile → llama-3.1-8b-instant → gemma2-9b-it`.

**Model preference persists across restarts**
When the LLM falls back to a lower model, it now saves the working model to config. Next restart uses that model first instead of always trying the primary.

**Vision model updated**
`meta-llama/llama-4-scout` (doesn't exist on Groq) and the deprecated `llama-3.2-11b-vision-preview` removed. Vision chain is now `llama-3.2-90b-vision-preview → llama-3.2-11b-vision-preview`.

---

### Frontend

**Rounded corners actually round**
`html, body` had `background: var(--bg)` — the dark background was showing behind the shell's `border-radius: 22px`, rendering square corners regardless. Fixed to `background: transparent` with matching `border-radius: 22px` on body.

**Input placeholder matches entity pronouns**
Placeholder was hardcoded as `"Talk to her…"`. Backend now sends `pronoun_object` in the `init` message. Frontend sets `Talk to her/him/them/it…` dynamically based on configured pronouns.

**Duplicate IPC handler removed**
`ipcMain.on('workspace-to-main', ...)` was registered twice in `main.js`. Every workspace confirm/reject was firing both handlers — actions executed twice. Merged into one.

**Multi-step action gap timing improved**
- Before any `type_text`: 1.2s settle
- After `focus_window`: 1.0s
- After `open_app`: 2.8s
- Everything else: 0.6s

---

## Known limitations

- Spotify "play liked songs" uses `Space` to start playback — works when Spotify opens to liked songs, but depends on Spotify's window state
- Screen vision requires the Groq vision endpoint to be available — falls back gracefully to no-vision mode
- `run_command` requires Full permission tier — not exposed in Standard tier by design
- Voice input (`Alt+T`) is wired but voice-to-text backend is not bundled in this build

---

## Upgrade notes

If upgrading from v9.x: apply the patch script, then restart. `soul_memory.db` is preserved — stale name entries will be automatically scrubbed on first boot.

```powershell
powershell -ExecutionPolicy Bypass -File .\SOUL_patch.ps1
cd frontend && npm start
```
