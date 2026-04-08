"""
Complete database schema for every bot module.

All tables use SQLAlchemy 2 mapped-column style.
Primary keys are explicit; foreign-key relationships use server-side integers
for Discord IDs (stored as BigInteger) since Discord snowflakes exceed 32-bit.
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database.base import Base

# ---------------------------------------------------------------------------
# MODULE 1 — Bot Identity
# ---------------------------------------------------------------------------


class BotIdentity(Base):
    """Per-guild bot identity overrides."""

    __tablename__ = "bot_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    bot_name: Mapped[Optional[str]] = mapped_column(String(80))
    avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    status_type: Mapped[str] = mapped_column(String(20), default="playing")
    status_text: Mapped[Optional[str]] = mapped_column(String(128))
    owner_id: Mapped[Optional[int]] = mapped_column(BigInteger)


# ---------------------------------------------------------------------------
# MODULE 2 — Leveling
# ---------------------------------------------------------------------------


class UserLevel(Base):
    """Tracks text + voice XP per user per guild."""

    __tablename__ = "user_levels"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Text XP
    text_xp: Mapped[int] = mapped_column(Integer, default=0)
    text_level: Mapped[int] = mapped_column(Integer, default=0)
    last_text_xp_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    # Voice XP
    voice_xp: Mapped[int] = mapped_column(Integer, default=0)
    voice_level: Mapped[int] = mapped_column(Integer, default=0)
    voice_joined_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    # Profile card customisation
    bar_color: Mapped[str] = mapped_column(String(7), default="#5865F2")
    text_color: Mapped[str] = mapped_column(String(7), default="#FFFFFF")
    background_url: Mapped[Optional[str]] = mapped_column(Text)


class XpMultiplier(Base):
    """Role-specific XP multipliers."""

    __tablename__ = "xp_multipliers"
    __table_args__ = (UniqueConstraint("guild_id", "role_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)


class XpSettings(Base):
    """Per-guild XP configuration flags."""

    __tablename__ = "xp_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    global_boost_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    global_boost_multiplier: Mapped[float] = mapped_column(Float, default=1.5)
    voice_counter_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)


class XpBlacklist(Base):
    """Channels / roles excluded from XP gain."""

    __tablename__ = "xp_blacklist"
    __table_args__ = (UniqueConstraint("guild_id", "target_id", "target_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(String(10))  # "channel" | "role"


class LevelRoleReward(Base):
    """Roles awarded when a user reaches a level."""

    __tablename__ = "level_role_rewards"
    __table_args__ = (UniqueConstraint("guild_id", "level", "role_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


# ---------------------------------------------------------------------------
# MODULE 3 — Moderation
# ---------------------------------------------------------------------------


class ModerationAction(Base):
    """Audit record of every moderation event."""

    __tablename__ = "moderation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(20))  # warn|mute|kick|ban|unmute|unban
    reason: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserStrike(Base):
    """Strike counter per user per guild."""

    __tablename__ = "user_strikes"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)


class LinkWhitelist(Base):
    """Domains allowed in link-protection mode."""

    __tablename__ = "link_whitelist"
    __table_args__ = (UniqueConstraint("guild_id", "domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)


class ModerationSettings(Base):
    """Per-guild moderation feature toggles."""

    __tablename__ = "moderation_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    link_protection: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_raid: Mapped[bool] = mapped_column(Boolean, default=False)
    raid_action: Mapped[str] = mapped_column(String(10), default="kick")  # kick|ban
    anti_spam_mentions: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_spam_emojis: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_guard: Mapped[bool] = mapped_column(Boolean, default=False)
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    mute_role_id: Mapped[Optional[int]] = mapped_column(BigInteger)


# ---------------------------------------------------------------------------
# MODULE 4 — Automations Engine
# ---------------------------------------------------------------------------


class Automation(Base):
    """An IFTTT-style trigger → action rule."""

    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Trigger
    trigger_event: Mapped[str] = mapped_column(String(50))
    # e.g. message_sent|message_deleted|message_edited|reaction_added|
    #       reaction_removed|voice_join|voice_leave|button_click
    trigger_filter_json: Mapped[Optional[str]] = mapped_column(
        Text
    )  # JSON: channel_id, role_id, content_regex …

    # Action (can be a JSON array of steps)
    actions_json: Mapped[str] = mapped_column(Text)
    # Each step: {"type": "send_message"|"add_role"|"remove_role"|
    #              "delete_message"|"send_dm"|"create_thread"|"move_user",
    #              "params": {...}}

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# MODULE 5 — Social Media Alerts
# ---------------------------------------------------------------------------


class SocialFeed(Base):
    """A social media alert subscription."""

    __tablename__ = "social_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(
        String(20)
    )  # twitch|youtube|twitter|reddit|instagram|tiktok
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embed_color: Mapped[Optional[str]] = mapped_column(String(7))
    message_template: Mapped[Optional[str]] = mapped_column(Text)
    last_post_id: Mapped[Optional[str]] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# MODULE 6 — Music
# ---------------------------------------------------------------------------


class MusicSettings(Base):
    """Per-guild music configuration."""

    __tablename__ = "music_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stay_247: Mapped[bool] = mapped_column(Boolean, default=False)
    default_volume: Mapped[int] = mapped_column(Integer, default=100)
    vote_skip_percent: Mapped[int] = mapped_column(Integer, default=51)
    dj_role_id: Mapped[Optional[int]] = mapped_column(BigInteger)


class SavedPlaylist(Base):
    """User-saved personal playlists."""

    __tablename__ = "saved_playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tracks_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of URLs
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "name"),)


# ---------------------------------------------------------------------------
# MODULE 7 — Utilities / Reaction Roles / Welcome / etc.
# ---------------------------------------------------------------------------


class ReactionRole(Base):
    """Maps an emoji reaction on a message to a role."""

    __tablename__ = "reaction_roles"
    __table_args__ = (UniqueConstraint("guild_id", "message_id", "emoji"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    emoji: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class WelcomeSettings(Base):
    """Per-guild welcome / goodbye configuration."""

    __tablename__ = "welcome_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    welcome_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    goodbye_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text)
    goodbye_message: Mapped[Optional[str]] = mapped_column(Text)
    welcome_image_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    background_url: Mapped[Optional[str]] = mapped_column(Text)
    embed_color: Mapped[str] = mapped_column(String(7), default="#5865F2")


class Birthday(Base):
    """User birthday registry."""

    __tablename__ = "birthdays"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    birthday_month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    birthday_day: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–31
    birthday_role_active: Mapped[bool] = mapped_column(Boolean, default=False)


class BirthdaySettings(Base):
    """Per-guild birthday config."""

    __tablename__ = "birthday_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    birthday_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    birthday_role_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    birthday_message: Mapped[Optional[str]] = mapped_column(Text)


class Timer(Base):
    """Recurring automated messages."""

    __tablename__ = "timers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Ticket(Base):
    """Support ticket record."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|closed
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class TicketSettings(Base):
    """Per-guild ticket panel configuration."""

    __tablename__ = "ticket_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    support_role_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    ticket_category_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    panel_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    panel_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)


