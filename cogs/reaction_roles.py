"""
Reaction Roles — unlimited messages, unlimited roles per message.
"""

from __future__ import annotations

import logging
from typing import Union

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import ReactionRole
from utils import db_session

log = logging.getLogger(__name__)


class ReactionRolesCog(commands.Cog, name="Reaction Roles"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction(payload, add=False)

    async def _handle_reaction(
        self, payload: discord.RawReactionActionEvent, add: bool
    ) -> None:
        emoji = str(payload.emoji)
        async with async_session() as session:
            row = await session.scalar(
                select(ReactionRole).where(
                    ReactionRole.guild_id == payload.guild_id,
                    ReactionRole.message_id == payload.message_id,
                    ReactionRole.emoji == emoji,
                )
            )
        if row is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            return
        role = guild.get_role(row.role_id)
        if role is None:
            return
        try:
            if add:
                await member.add_roles(role, reason="Reaction Role")
            else:
                await member.remove_roles(role, reason="Reaction Role removed")
        except discord.HTTPException as exc:
            log.warning("Reaction role error: %s", exc)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="reaction-role-add",
        description="[Admin] Add a reaction role to a message.",
    )
    @app_commands.describe(
        channel="Channel containing the message",
        message_id="ID of the message",
        emoji="Emoji to react with",
        role="Role to assign",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def rr_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message_id: str,
        emoji: str,
        role: discord.Role,
    ) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
            return
        async with db_session() as session:
            existing = await session.scalar(
                select(ReactionRole).where(
                    ReactionRole.guild_id == interaction.guild_id,
                    ReactionRole.message_id == mid,
                    ReactionRole.emoji == emoji,
                )
            )
            if existing is None:
                session.add(
                    ReactionRole(
                        guild_id=interaction.guild_id,
                        channel_id=channel.id,
                        message_id=mid,
                        emoji=emoji,
                        role_id=role.id,
                    )
                )
        # Add the reaction to the message
        try:
            msg = await channel.fetch_message(mid)
            await msg.add_reaction(emoji)
        except discord.HTTPException as exc:
            log.warning("Could not add reaction: %s", exc)
        await interaction.response.send_message(
            f"✅ Reaction role added: {emoji} → {role.mention}", ephemeral=True
        )

    @app_commands.command(
        name="reaction-role-remove",
        description="[Admin] Remove a reaction role.",
    )
    @app_commands.describe(message_id="ID of the message", emoji="Emoji to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_remove(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji: str,
    ) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
            return
        async with db_session() as session:
            row = await session.scalar(
                select(ReactionRole).where(
                    ReactionRole.guild_id == interaction.guild_id,
                    ReactionRole.message_id == mid,
                    ReactionRole.emoji == emoji,
                )
            )
            if row:
                await session.delete(row)
        await interaction.response.send_message(
            f"✅ Reaction role for {emoji} on message {mid} removed.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRolesCog(bot))
