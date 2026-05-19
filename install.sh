#!/usr/bin/env bash
# ----------------------------------------------------------------------
# SubProxy one-line installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/USERNAME/REPO/main/install.sh | bash
#
# Installs:
#   * system packages (python3, venv, nginx, sqlite3, curl)
#   * /opt/subproxy with the project source
#   * a Python venv with requirements
#   * SQLite database
#   * nginx reverse proxy
#   * systemd services (subproxy-api, subproxy-bot)
#   * optional: certbot + Let's Encrypt
# ----------------------------------------------------------------------
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/StefanoTG/happmeta.git"
INSTALL_DIR="/opt/subproxy"
SERVICE_API="subproxy-api"
SERVICE_BOT="subproxy-bot"
CFG_FILE="$INSTALL_DIR/config/config.json"

c_green="\033[1;32m"; c_yellow="\033[1;33m"; c_red="\033[1;31m"; c_reset="\033[0m"
say()  { printf "${c_green}[+] %s${c_reset}\n" "$*"; }
warn() { printf "${c_yellow}[!] %s${c_reset}\n" "$*"; }
die()  { printf "${c_red}[x] %s${c_reset}\n" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Please run as root (sudo bash install.sh)."

# Re-exec with a TTY if piped from curl, so prompts work
if [[ ! -t 0 ]] && [[ -t 1 ]]; then
    exec </dev/tty
fi

# ---------------------------------------------------------------- prompts
ask() {
    # ask "Prompt" "default"
    local prompt="$1" default="${2:-}" reply
    if [[ -n "$default" ]]; then
        read -rp "$prompt [$default]: " reply
        echo "${reply:-$default}"
    else
        read -rp "$prompt: " reply
        echo "$reply"
    fi
}

ask_yn() {
    local prompt="$1" default="${2:-y}" reply
    read -rp "$prompt (y/n) [$default]: " reply
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[Yy]$ ]]
}

echo "============================================="
echo "       SubProxy — interactive installer       "
echo "============================================="

REPO_URL=$(ask "Git repository URL" "$REPO_URL_DEFAULT")
TG_TOKEN=$(ask "Telegram bot token")
TG_ADMIN=$(ask "Telegram admin numeric ID")
PANEL_HOST=$(ask "Real Pasarguard panel domain or IP")
PANEL_PORT=$(ask "Pasarguard panel port" "8443")
PANEL_SCHEME=$(ask "Pasarguard scheme (http/https)" "https")
PUBLIC_DOMAIN=$(ask "Public domain for middleware (e.g. sub.mydomain.com)")
MW_PORT=$(ask "Internal FastAPI port" "8080")
NODE_PREFIX=$(ask "Optional node-name prefix (blank to skip)" "")
NODE_SUFFIX=$(ask "Optional node-name suffix (blank to skip)" "")

SSL_ENABLE="n"
if ask_yn "Configure HTTPS via Certbot (Let's Encrypt)?" "y"; then
    SSL_ENABLE="y"
    CERTBOT_EMAIL=$(ask "Email for Let's Encrypt") || true
fi

[[ -n "$TG_TOKEN" && -n "$TG_ADMIN" && -n "$PANEL_HOST" && -n "$PUBLIC_DOMAIN" ]] \
    || die "Missing required answers."

# ---------------------------------------------------------------- packages
say "Installing system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx sqlite3 curl git ca-certificates

# ---------------------------------------------------------------- source
if [[ -d "$INSTALL_DIR/.git" ]]; then
    say "Updating existing $INSTALL_DIR…"
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed; continuing"
elif [[ -d "$INSTALL_DIR" ]]; then
    warn "$INSTALL_DIR exists but is not a git repo; using current contents."
else
    say "Cloning $REPO_URL → $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"/{config,database,logs}

# ---------------------------------------------------------------- venv
say "Setting up Python venv…"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# ---------------------------------------------------------------- config
say "Writing $CFG_FILE…"
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

# ---------------------------------------------------------------- seed DB
say "Initialising SQLite database…"
sqlite3 "$INSTALL_DIR/database/subproxy.db" < "$INSTALL_DIR/database/schema.sql"

# Seed optional default node rules
if [[ -n "$NODE_PREFIX" ]]; then
    sqlite3 "$INSTALL_DIR/database/subproxy.db" \
      "INSERT INTO node_rules (rule_type, replacement, enabled, priority) VALUES ('prefix', '$NODE_PREFIX', 1, 10);"
fi
if [[ -n "$NODE_SUFFIX" ]]; then
    sqlite3 "$INSTALL_DIR/database/subproxy.db" \
      "INSERT INTO node_rules (rule_type, replacement, enabled, priority) VALUES ('suffix', '$NODE_SUFFIX', 1, 20);"
fi

# ---------------------------------------------------------------- systemd
say "Installing systemd units…"
sed "s/__PORT__/$MW_PORT/g" "$INSTALL_DIR/deploy/subproxy-api.service" \
    > /etc/systemd/system/${SERVICE_API}.service
cp "$INSTALL_DIR/deploy/subproxy-bot.service" /etc/systemd/system/${SERVICE_BOT}.service

# Sudoers so the bot can restart the API
install -m 0440 "$INSTALL_DIR/deploy/sudoers.subproxy" /etc/sudoers.d/subproxy

systemctl daemon-reload
systemctl enable --now ${SERVICE_API}
systemctl enable --now ${SERVICE_BOT}

# ---------------------------------------------------------------- nginx
say "Configuring nginx for $PUBLIC_DOMAIN…"
NGX_FILE="/etc/nginx/sites-available/subproxy.conf"
tpl=$(cat "$INSTALL_DIR/deploy/nginx.conf.tpl")
tpl=${tpl//__DOMAIN__/$PUBLIC_DOMAIN}
tpl=${tpl//__PORT__/$MW_PORT}
tpl=${tpl//__HTTP_REDIRECT__/}
tpl=${tpl//__SSL_BLOCK__/}
echo "$tpl" > "$NGX_FILE"
ln -sf "$NGX_FILE" /etc/nginx/sites-enabled/subproxy.conf
nginx -t && systemctl reload nginx

# ---------------------------------------------------------------- ssl
if [[ "$SSL_ENABLE" == "y" ]]; then
    say "Installing certbot and obtaining certificate…"
    apt-get install -y certbot python3-certbot-nginx
    certbot --nginx -d "$PUBLIC_DOMAIN" --non-interactive --agree-tos \
            -m "${CERTBOT_EMAIL:-admin@$PUBLIC_DOMAIN}" --redirect || \
        warn "Certbot failed; you can rerun it manually."
fi

# ---------------------------------------------------------------- done
say "Installation complete."
echo
echo "  Public URL :  https://$PUBLIC_DOMAIN"
echo "  Upstream   :  $PANEL_SCHEME://$PANEL_HOST:$PANEL_PORT"
echo "  Services   :  systemctl status $SERVICE_API $SERVICE_BOT"
echo "  Telegram   :  open the bot, send /start"
echo
echo "Set Pasarguard URL Prefix to:  https://$PUBLIC_DOMAIN"
