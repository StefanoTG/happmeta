#!/usr/bin/env bash
# ----------------------------------------------------------------------
# SubProxy one-line installer
#
# Usage (any of these work):
#   curl -fsSL https://raw.githubusercontent.com/StefanoTG/happmeta/main/install.sh | sudo bash
#   bash <(curl -fsSL https://raw.githubusercontent.com/StefanoTG/happmeta/main/install.sh)
#   wget -qO- https://raw.githubusercontent.com/StefanoTG/happmeta/main/install.sh | sudo bash
#
# This script ALWAYS prints exactly what it is doing.
# It will never silently hang waiting for input — if stdin isn't a TTY
# (e.g. when piped from curl) it re-execs itself so prompts work.
# ----------------------------------------------------------------------
set -Eeuo pipefail

# ────────────────────────────────────────────── colors / output helpers
c_g="\033[1;32m"; c_y="\033[1;33m"; c_r="\033[1;31m"; c_b="\033[1;36m"; c_0="\033[0m"
TOTAL_STEPS=12
STEP=0
log()   { printf "${c_b}[*]${c_0} %s\n" "$*"; }
ok()    { printf "${c_g}[+]${c_0} %s\n" "$*"; }
warn()  { printf "${c_y}[!]${c_0} %s\n" "$*"; }
die()   { printf "${c_r}[x] %s${c_0}\n" "$*" >&2; exit 1; }
step()  { STEP=$((STEP+1)); printf "\n${c_b}══ [%d/%d] %s${c_0}\n" "$STEP" "$TOTAL_STEPS" "$*"; }

trap 'die "Failed at line $LINENO (step $STEP/$TOTAL_STEPS). Check the output above."' ERR

# ────────────────────────────────────────────── repo / script locations
REPO_URL="https://github.com/StefanoTG/happmeta.git"
SCRIPT_URL="https://raw.githubusercontent.com/StefanoTG/happmeta/main/install.sh"
INSTALL_DIR="/opt/subproxy"
SERVICE_API="subproxy-api"
SERVICE_BOT="subproxy-bot"
CFG_FILE="$INSTALL_DIR/config/config.json"

# ────────────────────────────────────────────── re-exec with a TTY if piped
# When invoked as `curl ... | sudo bash`, stdin is the pipe — `read` would
# block forever, AND we cannot just `cat` ourselves because bash has
# already consumed part of the pipe. Re-download the full script and
# re-exec it with /dev/tty as stdin.
if [[ ! -t 0 ]]; then
    if [[ ! -r /dev/tty ]]; then
        die "No interactive terminal available. Try: bash <(curl -fsSL $SCRIPT_URL)"
    fi
    if ! command -v curl >/dev/null 2>&1; then
        printf "${c_b}[*]${c_0} Installing curl first…\n"
        apt-get update -y >/dev/null && apt-get install -y curl
    fi
    TMP_SELF="$(mktemp /tmp/subproxy-install.XXXXXX.sh)"
    printf "${c_b}[*]${c_0} Downloading installer to %s …\n" "$TMP_SELF"
    curl -fsSL "$SCRIPT_URL" -o "$TMP_SELF" || die "Download failed: $SCRIPT_URL"
    chmod +x "$TMP_SELF"
    printf "${c_b}[*]${c_0} Re-executing with interactive terminal…\n\n"
    exec bash "$TMP_SELF" </dev/tty
fi

# ────────────────────────────────────────────── must be root
[[ $EUID -eq 0 ]] || die "Please run as root (use sudo)."

