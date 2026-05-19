"""Inline keyboard builders for the SubProxy Telegram bot."""
from __future__ import annotations

from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📋 Metadata", callback_data="meta:list"),
            InlineKeyboardButton("🏷  Node Rules", callback_data="rules:list"),
        ],
        [
            InlineKeyboardButton("➕ Add Metadata", callback_data="meta:add"),
            InlineKeyboardButton("➕ Add Rule", callback_data="rules:add"),
        ],
        [
            InlineKeyboardButton("⚙️  Current Config", callback_data="cfg:show"),
        ],
        [
            InlineKeyboardButton("🔄 Reload Config", callback_data="svc:reload"),
            InlineKeyboardButton("♻️  Restart Proxy", callback_data="svc:restart"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def back_button(target: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])


def metadata_list_kb(items: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        mark = "✅" if it["enabled"] else "⛔"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {it['name']}",
                callback_data=f"meta:view:{it['name']}",
            )
        ])
    rows.append([
        InlineKeyboardButton("➕ Add", callback_data="meta:add"),
        InlineKeyboardButton("⬅️ Back", callback_data="menu"),
    ])
    return InlineKeyboardMarkup(rows)


def metadata_item_kb(name: str, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "⛔ Disable" if enabled else "✅ Enable"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit Value", callback_data=f"meta:edit:{name}"),
            InlineKeyboardButton(toggle_label, callback_data=f"meta:toggle:{name}"),
        ],
        [
            InlineKeyboardButton("🗑 Delete", callback_data=f"meta:del:{name}"),
            InlineKeyboardButton("⬅️ Back", callback_data="meta:list"),
        ],
    ])


def rules_list_kb(items: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for it in items:
        mark = "✅" if it["enabled"] else "⛔"
        label = f"{mark} #{it['id']} [{it['rule_type']}] {it['replacement'][:20]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rules:view:{it['id']}")])
    rows.append([
        InlineKeyboardButton("➕ Add", callback_data="rules:add"),
        InlineKeyboardButton("⬅️ Back", callback_data="menu"),
    ])
    return InlineKeyboardMarkup(rows)


def rule_item_kb(rule_id: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "⛔ Disable" if enabled else "✅ Enable"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(toggle_label, callback_data=f"rules:toggle:{rule_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"rules:del:{rule_id}"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="rules:list")],
    ])


def rule_type_kb() -> InlineKeyboardMarkup:
    types = ["prefix", "suffix", "emoji", "regex", "template"]
    rows = [[InlineKeyboardButton(t, callback_data=f"rules:type:{t}")] for t in types]
    rows.append([InlineKeyboardButton("⬅️ Cancel", callback_data="menu")])
    return InlineKeyboardMarkup(rows)
