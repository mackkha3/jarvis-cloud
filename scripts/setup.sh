#!/usr/bin/env bash
# =============================================================
#  J.A.R.V.I.S Cloud — Customer BYOI Setup Script
#  Walks a new customer through deploying their own JARVIS
#  instance to their personal Railway account.
#
#  Run from the project root:  bash scripts/setup.sh
#  Safe to run twice — idempotent.
# =============================================================
set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YEL='\033[1;33m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

info()    { echo -e "${CYN}[INFO]${RST} $*"; }
success() { echo -e "${GRN}[OK]${RST}   $*"; }
warn()    { echo -e "${YEL}[WARN]${RST} $*"; }
error()   { echo -e "${RED}[ERR]${RST}  $*" >&2; }
header()  { echo -e "\n${BLD}${CYN}── $* ──────────────────────────────────${RST}"; }
prompt()  { echo -e -n "${BLD}${YEL}▶ $*${RST} "; }

# ── Ensure we're in the project root ────────────────────────
if [ ! -f "run.py" ] || [ ! -f "requirements.txt" ]; then
  error "Run this script from the jarvis-cloud project root."
  error "  cd ~/jarvis-cloud && bash scripts/setup.sh"
  exit 1
fi

PROJECT_ROOT="$(pwd)"
STATE_FILE=".railway-setup-state"

# ── Load saved state (idempotency) ──────────────────────────
load_state() {
  [ -f "$STATE_FILE" ] && source "$STATE_FILE" || true
}

save_state() {
  local key="$1" val="$2"
  # Overwrite or append key=value in state file
  if grep -q "^${key}=" "$STATE_FILE" 2>/dev/null; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' "s|^${key}=.*|${key}=${val}|" "$STATE_FILE"
    else
      sed -i "s|^${key}=.*|${key}=${val}|" "$STATE_FILE"
    fi
  else
    echo "${key}=${val}" >> "$STATE_FILE"
  fi
}

load_state

# ═══════════════════════════════════════════════════════════
#  STEP 1 — PREREQUISITES
# ═══════════════════════════════════════════════════════════
header "Step 1: Prerequisites"

# Python 3.11+
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
  error "Python 3.11+ required. Found: $PYTHON_VERSION"
  error "Install from https://www.python.org/downloads/"
  exit 1
fi
success "Python $PYTHON_VERSION"

# git
if ! command -v git &>/dev/null; then
  error "git is required. Install from https://git-scm.com/"
  exit 1
fi
success "git $(git --version | awk '{print $3}')"

# Railway CLI
if ! command -v railway &>/dev/null; then
  echo ""
  warn "Railway CLI not found. Installing now..."
  if command -v npm &>/dev/null; then
    npm install -g @railway/cli
  elif command -v brew &>/dev/null; then
    brew install railway
  else
    error "Could not install Railway CLI automatically."
    error "Install manually: https://docs.railway.app/develop/cli"
    error "Then re-run this script."
    exit 1
  fi
fi
success "Railway CLI $(railway --version 2>/dev/null | head -1)"

# curl (for API validation)
if ! command -v curl &>/dev/null; then
  error "curl is required. Install it via your package manager."
  exit 1
fi
success "curl available"

# ═══════════════════════════════════════════════════════════
#  STEP 2 — CUSTOMER INFO
# ═══════════════════════════════════════════════════════════
header "Step 2: Your JARVIS Configuration"
echo "  These settings personalise JARVIS for you."
echo ""

collect_if_missing() {
  local var="$1" label="$2" default="${3:-}"
  if [ -z "${!var:-}" ]; then
    if [ -n "$default" ]; then
      prompt "$label [$default]:"
      read -r input
      eval "${var}=\"${input:-$default}\""
    else
      while [ -z "${!var:-}" ]; do
        prompt "$label:"
        read -r input
        eval "${var}=\"${input}\""
        [ -z "${!var}" ] && warn "This field is required."
      done
    fi
    save_state "$var" "${!var}"
  else
    success "$label: ${!var}  (saved from previous run)"
  fi
}