# ────────────────────────────────────────────── helpers
ask() {
    local prompt="$1" default="${2:-}" reply
    if [[ -n "$default" ]]; then
        read -rp "$(printf "${c_y}?${c_0} %s [%s]: " "$prompt" "$default")" reply
        echo "${reply:-$default}"
    else
        while true; do
            read -rp "$(printf "${c_y}?${c_0} %s: " "$prompt")" reply
            [[ -n "$reply" ]] && { echo "$reply"; return; }
            warn "Value cannot be empty."
        done
    fi
}
ask_yn() {
    local prompt="$1" default="${2:-y}" reply
    read -rp "$(printf "${c_y}?${c_0} %s (y/n) [%s]: " "$prompt" "$default")" reply
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ────────────────────────────────────────────── banner
clear || true
cat <<'BANNER'
==========================================================
              SubProxy — interactive installer
       Pasarguard subscription middleware + TG bot
==========================================================
BANNER
echo

# ────────────────────────────────────────────── prompts
log "Gathering configuration (you can press Enter to accept defaults in [brackets])."
echo

log "Repository: $REPO_URL"
TG_TOKEN=$(ask "Telegram bot token")
TG_ADMIN=$(ask "Telegram admin numeric ID")
PANEL_HOST=$(ask "Real Pasarguard panel domain or IP")
PANEL_PORT=$(ask "Pasarguard panel port" "8443")
PANEL_SCHEME=$(ask "Pasarguard scheme (http/https)" "https")
PUBLIC_DOMAIN=$(ask "Public domain for middleware (e.g. sub.mydomain.com)")
MW_PORT=$(ask "Internal FastAPI port" "8080")
NODE_PREFIX=$(ask "Optional node-name prefix (blank to skip)" " ")
NODE_SUFFIX=$(ask "Optional node-name suffix (blank to skip)" " ")
[[ "$NODE_PREFIX" == " " ]] && NODE_PREFIX=""
[[ "$NODE_SUFFIX" == " " ]] && NODE_SUFFIX=""

SSL_ENABLE="n"; CERTBOT_EMAIL=""
if ask_yn "Configure HTTPS via Certbot (Let's Encrypt)?" "y"; then
    SSL_ENABLE="y"
    CERTBOT_EMAIL=$(ask "Email for Let's Encrypt" "admin@$PUBLIC_DOMAIN")
fi

echo
ok "Configuration captured. Starting installation…"

# ────────────────────────────────────────────── 1. apt update
step "Updating apt package index"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# ────────────────────────────────────────────── 2. system packages
step "Installing system packages (python3, nginx, sqlite3, git, curl)"
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip nginx sqlite3 curl git ca-certificates

# ────────────────────────────────────────────── 3. fetch source
step "Fetching project source into $INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Existing checkout found — pulling latest"
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed; continuing with current files"
elif [[ -d "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    warn "$INSTALL_DIR exists and is non-empty but not a git repo — using current contents."
else
    git clone --depth=1 "$REPO_URL" "$INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR"/{config,database,logs}
ok "Source ready at $INSTALL_DIR"

# ────────────────────────────────────────────── 4. python venv
step "Creating Python virtualenv"
python3 -m venv "$INSTALL_DIR/venv"
ok "venv created at $INSTALL_DIR/venv"

# ────────────────────────────────────────────── 5. pip install
step "Installing Python dependencies (pip will show its own progress)"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
ok "Python dependencies installed"

# ────────────────────────────────────────────── 6. write config
step "Writing $CFG_FILE"
PANEL_VERIFY_SSL=$([[ "$PANEL_SCHEME" == "https" ]] && echo "true" || echo "false")
cat > "$CFG_FILE" <<EOF
{
  "panel": {
    "scheme": "$PANEL_SCHEME",
    "host": "$PANEL_HOST",
    "port": $PANEL_PORT,
    "verify_ssl": $PANEL_VERIFY_SSL,
    "timeout_seconds": 20
  },
  "middleware": {
    "host": "127.0.0.1",
    "port": $MW_PORT,
    "public_domain": "$PUBLIC_DOMAIN",
    "rate_limit_per_minute": 120,
    "log_level": "INFO"
  },
  "telegram": {
    "bot_token": "$TG_TOKEN",
    "admin_ids": [$TG_ADMIN]
  },
  "paths": {
    "database": "$INSTALL_DIR/database/subproxy.db",
    "log_file": "$INSTALL_DIR/logs/subproxy.log"
  }
}
EOF
chmod 600 "$CFG_FILE"
ok "Config saved (chmod 600)"

# ────────────────────────────────────────────── 7. SQLite
step "Initialising SQLite database"
sqlite3 "$INSTALL_DIR/database/subproxy.db" < "$INSTALL_DIR/database/schema.sql"
if [[ -n "$NODE_PREFIX" ]]; then
    sqlite3 "$INSTALL_DIR/database/subproxy.db" \
      "INSERT INTO node_rules (rule_type, replacement, enabled, priority) VALUES ('prefix', '$(printf %s "$NODE_PREFIX" | sed "s/'/''/g")', 1, 10);"
    ok "Default prefix rule added: '$NODE_PREFIX'"
fi
if [[ -n "$NODE_SUFFIX" ]]; then
    sqlite3 "$INSTALL_DIR/database/subproxy.db" \
      "INSERT INTO node_rules (rule_type, replacement, enabled, priority) VALUES ('suffix', '$(printf %s "$NODE_SUFFIX" | sed "s/'/''/g")', 1, 20);"
    ok "Default suffix rule added: '$NODE_SUFFIX'"
fi

# ────────────────────────────────────────────── 8. systemd
step "Installing systemd units"
sed "s/__PORT__/$MW_PORT/g" "$INSTALL_DIR/deploy/subproxy-api.service" \
    > /etc/systemd/system/${SERVICE_API}.service
cp "$INSTALL_DIR/deploy/subproxy-bot.service" /etc/systemd/system/${SERVICE_BOT}.service
install -m 0440 "$INSTALL_DIR/deploy/sudoers.subproxy" /etc/sudoers.d/subproxy
systemctl daemon-reload
ok "Units installed: $SERVICE_API.service, $SERVICE_BOT.service"

# ────────────────────────────────────────────── 9. start services
step "Starting and enabling services"
systemctl enable --now ${SERVICE_API}
systemctl enable --now ${SERVICE_BOT}
sleep 1
systemctl --no-pager --lines=3 status ${SERVICE_API} || true
systemctl --no-pager --lines=3 status ${SERVICE_BOT} || true
ok "Services running"

# ────────────────────────────────────────────── 10. nginx
step "Configuring nginx for $PUBLIC_DOMAIN"
NGX_FILE="/etc/nginx/sites-available/subproxy.conf"
tpl=$(cat "$INSTALL_DIR/deploy/nginx.conf.tpl")
tpl=${tpl//__DOMAIN__/$PUBLIC_DOMAIN}
tpl=${tpl//__PORT__/$MW_PORT}
tpl=${tpl//__HTTP_REDIRECT__/}
tpl=${tpl//__SSL_BLOCK__/}
echo "$tpl" > "$NGX_FILE"
ln -sf "$NGX_FILE" /etc/nginx/sites-enabled/subproxy.conf
[[ -e /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
ok "nginx is serving $PUBLIC_DOMAIN → 127.0.0.1:$MW_PORT"

# ────────────────────────────────────────────── 11. SSL
step "TLS / Certbot"
if [[ "$SSL_ENABLE" == "y" ]]; then
    apt-get install -y certbot python3-certbot-nginx
    if certbot --nginx -d "$PUBLIC_DOMAIN" --non-interactive --agree-tos \
            -m "$CERTBOT_EMAIL" --redirect; then
        ok "HTTPS certificate installed for $PUBLIC_DOMAIN"
    else
        warn "Certbot failed — verify DNS for $PUBLIC_DOMAIN points to this server, then run:"
        warn "  certbot --nginx -d $PUBLIC_DOMAIN"
    fi
else
    log "Skipping HTTPS as requested."
fi

# ────────────────────────────────────────────── 12. summary
step "All done"
PROTO="http"; [[ "$SSL_ENABLE" == "y" ]] && PROTO="https"

cat <<EOF

${c_g}╔════════════════════════════════════════════════════════════╗${c_0}
${c_g}║                 SubProxy installed successfully            ║${c_0}
${c_g}╚════════════════════════════════════════════════════════════╝${c_0}

  Public URL :  ${c_b}${PROTO}://${PUBLIC_DOMAIN}${c_0}
  Upstream   :  ${PANEL_SCHEME}://${PANEL_HOST}:${PANEL_PORT}
  Local API  :  127.0.0.1:${MW_PORT}
  DB         :  ${INSTALL_DIR}/database/subproxy.db
  Config     :  ${CFG_FILE}
  Logs       :  ${INSTALL_DIR}/logs/subproxy.log
                journalctl -u ${SERVICE_API} -f
                journalctl -u ${SERVICE_BOT} -f

  Pasarguard URL Prefix  →  ${c_b}${PROTO}://${PUBLIC_DOMAIN}${c_0}
  Telegram bot           →  open the bot and send /start

EOF
