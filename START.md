# SOUL — Setup & Run

## One-time setup

**Step 1 — API key**
Open the `.env` file (in this folder). Replace `paste_your_key_here` with your key from https://console.groq.com

**Step 2 — Python deps** (run once, in this folder)
```
pip install -r requirements.txt
```

**Step 3 — Electron deps** (run once, in the frontend folder)
```
cd frontend
npm install
cd ..
```

---

## Every time you want to run SOUL
```
cd frontend
npm start
```
One command. Backend starts automatically.

---

## Keyboard shortcuts (work from any app)
| Key   | Action                        |
|-------|-------------------------------|
| Alt+S | Summon / hide SOUL            |
| Alt+Z | Ambient mode (tiny orb)       |
| Alt+E | Toggle screen awareness on/off|
| Alt+X | Clear conversation            |
| Alt+T | Focus input, start talking    |

---

## Testing checklist (do in order)
1. Type anything → she responds within 2s ✓
2. Ask "what am I working on?" → she describes your screen ✓
3. Ask "open notepad" → yellow card appears → click Accept → Notepad opens ✓
4. Click the teal dot (top-left titlebar) → shrinks to ambient orb ✓
5. Press Alt+S from a different window → SOUL reappears ✓

## Troubleshooting
**No response / backend crash:**
```
taskkill /F /IM python.exe
```
Then run `npm start` again.

**Config issues (wrong name, old settings):**
```
del "%APPDATA%\soul\config.json"
```
