# JARVIS Cloud — Customer Onboarding Guide

Step-by-step for a paid install session. Work through this top to bottom.
Typical session time: 30–45 minutes.

---

## Pre-Call Checklist (Send to Customer 24h Before)

Ask the customer to complete these before the call:

- [ ] **Railway account created** at https://railway.app (free to sign up)
- [ ] **Credit card added** to Railway (required even for free tier — Railway needs it for billing trust)
- [ ] **Anthropic API key ready** — get at https://console.anthropic.com. Must start with `sk-ant-`
- [ ] **Google account** they want JARVIS to access (Calendar, Tasks, Gmail)
- [ ] **OpenWeatherMap API key** (optional, free) — https://openweathermap.org/api
- [ ] **jarvis-cloud repo cloned** locally:
  ```
  git clone https://github.com/YOUR_REPO/jarvis-cloud.git
  cd jarvis-cloud
  ```
- [ ] **Python 3.11+** installed — check with `python3 --version`

---

## The Install Session

### 1. Verify Prerequisites

Run on the customer's machine:

```bash
python3 --version          # must be 3.11+
git --version              # any version
railway --version          # if not installed, script will install it
```

If Railway CLI is missing:
```bash
npm install -g @railway/cli    # if they have npm
# OR
brew install railway           # if they're on Mac with Homebrew
```

**If step fails:** Python below 3.11 — send them to https://www.python.org/downloads/ and reschedule.

---

### 2. Run the Setup Script

```bash
cd ~/jarvis-cloud
bash scripts/setup.sh
```

The script walks through each step interactively. You guide the customer through each prompt.

---

### 3. Script Step-by-Step (What to Expect)

#### Step 1: Prerequisites Check
Automatic — script checks Python, git, Railway CLI. Fix any errors before continuing.

#### Step 2: Customer Info

| Prompt | What to enter | Notes |
|--------|--------------|-------|
| First name | Their preferred name | Used in every briefing |
| Title | `Boss`, `Sir`, `Ma'am`, or their name | JARVIS uses this |
| Timezone | IANA format | e.g. `America/New_York`, `Europe/London` |
| City | Their city name | Optional — used in briefings |
| Lat/Lon | GPS coordinates | Optional — needed only for weather |

Find timezone strings at: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

#### Step 3: Anthropic API Key

- Customer pastes their key (starts with `sk-ant-`)
- Script validates it live against the Anthropic API
- **If invalid:** Check they copied the full key — these are very long strings
- **If network error:** Check their internet connection; the script will ask to retry

#### Step 4: OpenWeatherMap Key (optional)

- If the customer wants weather in briefings, they paste their OWM key here
- Script validates against OWM API
- **If skipped:** Weather features simply won't appear — everything else works

#### Step 5: Google OAuth

This is the most interactive step.

**Sub-step A: Google Cloud Console setup** (customer may have done this ahead of time)

1. Go to https://console.cloud.google.com/
2. Create project: **"JARVIS Cloud"**
3. Enable three APIs (search each in the library):
   - Google Calendar API
   - Tasks API
   - Gmail API
4. APIs & Services → Credentials → **Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop app** | Name: `JARVIS`
6. Click **Download JSON** → rename file to `credentials.json`
7. Move `credentials.json` into the `jarvis-cloud/` folder

**If they see "OAuth consent screen" warning:** They need to configure it first:
- Go to OAuth consent screen → Internal (if G Suite) or External
- Add their own email as a test user
- Save — then go back to Credentials

**Sub-step B: The OAuth browser flow**

The script opens a browser window automatically. Customer:
1. Signs in with the Google account JARVIS should access
2. Clicks through the permissions grant (Calendar + Tasks + Gmail read access)
3. Sees "Authentication successful" in the terminal

**If browser doesn't open:** The terminal prints a URL — they can copy/paste it into any browser.

**If they get "This app isn't verified":**
- Click **"Advanced"** → **"Go to JARVIS (unsafe)"**
- This warning is normal for personal OAuth apps — it's their own credentials

**Sub-step C: Token encoding**

Automatic — script base64-encodes the token and prepares it for Railway.