collect_if_missing OWNER_NAME      "Your first name (e.g. Mike)"
collect_if_missing OWNER_TITLE     "How JARVIS addresses you" "Boss"
collect_if_missing TIMEZONE        "Your timezone (IANA format)" "America/Chicago"
collect_if_missing LOCATION_CITY   "Your city (leave blank to skip)" ""
collect_if_missing LOCATION_LAT    "Latitude  (leave blank to skip)" "0.0"
collect_if_missing LOCATION_LON    "Longitude (leave blank to skip)" "0.0"

# Generate JARVIS_API_KEY if not already done
if [ -z "${JARVIS_API_KEY:-}" ]; then
  JARVIS_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  save_state "JARVIS_API_KEY" "$JARVIS_API_KEY"
  success "JARVIS API key generated (saved)"
else
  success "JARVIS API key: already set"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 3 — ANTHROPIC API KEY
# ═══════════════════════════════════════════════════════════
header "Step 3: Anthropic API Key"
echo "  Get yours at: https://console.anthropic.com/"
echo "  It starts with: sk-ant-"
echo ""

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  while true; do
    prompt "Paste your Anthropic API key:"
    read -r ANTHROPIC_API_KEY
    if [[ "$ANTHROPIC_API_KEY" != sk-ant-* ]]; then
      warn "Anthropic keys must start with 'sk-ant-'. Try again."
      ANTHROPIC_API_KEY=""
      continue
    fi

    info "Validating key with Anthropic API..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      "https://api.anthropic.com/v1/models" \
      -H "x-api-key: ${ANTHROPIC_API_KEY}" \
      -H "anthropic-version: 2023-06-01" \
      --max-time 10)

    if [ "$HTTP_CODE" = "200" ]; then
      success "Anthropic API key is valid"
      save_state "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY"
      break
    elif [ "$HTTP_CODE" = "401" ]; then
      warn "Key rejected (401 Unauthorized). Check you copied the full key."
      ANTHROPIC_API_KEY=""
    elif [ "$HTTP_CODE" = "000" ]; then
      warn "Network error — could not reach api.anthropic.com. Check your internet."
      prompt "Retry? (y/n):"
      read -r retry
      [ "$retry" != "y" ] && { ANTHROPIC_API_KEY=""; break; }
    else
      warn "Unexpected response (HTTP $HTTP_CODE). Saving key anyway."
      save_state "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY"
      break
    fi
  done
else
  success "Anthropic API key: already validated"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 4 — OPENWEATHERMAP API KEY (optional)
# ═══════════════════════════════════════════════════════════
header "Step 4: OpenWeatherMap API Key (optional)"
echo "  Free tier at: https://openweathermap.org/api"
echo "  Press ENTER to skip weather features."
echo ""

if [ -z "${OPENWEATHER_API_KEY:-}" ]; then
  prompt "OpenWeatherMap API key (or ENTER to skip):"
  read -r OWM_INPUT
  if [ -n "$OWM_INPUT" ]; then
    info "Validating OWM key..."
    OWM_CITY="${LOCATION_CITY:-London}"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      "https://api.openweathermap.org/data/2.5/weather?q=${OWM_CITY}&appid=${OWM_INPUT}" \
      --max-time 10)
    if [ "$HTTP_CODE" = "200" ]; then
      success "OpenWeatherMap key is valid"
      OPENWEATHER_API_KEY="$OWM_INPUT"
    elif [ "$HTTP_CODE" = "401" ]; then
      warn "OWM key rejected — check it was copied correctly. Disabling weather."
      OPENWEATHER_API_KEY=""
    else
      warn "Could not validate OWM key (HTTP $HTTP_CODE). Saving it anyway."
      OPENWEATHER_API_KEY="$OWM_INPUT"
    fi
    save_state "OPENWEATHER_API_KEY" "$OPENWEATHER_API_KEY"
  else
    OPENWEATHER_API_KEY=""
    success "Weather skipped"
  fi
else
  success "OpenWeatherMap key: already set"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 5 — GOOGLE OAUTH
# ═══════════════════════════════════════════════════════════
header "Step 5: Google Account (Calendar, Tasks, Gmail)"
echo ""

