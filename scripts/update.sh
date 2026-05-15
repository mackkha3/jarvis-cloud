#!/usr/bin/env bash
# =============================================================
#  J.A.R.V.I.S Cloud — Push Updates to a Customer Instance
#
#  Usage:
#    bash scripts/update.sh [railway-project-name]
#
#  If project name is omitted, uses the currently linked project.
# =============================================================
set -euo pipefail

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

# ── Sanity checks ────────────────────────────────────────────
if [ ! -f "run.py" ]; then
  error "Run from the jarvis-cloud project root."
  exit 1
fi

if ! command -v railway &>/dev/null; then
  error "Railway CLI not found. Install: npm install -g @railway/cli"
  exit 1
fi

PROJECT_NAME="${1:-}"
STATE_FILE=".railway-setup-state"

# ── Load saved URL from setup state ─────────────────────────
RAILWAY_URL=""
if [ -f "$STATE_FILE" ]; then
  RAILWAY_URL=$(grep "^RAILWAY_URL=" "$STATE_FILE" 2>/dev/null | cut -d= -f2- || true)
fi

# ── Link to project if name given ───────────────────────────
if [ -n "$PROJECT_NAME" ]; then
  info "Linking to Railway project: $PROJECT_NAME"
  railway link --project "$PROJECT_NAME" 2>/dev/null || {
    error "Could not link to project '$PROJECT_NAME'."
    error "Run 'railway link' manually and then re-run this script."
    exit 1
  }
  success "Linked to project: $PROJECT_NAME"
else
  # Confirm we're already linked
  if ! railway status &>/dev/null 2>&1; then
    error "No Railway project linked. Run: bash scripts/setup.sh"
    error "Or specify the project name: bash scripts/update.sh my-project-name"
    exit 1
  fi
  PROJECT_NAME=$(railway status 2>/dev/null | grep -i "Project:" | awk '{print $2}' || echo "current project")
fi

echo ""
echo -e "${BLD}Deploying update to: ${CYN}${PROJECT_NAME}${RST}"
echo ""

# ── Deploy ───────────────────────────────────────────────────
info "Pushing to Railway (detached)..."
railway up --detach
success "Deployment submitted"

# ── Resolve URL if we don't have it ─────────────────────────
if [ -z "$RAILWAY_URL" ]; then
  for i in 1 2 3; do
    RAILWAY_URL=$(railway status 2>/dev/null | grep -iE "https?://" | grep -oE "https?://[^ ]+" | head -1 || true)
    [ -n "$RAILWAY_URL" ] && break
    sleep 5
  done
fi

if [ -z "$RAILWAY_URL" ]; then
  warn "Could not determine Railway URL automatically."
  echo -n "Paste the service URL from your Railway dashboard: "
  read -r RAILWAY_URL
fi

RAILWAY_URL="${RAILWAY_URL%/}"
echo ""

# ── Wait for health check ────────────────────────────────────
info "Waiting for health check at ${RAILWAY_URL}/health ..."
MAX_WAIT=180
ELAPSED=0
INTERVAL=10
HTTP_CODE="000"

while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "${RAILWAY_URL}/health" --max-time 10 || echo "000")

  if [ "$HTTP_CODE" = "200" ]; then
    break
  fi

  printf "\r${YEL}  Waiting... %ds (HTTP %s)${RST}" "$ELAPSED" "$HTTP_CODE"
  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""

if [ "$HTTP_CODE" = "200" ]; then
  success "Health check passed — JARVIS is live"
  echo ""
  echo -e "  Dashboard: ${CYN}${RAILWAY_URL}/dashboard${RST}"
else
  warn "Health check did not pass within ${MAX_WAIT}s (last status: HTTP $HTTP_CODE)."
  warn "The deployment may still be starting. Check:"
  warn "  curl ${RAILWAY_URL}/health"
  warn "  railway logs"
  exit 1
fi