**What `GOOGLE_TOKEN_JSON` contains:** The OAuth token (refresh token + access token). It does NOT contain their Google password. It grants read-only access to Calendar, Tasks, and Gmail. It auto-refreshes using the embedded refresh token.

#### Step 6: Railway Login & Project

Browser opens for Railway OAuth login. Customer signs in to their Railway account.

Script creates a new project called `jarvis-cloud` (or whatever name they chose).

**If "project already exists" error:** The customer may have a previous attempt. Script will try to link to it instead — that's fine, it's idempotent.

#### Step 7: Environment Variables

Automatic — script pushes all settings to Railway. Watch for any `FAILED` lines.

**If a variable fails to set:** Run manually:
```bash
railway variables set KEY="VALUE"
```

#### Step 8: Deploy

```bash
railway up
```

This uploads the code and triggers a build. Takes 2–4 minutes. The customer can watch the Railway dashboard at https://railway.app/dashboard.

**If build fails:** Check `railway logs`. Common issues:
- Missing `requirements.txt` entry — check the package is listed
- Build timeout — Railway's free tier has limited build minutes; try again

#### Step 9: Health Check

Script polls `https://your-project.up.railway.app/health` every 10 seconds.

**If it times out:** Deployment might still be running. Check the Railway dashboard deploy tab. When it shows "Active", run:
```bash
curl https://your-project.up.railway.app/health
```

---

### 4. Post-Deploy Verification

Once health check passes, verify each feature manually:

```bash
JARVIS_URL="https://your-project.up.railway.app"
API_KEY="their-jarvis-api-key-from-setup-output"

# Health (no auth)
curl $JARVIS_URL/health

# Status (needs API key)
curl -H "X-API-Key: $API_KEY" $JARVIS_URL/api/status

# Dashboard page (no auth)
open $JARVIS_URL/dashboard

# Calendar (needs API key)
curl -H "X-API-Key: $API_KEY" $JARVIS_URL/api/calendar/upcoming

# Gmail digest
curl -H "X-API-Key: $API_KEY" $JARVIS_URL/api/digest

# Morning brief page
open $JARVIS_URL/morning-brief.html
```

---

### 5. Hand Off to Customer

Give the customer these four things:

1. **Their Railway URL** — `https://their-project.up.railway.app`
2. **Dashboard link** — `https://their-project.up.railway.app/dashboard`
3. **Their JARVIS API Key** — from the setup script's final output
4. **PWA install instructions:**
   - On iPhone: open the dashboard URL in Safari → Share → Add to Home Screen
   - On Android: open in Chrome → three-dot menu → Add to Home Screen

---

## Updating a Customer Instance

When you push changes or they want an update:

```bash
cd ~/jarvis-cloud
git pull origin main
bash scripts/update.sh their-railway-project-name
```

The update script deploys and waits for the health check to pass before confirming.

---

## Troubleshooting Reference

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `/health` returns 500 | Missing env var | Check `railway variables` — look for empty required vars |
| Dashboard shows "API OFFLINE" | Wrong API key | Customer must enter the key from setup output |
| Google features not working | Expired/invalid token | Re-run `bash scripts/setup.sh` — it will skip completed steps and re-encode the token |
| `GOOGLE_TOKEN_JSON` decode error | Token was corrupted | Delete `google_token.json`, re-run `bash scripts/setup.sh` |
| Morning brief returns error | Anthropic key issue or quota | Check `railway logs` for the full error |
| Weather not showing | OWM key or missing lat/lon | Set `LOCATION_LAT`, `LOCATION_LON`, `OPENWEATHER_API_KEY` via `railway variables set` |
| Railway build timeout | Free tier resource limit | Retry `railway up`; if persistent, upgrade Railway plan |
| "OAuth consent" loop | Token expired | Re-run OAuth step: delete `google_token.json`, run `bash scripts/setup.sh` |

---

## Re-Running Setup (Idempotent)

Setup saves state to `.railway-setup-state` in the project root. Re-running `bash scripts/setup.sh` skips any step already completed. This is safe to do at any time.

Steps that are re-run if you delete the state entry:
- Google OAuth (delete `google_token.json` to force re-auth)
- Env vars (always safe to re-push — Railway overwrites existing values)

Never commit `.railway-setup-state` — it contains API keys. It's in `.gitignore` by default.
