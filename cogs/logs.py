"""
In-depth Audit Logs — listens to Discord events and posts detailed embeds
to a configured log channel. Tracks:
  message edits / deletes, member join / leave, role changes,
  channel changes, bans, voice state updates.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import AuditLog, AuditLogSettings
from utils import db_session

log = logging.getLogger(__name__)


async def _get_settings(guild_id: int) -> Optional[AuditLogSettings]:
    async with async_session() as session:
        return await session.scalar(
            select(AuditLogSettings).where(AuditLogSettings.guild_id == guild_id)
        )


async def _store(
    guild_id: int,
    event_type: str,
    actor_id: Optional[int] = None,
    target_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    async with db_session() as session:
        session.add(
            AuditLog(
                guild_id=guild_id,
                actor_id=actor_id,
                target_id=target_id,
                event_type=event_type,
                detail=detail,
            )
        )


async def _post(guild: discord.Guild, embed: discord.Embed) -> None:
    settings = await _get_settings(guild.id)
    if not settings or not settings.log_channel_id:
        return
    channel = guild.get_channel(settings.log_channel_id)
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


def _e(title: str, color: int = 0xFF6B6B) -> discord.Embed:
    return discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.datetime.utcnow(),
    )


class LogsCog(commands.Cog, name="Logs"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Message events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if not after.guild or after.author.bot:
            return
        settings = await _get_settings(after.guild.id)
        if not settings or not settings.log_message_edits:
            return
        if before.content == after.content:
            return
        embed = _e("✏️ Message Edited", 0xFFA500)
        embed.add_field(name="Author", value=after.author.mention, inline=True)
        embed.add_field(name="Channel", value=after.channel.mention, inline=True)
        embed.add_field(name="Before", value=before.content[:512] or "*empty*", inline=False)
        embed.add_field(name="After", value=after.content[:512] or "*empty*", inline=False)
        embed.add_field(name="Jump", value=f"[Link]({after.jump_url})", inline=True)
        await _post(after.guild, embed)
        await _store(after.guild.id, "message_edit", after.author.id, after.id, after.content[:1000])

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        settings = await _get_settings(message.guild.id)
        if not settings or not settings.log_message_deletes:
            return
        embed = _e("🗑️ Message Deleted", 0xFF4444)
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(
            name="Content",
            value=message.content[:512] or "*no text content*",
            inline=False,
        )
        await _post(message.guild, embed)
        await _store(message.guild.id, "message_delete", message.author.id, message.id)

    # ------------------------------------------------------------------
    # Member events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = await _get_settings(member.guild.id)
        if not settings or not settings.log_member_join:
            return
        age = (discord.utils.utcnow() - member.created_at).days
        embed = _e("📥 Member Joined", 0x57F287)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Account Age", value=f"{age} days", inline=True)
        embed.add_field(name="Member #", value=str(member.guild.member_count), inline=True)
        await _post(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        settings = await _get_settings(member.guild.id)
        if not settings or not settings.log_member_leave:
            return
        embed = _e("📤 Member Left", 0xED4245)
        embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed.add_field(name="Roles", value=", ".join(roles) or "None", inline=False)
        await _post(member.guild, embed)

    # ------------------------------------------------------------------
    # Role changes (member update)
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        settings = await _get_settings(after.guild.id)
        if not settings or not settings.log_role_changes:
            return
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        if not added_roles and not removed_roles:
            return
        embed = _e("🔄 Member Roles Updated", 0x5865F2)
        embed.add_field(name="Member", value=after.mention, inline=False)
        if added_roles:
            embed.add_field(
                name="Roles Added",
                value=", ".join(r.mention for r in added_roles),
                inline=False,
            )
        if removed_roles:
            embed.add_field(
                name="Roles Removed",
                value=", ".join(r.mention for r in removed_roles),
                inline=False,
            )
        await _post(after.guild, embed)

    # ------------------------------------------------------------------
    # Ban events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_ban(
        self, guild: discord.Guild, user: discord.User | discord.Member
    ) -> None:
        settings = await _get_settings(guild.id)
        if not settings or not settings.log_bans:
            return
        embed = _e("🔨 Member Banned", 0xFF0000)
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        await _post(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(
        self, guild: discord.Guild, user: discord.User
    ) -> None:
        settings = await _get_settings(guild.id)
        if not settings or not settings.log_bans:
            return
        embed = _e("✅ Member Unbanned", 0x57F287)
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        await _post(guild, embed)

    # ------------------------------------------------------------------
    # Channel events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        settings = await _get_settings(channel.guild.id)
        if not settings or not settings.log_channel_changes:
            return
        embed = _e("➕ Channel Created", 0x57F287)
        embed.add_field(name="Channel", value=f"#{channel.name} ({channel.id})", inline=False)
        embed.add_field(name="Type", value=str(channel.type), inline=True)
        await _post(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        settings = await _get_settings(channel.guild.id)
        if not settings or not settings.log_channel_changes:
            return
        embed = _e("➖ Channel Deleted", 0xFF4444)
        embed.add_field(name="Channel", value=f"#{channel.name} ({channel.id})", inline=False)
        await _post(channel.guild, embed)

    # ------------------------------------------------------------------
    # Voice events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        settings = await _get_settings(member.guild.id)
        if not settings or not settings.log_voice:
            return
        if before.channel == after.channel:
            return
        if before.channel is None:
            embed = _e("🎤 Member Joined Voice", 0x57F287)
            embed.add_field(name="Member", value=member.mention, inline=True)
            embed.add_field(name="Channel", value=after.channel.name, inline=True)
        elif after.channel is None:
            embed = _e("🔇 Member Left Voice", 0xFF4444)
            embed.add_field(name="Member", value=member.mention, inline=True)
            embed.add_field(name="Channel", value=before.channel.name, inline=True)
        else:
            embed = _e("🔀 Member Moved Voice", 0xFFA500)
            embed.add_field(name="Member", value=member.mention, inline=True)
            embed.add_field(name="From", value=before.channel.name, inline=True)
            embed.add_field(name="To", value=after.channel.name, inline=True)
        await _post(member.guild, embed)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="log-setup",
        description="[Admin] Configure the audit log channel and settings.",
    )
    @app_commands.describe(
        log_channel="Channel to post audit logs",
        message_edits="Log message edits",
        message_deletes="Log message deletes",
        member_join="Log member joins",
        member_leave="Log member leaves",
        role_changes="Log role assignments/removals",
        channel_changes="Log channel creation/deletion",
        bans="Log bans/unbans",
        voice="Log voice state updates",
    )
    @app_commands.default_permissions(administrator=True)
    async def log_setup(
        self,
        interaction: discord.Interaction,
        log_channel: discord.TextChannel,
        message_edits: Optional[bool] = None,
        message_deletes: Optional[bool] = None,
        member_join: Optional[bool] = None,
        member_leave: Optional[bool] = None,
        role_changes: Optional[bool] = None,
        channel_changes: Optional[bool] = None,
        bans: Optional[bool] = None,
        voice: Optional[bool] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(AuditLogSettings).where(
                    AuditLogSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = AuditLogSettings(guild_id=interaction.guild_id)
                session.add(row)
            row.log_channel_id = log_channel.id
            if message_edits is not None:
                row.log_message_edits = message_edits
            if message_deletes is not None:
                row.log_message_deletes = message_deletes
            if member_join is not None:
                row.log_member_join = member_join
            if member_leave is not None:
                row.log_member_leave = member_leave
            if role_changes is not None:
                row.log_role_changes = role_changes
            if channel_changes is not None:
                row.log_channel_changes = channel_changes
            if bans is not None:
                row.log_bans = bans
            if voice is not None:
                row.log_voice = voice
        await interaction.response.send_message(
            f"✅ Audit logs set to {log_channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogsCog(bot))