# ---------------------------------------------------------------------------
# Economy
# ---------------------------------------------------------------------------


class EconomyAccount(Base):
    """User wallet."""

    __tablename__ = "economy_accounts"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    last_daily_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class ShopItem(Base):
    """An item available in the guild shop."""

    __tablename__ = "shop_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20))  # role|icon
    role_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    stock: Mapped[int] = mapped_column(Integer, default=-1)  # -1 = unlimited


# ---------------------------------------------------------------------------
# Starboard
# ---------------------------------------------------------------------------


class StarboardSettings(Base):
    __tablename__ = "starboard_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    threshold: Mapped[int] = mapped_column(Integer, default=3)
    emoji: Mapped[str] = mapped_column(String(50), default="⭐")


class StarboardEntry(Base):
    __tablename__ = "starboard_entries"
    __table_args__ = (UniqueConstraint("guild_id", "original_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    star_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    star_count: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Custom Commands
# ---------------------------------------------------------------------------


class CustomCommand(Base):
    __tablename__ = "custom_commands"
    __table_args__ = (UniqueConstraint("guild_id", "trigger"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    is_embed: Mapped[bool] = mapped_column(Boolean, default=False)
    embed_color: Mapped[Optional[str]] = mapped_column(String(7))


# ---------------------------------------------------------------------------
# Advanced Invites
# ---------------------------------------------------------------------------


class InviteLink(Base):
    """Tracked invite links with optional role assignment."""

    __tablename__ = "invite_links"
    __table_args__ = (UniqueConstraint("guild_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    role_id: Mapped[Optional[int]] = mapped_column(
        BigInteger
    )  # Role assigned on join via this link
    max_uses: Mapped[int] = mapped_column(Integer, default=-1)  # -1 = unlimited
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class InviteUsage(Base):
    """Who joined via which invite link."""

    __tablename__ = "invite_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invite_code: Mapped[str] = mapped_column(String(20), nullable=False)
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """High-retention custom audit log."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class AuditLogSettings(Base):
    __tablename__ = "audit_log_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    log_message_edits: Mapped[bool] = mapped_column(Boolean, default=True)
    log_message_deletes: Mapped[bool] = mapped_column(Boolean, default=True)
    log_member_join: Mapped[bool] = mapped_column(Boolean, default=True)
    log_member_leave: Mapped[bool] = mapped_column(Boolean, default=True)
    log_role_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    log_channel_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    log_bans: Mapped[bool] = mapped_column(Boolean, default=True)
    log_voice: Mapped[bool] = mapped_column(Boolean, default=True)
