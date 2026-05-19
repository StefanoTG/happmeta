"""
Telegram bot command + callback handlers for SubProxy management.

The bot drives all metadata + node-rename configuration through a simple
inline-keyboard UI. State for multi-step inputs is kept in
context.user_data.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import get_config, reload_config
from app.database import get_db

from .keyboards import (
    back_button,
    main_menu,
    metadata_item_kb,
    metadata_list_kb,
    rule_item_kb,
    rule_type_kb,
    rules_list_kb,
)

log = logging.getLogger("subproxy.bot")


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def _is_admin(update: Update) -> bool:
    cfg = get_config()
    admin_ids = set(int(x) for x in cfg.telegram.get("admin_ids", []))
    uid = update.effective_user.id if update.effective_user else None
    return uid in admin_ids


async def _deny(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer("Not authorized.", show_alert=True)
    elif update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized.")


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return await _deny(update)
    context.user_data.clear()
    text = (
        "🛰 *SubProxy Management*\n\n"
        "Manage subscription metadata, node-rename rules, and services from here.\n"
        "Use the buttons below."
    )
    await update.effective_chat.send_message(
        text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN
    )


# ---------------------------------------------------------------------------
# Callback router
# ---------------------------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return await _deny(update)

    q = update.callback_query
    await q.answer()
    data = q.data or ""
    db = get_db()

    try:
        if data == "menu":
            context.user_data.clear()
            await q.edit_message_text(
                "🛰 *SubProxy Management*", reply_markup=main_menu(),
                parse_mode=ParseMode.MARKDOWN,
            )

        # ------------------ metadata ------------------
        elif data == "meta:list":
            items = db.list_metadata()
            text = "*📋 Metadata headers*\n\n" + (
                "\n".join(
                    f"{'✅' if i['enabled'] else '⛔'} `{i['name']}` = `{i['value']}`"
                    for i in items
                ) or "_empty_"
            )
            await q.edit_message_text(text, reply_markup=metadata_list_kb(items),
                                      parse_mode=ParseMode.MARKDOWN)

        elif data == "meta:add":
            context.user_data["state"] = "meta:add:name"
            await q.edit_message_text(
                "📝 Send the *header name* (e.g. `profile-title`):",
                reply_markup=back_button("meta:list"),
                parse_mode=ParseMode.MARKDOWN,
            )

        elif data.startswith("meta:view:"):
            name = data.split(":", 2)[2]
            row = db.get_metadata(name)
            if not row:
                return await q.edit_message_text("Not found.", reply_markup=back_button("meta:list"))
            text = (
                f"*{row['name']}*\n\n"
                f"Value: `{row['value']}`\n"
                f"Enabled: {'✅' if row['enabled'] else '⛔'}"
            )
            await q.edit_message_text(text,
                                      reply_markup=metadata_item_kb(row["name"], bool(row["enabled"])),
                                      parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("meta:edit:"):
            name = data.split(":", 2)[2]
            context.user_data["state"] = "meta:edit:value"
            context.user_data["edit_name"] = name
            await q.edit_message_text(
                f"✏️ Send the new value for `{name}`:",
                reply_markup=back_button("meta:list"),
                parse_mode=ParseMode.MARKDOWN,
            )

        elif data.startswith("meta:toggle:"):
            name = data.split(":", 2)[2]
            row = db.get_metadata(name)
            if row:
                db.set_metadata_enabled(name, not bool(row["enabled"]))
            await _refresh_meta_view(q, db, name)

        elif data.startswith("meta:del:"):
            name = data.split(":", 2)[2]
            db.delete_metadata(name)
            items = db.list_metadata()
            await q.edit_message_text("🗑 Deleted.", reply_markup=metadata_list_kb(items))

        # ------------------ node rules ------------------
        elif data == "rules:list":
            items = db.list_node_rules()
            text = "*🏷 Node-rename rules*\n\n" + (
                "\n".join(
                    f"{'✅' if i['enabled'] else '⛔'} #{i['id']} [{i['rule_type']}] "
                    f"`{(i['pattern'] or '')[:20]}` → `{i['replacement'][:20]}`"
                    for i in items
                ) or "_empty_"
            )
            await q.edit_message_text(text, reply_markup=rules_list_kb(items),
                                      parse_mode=ParseMode.MARKDOWN)

        elif data == "rules:add":
            context.user_data["state"] = "rules:add:type"
            await q.edit_message_text("Choose a rule type:", reply_markup=rule_type_kb())

        elif data.startswith("rules:type:"):
            rtype = data.split(":", 2)[2]
            context.user_data["rule_type"] = rtype
            if rtype in ("regex", "template"):
                context.user_data["state"] = "rules:add:pattern"
                await q.edit_message_text(
                    f"Send the *pattern* for `{rtype}` (regex pattern or template using `{{name}}`):",
                    reply_markup=back_button("rules:list"),
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                context.user_data["state"] = "rules:add:replacement"
                await q.edit_message_text(
                    f"Send the *value* for `{rtype}` (e.g. `🔥 ` or ` | Premium`):",
                    reply_markup=back_button("rules:list"),
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif data.startswith("rules:view:"):
            rid = int(data.split(":", 2)[2])
            row = next((r for r in db.list_node_rules() if r["id"] == rid), None)
            if not row:
                return await q.edit_message_text("Not found.", reply_markup=back_button("rules:list"))
            text = (
                f"*Rule #{row['id']}*\n\n"
                f"Type: `{row['rule_type']}`\n"
                f"Pattern: `{row['pattern'] or '-'}`\n"
                f"Replacement: `{row['replacement']}`\n"
                f"Enabled: {'✅' if row['enabled'] else '⛔'}"
            )
            await q.edit_message_text(text, reply_markup=rule_item_kb(rid, bool(row["enabled"])),
                                      parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("rules:toggle:"):
            rid = int(data.split(":", 2)[2])
            row = next((r for r in db.list_node_rules() if r["id"] == rid), None)
            if row:
                db.set_node_rule_enabled(rid, not bool(row["enabled"]))
            items = db.list_node_rules()
            await q.edit_message_text("Updated.", reply_markup=rules_list_kb(items))

        elif data.startswith("rules:del:"):
            rid = int(data.split(":", 2)[2])
            db.delete_node_rule(rid)
            items = db.list_node_rules()
            await q.edit_message_text("🗑 Deleted.", reply_markup=rules_list_kb(items))

        # ------------------ services ------------------
        elif data == "cfg:show":
            cfg = get_config()
            text = (
                "*⚙️ Current configuration*\n\n"
                f"Panel: `{cfg.panel_base_url}`\n"
                f"Public domain: `{cfg.middleware.get('public_domain')}`\n"
                f"Listen: `{cfg.middleware.get('host')}:{cfg.middleware.get('port')}`\n"
                f"Rate limit: `{cfg.middleware.get('rate_limit_per_minute')}/min`\n"
                f"DB: `{cfg.paths.get('database')}`\n"
                f"Metadata count: `{len(db.list_metadata())}`\n"
                f"Rules count: `{len(db.list_node_rules())}`"
            )
            await q.edit_message_text(text, reply_markup=back_button("menu"),
                                      parse_mode=ParseMode.MARKDOWN)

        elif data == "svc:reload":
            reload_config()
            await q.edit_message_text("🔄 Config reloaded in bot process.\nUse 'Restart Proxy' to reload the FastAPI service.",
                                      reply_markup=back_button("menu"))

        elif data == "svc:restart":
            ok, out = await _restart_service("subproxy-api")
            text = "♻️ Restart " + ("succeeded ✅" if ok else f"failed ❌\n```\n{out}\n```")
            await q.edit_message_text(text, reply_markup=back_button("menu"),
                                      parse_mode=ParseMode.MARKDOWN)

        else:
            await q.edit_message_text("Unknown action.", reply_markup=back_button("menu"))

    except Exception as exc:
        log.exception("callback error")
        await q.edit_message_text(f"⚠️ Error: `{exc}`",
                                  reply_markup=back_button("menu"),
                                  parse_mode=ParseMode.MARKDOWN)


async def _refresh_meta_view(q, db, name: str) -> None:
    row = db.get_metadata(name)
    if not row:
        items = db.list_metadata()
        return await q.edit_message_text("Removed.", reply_markup=metadata_list_kb(items))
    text = (
        f"*{row['name']}*\n\n"
        f"Value: `{row['value']}`\n"
        f"Enabled: {'✅' if row['enabled'] else '⛔'}"
    )
    await q.edit_message_text(text,
                              reply_markup=metadata_item_kb(row["name"], bool(row["enabled"])),
                              parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Free-text message handler (multi-step flows)
# ---------------------------------------------------------------------------
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return await _deny(update)

    state = context.user_data.get("state")
    if not state:
        return  # ignore stray messages
    text = (update.message.text or "").strip()
    db = get_db()

    if state == "meta:add:name":
        if not text:
            return await update.message.reply_text("Header name cannot be empty.")
        context.user_data["new_meta_name"] = text.lower()
        context.user_data["state"] = "meta:add:value"
        await update.message.reply_text(f"Now send the *value* for `{text}`:",
                                        parse_mode=ParseMode.MARKDOWN)

    elif state == "meta:add:value":
        name = context.user_data.pop("new_meta_name", None)
        if not name:
            context.user_data.clear()
            return await update.message.reply_text("Lost context. /start again.")
        db.upsert_metadata(name, text, enabled=True)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Added `{name}` = `{text}`",
            reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN,
        )

    elif state == "meta:edit:value":
        name = context.user_data.pop("edit_name", None)
        if not name:
            context.user_data.clear()
            return await update.message.reply_text("Lost context. /start again.")
        db.upsert_metadata(name, text, enabled=True)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Updated `{name}`",
            reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN,
        )

    elif state == "rules:add:pattern":
        context.user_data["rule_pattern"] = text
        context.user_data["state"] = "rules:add:replacement"
        await update.message.reply_text("Now send the *replacement* value:",
                                        parse_mode=ParseMode.MARKDOWN)

    elif state == "rules:add:replacement":
        rtype = context.user_data.pop("rule_type", None)
        pattern = context.user_data.pop("rule_pattern", None)
        if not rtype:
            context.user_data.clear()
            return await update.message.reply_text("Lost context. /start again.")
        rid = db.add_node_rule(rule_type=rtype, replacement=text,
                               pattern=pattern, enabled=True)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Added rule #{rid} [{rtype}]",
            reply_markup=main_menu(),
        )

    else:
        context.user_data.clear()


# ---------------------------------------------------------------------------
# systemctl wrapper
# ---------------------------------------------------------------------------
async def _restart_service(name: str) -> tuple[bool, str]:
    def _run() -> tuple[bool, str]:
        try:
            r = subprocess.run(
                ["sudo", "-n", "systemctl", "restart", name],
                capture_output=True, text=True, timeout=20,
            )
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except Exception as e:
            return False, str(e)
    return await asyncio.to_thread(_run)
