"""
Advanced Invites — Auto-role by invite link, temporary links (expire by time or use count).
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
from database.models import InviteLink, InviteUsage
from utils import db_session, parse_duration

log = logging.getLogger(__name__)


class InvitesCog(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> {code: uses}
        self._invite_cache: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Seed invite cache."""
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild:
            self._invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            return

        current_map = {inv.code: inv.uses for inv in current_invites}
        old_map = self._invite_cache.get(guild.id, {})

        used_code = None
        for code, uses in current_map.items():
            if uses > old_map.get(code, 0):
                used_code = code
                break

        # Update cache
        self._invite_cache[guild.id] = current_map

        if used_code is None:
            return

        # Log usage
        async with db_session() as session:
            session.add(
                InviteUsage(
                    guild_id=guild.id,
                    user_id=member.id,
                    invite_code=used_code,
                )
            )

        # Check tracked invite for role reward
        async with async_session() as session:
            row = await session.scalar(
                select(InviteLink).where(
                    InviteLink.guild_id == guild.id,
                    InviteLink.code == used_code,
                    InviteLink.enabled == True,  # noqa: E712
                )
            )
        if row is None:
            return

        # Expire by time
        if row.expires_at and datetime.datetime.utcnow() >= row.expires_at:
            async with db_session() as session:
                db_row = await session.get(InviteLink, row.id)
                if db_row:
                    db_row.enabled = False
            return

        # Expire by use count
        if row.max_uses != -1 and row.uses >= row.max_uses:
            async with db_session() as session:
                db_row = await session.get(InviteLink, row.id)
                if db_row:
                    db_row.enabled = False
            return

        # Increment uses
        async with db_session() as session:
            db_row = await session.get(InviteLink, row.id)
            if db_row:
                db_row.uses += 1

        # Assign role
        if row.role_id:
            role = guild.get_role(row.role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"Joined via invite {used_code}")
                except discord.HTTPException as exc:
                    log.warning("Could not assign invite role: %s", exc)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="invite-track",
        description="[Admin] Track an invite link and optionally assign a role on join.",
    )
    @app_commands.describe(
        code="Discord invite code (without discord.gg/)",
        role="Role to assign when someone joins with this link",
        max_uses="Max uses before expiry (-1 = unlimited)",
        expires_in="Duration before link expires (e.g. 7d, 24h)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def invite_track(
        self,
        interaction: discord.Interaction,
        code: str,
        role: Optional[discord.Role] = None,
        max_uses: int = -1,
        expires_in: Optional[str] = None,
    ) -> None:
        expires_at = None
        if expires_in:
            seconds = parse_duration(expires_in)
            if seconds > 0:
                expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)

        async with db_session() as session:
            existing = await session.scalar(
                select(InviteLink).where(
                    InviteLink.guild_id == interaction.guild_id,
                    InviteLink.code == code,
                )
            )
            if existing:
                existing.role_id = role.id if role else None
                existing.max_uses = max_uses
                existing.expires_at = expires_at
                existing.enabled = True
            else:
                session.add(
                    InviteLink(
                        guild_id=interaction.guild_id,
                        code=code,
                        creator_id=interaction.user.id,
                        role_id=role.id if role else None,
                        max_uses=max_uses,
                        expires_at=expires_at,
                    )
                )
        role_str = role.mention if role else "None"
        await interaction.response.send_message(
            f"✅ Tracking invite `{code}` → Role: {role_str}",
            ephemeral=True,
        )

    @app_commands.command(name="invite-list", description="List tracked invite links.")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(InviteLink).where(InviteLink.guild_id == interaction.guild_id)
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("No invite links tracked.", ephemeral=True)
            return
        embed = discord.Embed(title="🔗 Tracked Invite Links", color=0x5865F2)
        for row in items:
            role_str = f"<@&{row.role_id}>" if row.role_id else "None"
            embed.add_field(
                name=f"`{row.code}`",
                value=(
                    f"Role: {role_str} | Uses: {row.uses}/{row.max_uses} "
                    f"| Expires: {row.expires_at or 'Never'} | Active: {row.enabled}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="invite-delete",
        description="[Admin] Stop tracking an invite.",
    )
    @app_commands.describe(code="Invite code to stop tracking")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_delete(self, interaction: discord.Interaction, code: str) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(InviteLink).where(
                    InviteLink.guild_id == interaction.guild_id,
                    InviteLink.code == code,
                )
            )
            if row:
                await session.delete(row)
                await interaction.response.send_message(
                    f"✅ Stopped tracking invite `{code}`.", ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Not found.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InvitesCog(bot))