setup_google_auth() {
  # Check for credentials.json
  if [ ! -f "credentials.json" ]; then
    echo "  You need a Google OAuth credentials file (credentials.json)."
    echo ""
    echo "  How to get it:"
    echo "    1. Go to https://console.cloud.google.com/"
    echo "    2. Create a project (e.g. 'JARVIS Cloud')"
    echo "    3. Enable these APIs: Google Calendar, Tasks, Gmail"
    echo "       (APIs & Services → Library → search each one → Enable)"
    echo "    4. Go to APIs & Services → Credentials"
    echo "    5. Create Credentials → OAuth 2.0 Client ID"
    echo "    6. Application type: Desktop app  →  Name: JARVIS"
    echo "    7. Click Download JSON"
    echo "    8. Rename the file to: credentials.json"
    echo "    9. Move it into this folder: $(pwd)"
    echo ""
    prompt "Press ENTER when credentials.json is in place..."
    read -r

    if [ ! -f "credentials.json" ]; then
      error "credentials.json not found in $(pwd)"
      error "Cannot continue without Google credentials."
      exit 1
    fi
  fi
  success "credentials.json found"

  # Run OAuth flow if we don't have a token yet
  if [ ! -f "google_token.json" ]; then
    echo ""
    info "Opening Google sign-in in your browser..."
    echo "  → Sign in with the Google account JARVIS should access."
    echo "  → Grant all requested permissions."
    echo ""

    python3 - <<'PYEOF'
from google_auth_oauthlib.flow import InstalledAppFlow
import sys

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

try:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    with open("google_token.json", "w") as f:
        f.write(creds.to_json())
    print("Google authentication successful!")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

    if [ $? -ne 0 ]; then
      error "Google OAuth flow failed."
      error "Make sure google-auth-oauthlib is installed: pip install google-auth-oauthlib"
      exit 1
    fi
  else
    success "google_token.json already exists — skipping re-auth"
  fi

  # Base64-encode the token for Railway env var
  if [[ "$OSTYPE" == "darwin"* ]]; then
    GOOGLE_TOKEN_JSON=$(base64 -i google_token.json | tr -d '\n')
  else
    GOOGLE_TOKEN_JSON=$(base64 -w 0 google_token.json)
  fi
  save_state "GOOGLE_TOKEN_JSON" "$GOOGLE_TOKEN_JSON"
  success "Google token encoded for cloud deployment"
}

if [ -z "${GOOGLE_TOKEN_JSON:-}" ]; then
  setup_google_auth
else
  success "Google token: already encoded (saved from previous run)"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 6 — RAILWAY LOGIN & PROJECT
# ═══════════════════════════════════════════════════════════
header "Step 6: Railway Project Setup"
echo ""

# Login (idempotent — railway whoami exits 0 if already logged in)
if railway whoami &>/dev/null; then
  RAILWAY_USER=$(railway whoami 2>/dev/null | head -1)
  success "Already logged in to Railway as: $RAILWAY_USER"
else
  info "Opening Railway login in your browser..."
  railway login
  success "Logged in to Railway"
fi

# Init or link project
if [ -z "${RAILWAY_PROJECT_NAME:-}" ]; then
  echo ""
  echo "  What should we call your JARVIS Railway project?"
  echo "  This is just the project name in your Railway dashboard."
  prompt "Project name [jarvis-cloud]:"
  read -r RAILWAY_PROJECT_NAME
  RAILWAY_PROJECT_NAME="${RAILWAY_PROJECT_NAME:-jarvis-cloud}"
  save_state "RAILWAY_PROJECT_NAME" "$RAILWAY_PROJECT_NAME"
fi

# Check if already linked
if railway status &>/dev/null 2>&1; then
  success "Railway project already linked"
else
  info "Creating Railway project: $RAILWAY_PROJECT_NAME"
  railway init --name "$RAILWAY_PROJECT_NAME" 2>/dev/null || {
    warn "Could not auto-create project. Trying to link..."
    railway link
  }
  success "Railway project ready"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 7 — SET ENVIRONMENT VARIABLES IN RAILWAY
# ═══════════════════════════════════════════════════════════
header "Step 7: Configuring Environment Variables"
echo ""

set_railway_var() {
  local key="$1" val="$2"
  if [ -z "$val" ]; then return; fi
  railway variables set "${key}=${val}" 2>/dev/null && success "  SET: $key" || warn "  FAILED: $key"
}

