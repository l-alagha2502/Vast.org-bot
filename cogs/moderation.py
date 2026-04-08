"""
MODULE 3 — Elite Moderation & Security (Anti-Raid).

Features
--------
* /ban /mute /unmute /kick /warn /clear /slowmode /role-multiple
* Anti-Raid: join surge detection → kick/ban new accounts
* Link Protection: whitelist domains
* Anti-Spam: mass mentions + mass emojis
* Strike System (configurable thresholds)
* AI Guard (Google Cloud Natural Language toxicity detection)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
from collections import defaultdict, deque
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from config import BotConfig
from database.base import async_session
from database.models import (
    LinkWhitelist,
    ModerationAction,
    ModerationSettings,
    UserStrike,
)
from utils import db_session, parse_duration

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# AI Guard helper (Google Cloud Natural Language)
# ---------------------------------------------------------------------------

_nl_client = None


def _get_nl_client():
    global _nl_client
    if _nl_client is None and BotConfig.GOOGLE_APPLICATION_CREDENTIALS:
        try:
            from google.cloud import language_v1
            _nl_client = language_v1.LanguageServiceClient()
        except Exception as exc:
            log.warning("AI Guard unavailable: %s", exc)
    return _nl_client


async def _is_toxic(text: str) -> bool:
    """Return True if text is classified as toxic/hateful."""
    client = _get_nl_client()
    if client is None:
        return False
    try:
        loop = asyncio.get_event_loop()
        from google.cloud import language_v1

        doc = language_v1.Document(
            content=text, type_=language_v1.Document.Type.PLAIN_TEXT
        )
        response = await loop.run_in_executor(
            None, lambda: client.moderate_text(document=doc)
        )
        for cat in response.moderation_categories:
            if cat.name in (
                "Toxic",
                "Insult",
                "Identity Attack",
                "Sexually Explicit",
                "Threat",
            ) and cat.confidence > 0.7:
                return True
    except Exception as exc:
        log.debug("AI Guard error: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_settings(guild_id: int) -> ModerationSettings:
    async with async_session() as session:
        row = await session.scalar(
            select(ModerationSettings).where(ModerationSettings.guild_id == guild_id)
        )
        if row is None:
            row = ModerationSettings(guild_id=guild_id)
            session.add(row)
            await session.commit()
    return row


async def _log_action(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    action: str,
    reason: Optional[str],
    duration: Optional[int] = None,
) -> ModerationAction:
    now = datetime.datetime.utcnow()
    expires = (
        now + datetime.timedelta(seconds=duration)
        if duration
        else None
    )
    async with db_session() as session:
        entry = ModerationAction(
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=moderator_id,
            action=action,
            reason=reason,
            duration_seconds=duration,
            expires_at=expires,
        )
        session.add(entry)
    return entry


async def _add_strike(guild_id: int, user_id: int) -> int:
    async with db_session() as session:
        row = await session.scalar(
            select(UserStrike).where(
                UserStrike.guild_id == guild_id,
                UserStrike.user_id == user_id,
            )
        )
        if row is None:
            row = UserStrike(guild_id=guild_id, user_id=user_id, count=0)
            session.add(row)
        row.count += 1
        return row.count


async def _apply_strike_action(
    guild: discord.Guild,
    member: discord.Member,
    strike_count: int,
    settings: ModerationSettings,
    bot: commands.Bot,
) -> str:
    """Enforce the configured strike → action policy."""
    if strike_count >= BotConfig.STRIKE_KICK:
        await member.kick(reason=f"Strike #{strike_count}")
        return "kicked"
    elif strike_count >= BotConfig.STRIKE_MUTE:
        # 10-minute timeout
        until = discord.utils.utcnow() + datetime.timedelta(minutes=10)
        await member.timeout(until, reason=f"Strike #{strike_count}")
        return "muted"
    elif strike_count >= BotConfig.STRIKE_WARN:
        return "warned"
    return "noted"


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Anti-raid join tracking: guild_id -> deque of join timestamps
        self._recent_joins: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )
        self._raid_active: set[int] = set()
        self.unmute_loop.start()

    def cog_unload(self) -> None:
        self.unmute_loop.cancel()

    # ------------------------------------------------------------------
    # Anti-Raid
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        settings = await _get_settings(guild.id)

        now = datetime.datetime.utcnow()

        if settings.anti_raid:
            self._recent_joins[guild.id].append(now)
            # Count joins in the last RAID_JOIN_WINDOW seconds
            cutoff = now - datetime.timedelta(seconds=BotConfig.RAID_JOIN_WINDOW)
            recent = [t for t in self._recent_joins[guild.id] if t >= cutoff]
            if len(recent) >= BotConfig.RAID_JOIN_THRESHOLD:
                if guild.id not in self._raid_active:
                    self._raid_active.add(guild.id)
                    log.warning("RAID DETECTED in guild %s!", guild.id)
                # Auto-action on new accounts
                account_age = (now - member.created_at.replace(tzinfo=None)).days
                if account_age < BotConfig.RAID_ACCOUNT_AGE_DAYS:
                    try:
                        if settings.raid_action == "ban":
                            await guild.ban(member, reason="Anti-Raid: new account")
                        else:
                            await member.kick(reason="Anti-Raid: new account")
                    except discord.HTTPException:
                        pass

    # ------------------------------------------------------------------
    # Link Protection
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        settings = await _get_settings(message.guild.id)

        # ---- Link Protection ----
        if settings.link_protection:
            urls = URL_RE.findall(message.content)
            if urls:
                async with async_session() as session:
                    whitelist_rows = await session.scalars(
                        select(LinkWhitelist).where(
                            LinkWhitelist.guild_id == message.guild.id
                        )
                    )
                    allowed_domains = {r.domain.lower() for r in whitelist_rows}
                blocked = [d for d in urls if d.lower() not in allowed_domains]
                if blocked:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                    await _log_action(
                        message.guild.id, message.author.id,
                        self.bot.user.id, "link_removed", ", ".join(blocked)
                    )
                    strike_count = await _add_strike(message.guild.id, message.author.id)
                    member = message.author
                    if isinstance(member, discord.Member):
                        await _apply_strike_action(message.guild, member, strike_count, settings, self.bot)
                    return

        # ---- Anti-Spam: Mass Mentions ----
        if settings.anti_spam_mentions:
            if len(message.mentions) > BotConfig.MAX_MENTIONS:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                strike_count = await _add_strike(message.guild.id, message.author.id)
                member = message.author
                if isinstance(member, discord.Member):
                    await _apply_strike_action(message.guild, member, strike_count, settings, self.bot)
                return

        # ---- Anti-Spam: Mass Emojis ----
        if settings.anti_spam_emojis:
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F000-\U0001FFFF]", message.content))
            if emoji_count > BotConfig.MAX_EMOJIS:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                return

        # ---- AI Guard ----
        if settings.ai_guard and message.content:
            if await _is_toxic(message.content):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                strike_count = await _add_strike(message.guild.id, message.author.id)
                member = message.author
                if isinstance(member, discord.Member):
                    await _apply_strike_action(message.guild, member, strike_count, settings, self.bot)

    # ------------------------------------------------------------------
    # Expired mute loop
    # ------------------------------------------------------------------

    @tasks.loop(seconds=30)
    async def unmute_loop(self) -> None:
        now = datetime.datetime.utcnow()
        async with async_session() as session:
            rows = await session.scalars(
                select(ModerationAction).where(
                    ModerationAction.action == "mute",
                    ModerationAction.active == True,  # noqa: E712
                    ModerationAction.expires_at <= now,
                )
            )
            for row in rows:
                row.active = False
            await session.commit()

    @unmute_loop.before_loop
    async def before_unmute(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # /ban
    # ------------------------------------------------------------------

    @app_commands.command(name="ban", description="Ban a user from the server.")
    @app_commands.describe(
        user="User to ban",
        reason="Reason for the ban",
        delete_message_days="Days of messages to delete (0–7)",
    )
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = "No reason provided",
        delete_message_days: int = 0,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.guild.ban(
            user,
            reason=f"{reason} | Mod: {interaction.user}",
            delete_message_days=min(max(delete_message_days, 0), 7),
        )
        await _log_action(interaction.guild_id, user.id, interaction.user.id, "ban", reason)
        await interaction.followup.send(f"🔨 **{user}** has been banned. Reason: {reason}")

    # ------------------------------------------------------------------
    # /kick
    # ------------------------------------------------------------------

    @app_commands.command(name="kick", description="Kick a user from the server.")
    @app_commands.describe(user="User to kick", reason="Reason")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = "No reason provided",
    ) -> None:
        await user.kick(reason=f"{reason} | Mod: {interaction.user}")
        await _log_action(interaction.guild_id, user.id, interaction.user.id, "kick", reason)
        await interaction.response.send_message(f"👢 **{user}** has been kicked. Reason: {reason}")

    # ------------------------------------------------------------------
    # /warn
    # ------------------------------------------------------------------

    @app_commands.command(name="warn", description="Warn a user (adds a strike).")
    @app_commands.describe(user="User to warn", reason="Reason")
    @app_commands.default_permissions(manage_messages=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = "No reason provided",
    ) -> None:
        strike_count = await _add_strike(interaction.guild_id, user.id)
        await _log_action(interaction.guild_id, user.id, interaction.user.id, "warn", reason)
        settings = await _get_settings(interaction.guild_id)
        action_taken = await _apply_strike_action(
            interaction.guild, user, strike_count, settings, self.bot
        )
        await interaction.response.send_message(
            f"⚠️ **{user}** warned (Strike #{strike_count}). Action: {action_taken}. Reason: {reason}"
        )

    # ------------------------------------------------------------------
    # /mute
    # ------------------------------------------------------------------

    @app_commands.command(name="mute", description="Mute a user (text and/or voice).")
    @app_commands.describe(
        mute_type="text, voice, or both",
        user="User to mute",
        duration="Duration (e.g. 1h, 30m, 1d 12h)",
        reason="Reason",
    )
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        mute_type: Literal["text", "voice", "both"],
        user: discord.Member,
        duration: str = "10m",
        reason: Optional[str] = "No reason provided",
    ) -> None:
        seconds = parse_duration(duration)
        if seconds <= 0:
            await interaction.response.send_message("❌ Invalid duration.", ephemeral=True)
            return

        until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)

        if mute_type in ("text", "both"):
            # Discord timeout covers text
            await user.timeout(until, reason=reason)

        if mute_type in ("voice", "both"):
            await user.edit(mute=True, reason=reason)

        await _log_action(
            interaction.guild_id, user.id, interaction.user.id,
            "mute", reason, duration=seconds
        )
        await interaction.response.send_message(
            f"🔇 **{user}** muted ({mute_type}) for **{duration}**. Reason: {reason}"
        )

    # ------------------------------------------------------------------
    # /unmute
    # ------------------------------------------------------------------

    @app_commands.command(name="unmute", description="Remove mute from a user.")
    @app_commands.describe(user="User to unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await user.timeout(None)
        try:
            await user.edit(mute=False)
        except discord.HTTPException:
            pass
        await _log_action(interaction.guild_id, user.id, interaction.user.id, "unmute", None)
        await interaction.response.send_message(f"🔊 **{user}** has been unmuted.")

    # ------------------------------------------------------------------
    # /clear
    # ------------------------------------------------------------------

    @app_commands.command(name="clear", description="Bulk-delete messages.")
    @app_commands.describe(
        amount="Number of messages to scan",
        user="Delete messages only from this user",
        bots="Delete messages only from bots",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: int,
        user: Optional[discord.Member] = None,
        bots: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            if user and msg.author != user:
                return False
            if bots and not msg.author.bot:
                return False
            return True

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("❌ This command must be used in a text channel.")
            return

        deleted = await channel.purge(limit=amount + 1, check=check)
        await interaction.followup.send(f"🗑️ Deleted **{len(deleted) - 1}** messages.")

    # ------------------------------------------------------------------
    # /slowmode
    # ------------------------------------------------------------------

    @app_commands.command(name="slowmode", description="Set slowmode on a channel.")
    @app_commands.describe(
        seconds="Slowmode in seconds (0 to disable)",
        channel="Target channel (defaults to current)",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: int,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Invalid channel.", ephemeral=True)
            return
        await target.edit(slowmode_delay=max(0, min(seconds, 21600)))
        await interaction.response.send_message(
            f"⏱️ Slowmode set to **{seconds}s** in {target.mention}."
        )

    # ------------------------------------------------------------------
    # /role-multiple
    # ------------------------------------------------------------------

    @app_commands.command(
        name="role-multiple",
        description="[Admin] Mass assign/remove a role to all or filtered members.",
    )
    @app_commands.describe(
        action="add or remove",
        role="The role to assign/remove",
        filter_role="Only affect members who have this role (optional)",
    )
    @app_commands.default_permissions(administrator=True)
    async def role_multiple(
        self,
        interaction: discord.Interaction,
        action: Literal["add", "remove"],
        role: discord.Role,
        filter_role: Optional[discord.Role] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        members = interaction.guild.members
        if filter_role:
            members = [m for m in members if filter_role in m.roles]

        count = 0
        for member in members:
            try:
                if action == "add" and role not in member.roles:
                    await member.add_roles(role)
                    count += 1
                elif action == "remove" and role in member.roles:
                    await member.remove_roles(role)
                    count += 1
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"✅ {action.capitalize()}d {role.mention} for **{count}** members."
        )

    # ------------------------------------------------------------------
    # /mod-settings
    # ------------------------------------------------------------------

    @app_commands.command(name="mod-settings", description="[Admin] Configure moderation.")
    @app_commands.default_permissions(administrator=True)
    async def mod_settings(
        self,
        interaction: discord.Interaction,
        link_protection: Optional[bool] = None,
        anti_raid: Optional[bool] = None,
        raid_action: Optional[Literal["kick", "ban"]] = None,
        anti_spam_mentions: Optional[bool] = None,
        anti_spam_emojis: Optional[bool] = None,
        ai_guard: Optional[bool] = None,
        log_channel: Optional[discord.TextChannel] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(ModerationSettings).where(
                    ModerationSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = ModerationSettings(guild_id=interaction.guild_id)
                session.add(row)
            if link_protection is not None:
                row.link_protection = link_protection
            if anti_raid is not None:
                row.anti_raid = anti_raid
            if raid_action is not None:
                row.raid_action = raid_action
            if anti_spam_mentions is not None:
                row.anti_spam_mentions = anti_spam_mentions
            if anti_spam_emojis is not None:
                row.anti_spam_emojis = anti_spam_emojis
            if ai_guard is not None:
                row.ai_guard = ai_guard
            if log_channel is not None:
                row.log_channel_id = log_channel.id
        await interaction.response.send_message("✅ Moderation settings updated.", ephemeral=True)

    # ------------------------------------------------------------------
    # /link-whitelist
    # ------------------------------------------------------------------

    @app_commands.command(name="link-whitelist", description="[Admin] Add a domain to the link whitelist.")
    @app_commands.describe(domain="Domain to allow (e.g. discord.com)")
    @app_commands.default_permissions(administrator=True)
    async def link_whitelist(
        self, interaction: discord.Interaction, domain: str
    ) -> None:
        async with db_session() as session:
            existing = await session.scalar(
                select(LinkWhitelist).where(
                    LinkWhitelist.guild_id == interaction.guild_id,
                    LinkWhitelist.domain == domain.lower(),
                )
            )
            if existing is None:
                session.add(LinkWhitelist(guild_id=interaction.guild_id, domain=domain.lower()))
        await interaction.response.send_message(
            f"✅ `{domain}` added to link whitelist.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
