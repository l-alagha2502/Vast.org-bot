"""
MODULE 1 — Bot Identity & VIP Controls.

Commands
--------
/vip name <name>        — Change bot nickname in the guild
/vip status <type> <text> — Update bot presence
/vip avatar <url>       — Change bot avatar (requires bot owner)
/vip transfer <user>    — Transfer ownership to another user
"""

from __future__ import annotations

import io
import logging
from typing import Literal
from urllib.request import urlopen

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from config import BotConfig
from database.base import async_session
from database.models import BotIdentity

log = logging.getLogger(__name__)


class IdentityCog(commands.Cog, name="Identity"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_owner(self, user_id: int) -> bool:
        return user_id == BotConfig.OWNER_ID

    async def _get_identity(self, guild_id: int) -> BotIdentity:
        async with async_session() as session:
            row = await session.scalar(
                select(BotIdentity).where(BotIdentity.guild_id == guild_id)
            )
            if row is None:
                row = BotIdentity(guild_id=guild_id)
                session.add(row)
                await session.commit()
        return row

    # ------------------------------------------------------------------
    # /vip command group
    # ------------------------------------------------------------------

    vip = app_commands.Group(
        name="vip",
        description="Bot identity management (owner only)",
    )

    @vip.command(name="name", description="Set the bot's display name in this guild.")
    @app_commands.describe(name="New nickname for the bot")
    async def vip_name(self, interaction: discord.Interaction, name: str) -> None:
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Guild not found.", ephemeral=True)
            return
        me = guild.me
        await me.edit(nick=name)
        async with async_session() as session:
            row = await session.scalar(
                select(BotIdentity).where(BotIdentity.guild_id == guild.id)
            )
            if row is None:
                row = BotIdentity(guild_id=guild.id)
                session.add(row)
            row.bot_name = name
            await session.commit()
        await interaction.response.send_message(f"✅ Bot name set to **{name}**.", ephemeral=True)

    @vip.command(name="status", description="Update the bot's presence status.")
    @app_commands.describe(
        status_type="Activity type",
        text="Status text",
    )
    async def vip_status(
        self,
        interaction: discord.Interaction,
        status_type: Literal["playing", "watching", "listening"],
        text: str,
    ) -> None:
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        activity_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
        }
        activity = discord.Activity(
            type=activity_map[status_type], name=text
        )
        await self.bot.change_presence(activity=activity)
        # Persist
        async with async_session() as session:
            row = await session.scalar(
                select(BotIdentity).where(BotIdentity.guild_id == interaction.guild_id)
            )
            if row is None:
                row = BotIdentity(guild_id=interaction.guild_id)
                session.add(row)
            row.status_type = status_type
            row.status_text = text
            await session.commit()
        await interaction.response.send_message(
            f"✅ Status set to **{status_type} {text}**.", ephemeral=True
        )

    @vip.command(name="avatar", description="Change the bot's global avatar.")
    @app_commands.describe(url="Direct image URL")
    async def vip_avatar(self, interaction: discord.Interaction, url: str) -> None:
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            with urlopen(url, timeout=10) as resp:
                data = resp.read()
            await self.bot.user.edit(avatar=data)
            await interaction.followup.send("✅ Avatar updated.")
        except Exception as exc:
            log.error("Failed to update avatar: %s", exc)
            await interaction.followup.send(f"❌ Failed: {exc}")

    @vip.command(name="transfer", description="Transfer bot ownership to another user.")
    @app_commands.describe(user="New bot owner")
    async def vip_transfer(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        BotConfig.OWNER_ID = user.id  # update class-level value for this process lifetime
        async with async_session() as session:
            row = await session.scalar(
                select(BotIdentity).where(
                    BotIdentity.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = BotIdentity(guild_id=interaction.guild_id)
                session.add(row)
            row.owner_id = user.id
            await session.commit()
        await interaction.response.send_message(
            f"✅ Ownership transferred to {user.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(IdentityCog(bot))