set_railway_var "OWNER_NAME"            "$OWNER_NAME"
set_railway_var "OWNER_TITLE"           "$OWNER_TITLE"
set_railway_var "TIMEZONE"              "$TIMEZONE"
set_railway_var "LOCATION_CITY"         "$LOCATION_CITY"
set_railway_var "LOCATION_LAT"          "$LOCATION_LAT"
set_railway_var "LOCATION_LON"          "$LOCATION_LON"
set_railway_var "JARVIS_API_KEY"        "$JARVIS_API_KEY"
set_railway_var "ANTHROPIC_API_KEY"     "$ANTHROPIC_API_KEY"
set_railway_var "GOOGLE_TOKEN_JSON"     "$GOOGLE_TOKEN_JSON"
set_railway_var "OPENWEATHER_API_KEY"   "$OPENWEATHER_API_KEY"
set_railway_var "ENVIRONMENT"           "production"
set_railway_var "DEBUG"                 "false"
set_railway_var "LOG_LEVEL"             "INFO"
set_railway_var "CLAUDE_MODEL_DEFAULT"  "claude-haiku-4-5-20251001"
set_railway_var "CLAUDE_MODEL_COMPLEX"  "claude-sonnet-4-5"

success "All environment variables configured"

# ═══════════════════════════════════════════════════════════
#  STEP 8 — DEPLOY
# ═══════════════════════════════════════════════════════════
header "Step 8: Deploying to Railway"
echo ""

info "Starting deployment (this takes 2-4 minutes)..."
railway up

success "Deployment submitted"

# ═══════════════════════════════════════════════════════════
#  STEP 9 — HEALTH CHECK
# ═══════════════════════════════════════════════════════════
header "Step 9: Health Check"
echo ""

# Try to get the Railway URL
RAILWAY_URL=""
for i in 1 2 3; do
  RAILWAY_URL=$(railway status 2>/dev/null | grep -iE "https?://" | grep -oE "https?://[^ ]+" | head -1 || true)
  [ -n "$RAILWAY_URL" ] && break
  sleep 5
done

if [ -z "$RAILWAY_URL" ]; then
  warn "Could not auto-detect Railway URL."
  prompt "Paste your Railway service URL (from the dashboard):"
  read -r RAILWAY_URL
fi

# Strip trailing slash
RAILWAY_URL="${RAILWAY_URL%/}"
save_state "RAILWAY_URL" "$RAILWAY_URL"

echo ""
info "Waiting for JARVIS to come online at $RAILWAY_URL..."
MAX_WAIT=180
ELAPSED=0
INTERVAL=10

while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "${RAILWAY_URL}/health" --max-time 10 || echo "000")

  if [ "$HTTP_CODE" = "200" ]; then
    success "JARVIS is online!"
    break
  fi

  printf "\r${YEL}  Waiting... %ds elapsed (status: %s)${RST}" "$ELAPSED" "$HTTP_CODE"
  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
if [ "$HTTP_CODE" != "200" ]; then
  warn "Health check timed out after ${MAX_WAIT}s."
  warn "Deployment may still be in progress. Check the Railway dashboard."
  warn "Run: curl ${RAILWAY_URL}/health"
fi

# ═══════════════════════════════════════════════════════════
#  DONE — SUMMARY
# ═══════════════════════════════════════════════════════════
header "Setup Complete"
echo ""
echo -e "  ${BLD}Your JARVIS instance:${RST}"
echo -e "    Dashboard:  ${CYN}${RAILWAY_URL}/dashboard${RST}"
echo -e "    Morning:    ${CYN}${RAILWAY_URL}/morning-brief.html${RST}"
echo -e "    Evening:    ${CYN}${RAILWAY_URL}/evening-debrief.html${RST}"
echo -e "    Digest:     ${CYN}${RAILWAY_URL}/digest${RST}"
echo -e "    Health:     ${CYN}${RAILWAY_URL}/health${RST}"
echo ""
echo -e "  ${BLD}Your API Key (for dashboard login):${RST}"
echo -e "    ${YEL}${JARVIS_API_KEY}${RST}"
echo ""
echo -e "  ${BLD}Save this key — you'll need it to log into the dashboard.${RST}"
echo ""
echo "  Setup state saved to: ${PROJECT_ROOT}/${STATE_FILE}"
echo "  DO NOT commit ${STATE_FILE} — it contains secrets."
echo ""
success "JARVIS Cloud is live. Good luck, ${OWNER_NAME}."
