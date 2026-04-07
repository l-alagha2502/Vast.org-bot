"""
Welcome & Goodbye module.

Generates high-quality banner images using Pillow.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import WelcomeSettings
from utils import db_session, resolve_variables
from utils.image_gen import generate_welcome_card

log = logging.getLogger(__name__)


class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_settings(self, guild_id: int) -> WelcomeSettings:
        async with async_session() as session:
            row = await session.scalar(
                select(WelcomeSettings).where(WelcomeSettings.guild_id == guild_id)
            )
            if row is None:
                row = WelcomeSettings(guild_id=guild_id)
                session.add(row)
                await session.commit()
        return row

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = await self._get_settings(member.guild.id)
        if not settings.welcome_channel_id:
            return
        channel = member.guild.get_channel(settings.welcome_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        ctx = {
            "user": {"mention": member.mention, "name": member.display_name},
            "server": {
                "name": member.guild.name,
                "member_count": str(member.guild.member_count),
            },
        }
        text = resolve_variables(
            settings.welcome_message or "Welcome {user.mention} to **{server.name}**!", **ctx
        )
        if settings.welcome_image_enabled:
            buf = generate_welcome_card(
                username=member.display_name,
                avatar_url=str(member.display_avatar.url),
                member_count=member.guild.member_count,
                guild_name=member.guild.name,
                background_url=settings.background_url,
                embed_color=settings.embed_color,
            )
            file = discord.File(buf, filename="welcome.png")
            await channel.send(text, file=file)
        else:
            await channel.send(text)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        settings = await self._get_settings(member.guild.id)
        if not settings.goodbye_channel_id:
            return
        channel = member.guild.get_channel(settings.goodbye_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        ctx = {
            "user": {"mention": member.mention, "name": member.display_name},
            "server": {"name": member.guild.name},
        }
        text = resolve_variables(
            settings.goodbye_message or "**{user.name}** has left the server.", **ctx
        )
        if settings.welcome_image_enabled:
            buf = generate_welcome_card(
                username=member.display_name,
                avatar_url=str(member.display_avatar.url),
                member_count=member.guild.member_count,
                guild_name=member.guild.name,
                background_url=settings.background_url,
                embed_color=settings.embed_color,
                goodbye=True,
            )
            file = discord.File(buf, filename="goodbye.png")
            await channel.send(text, file=file)
        else:
            await channel.send(text)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="welcome-setup",
        description="[Admin] Configure welcome and goodbye messages.",
    )
    @app_commands.describe(
        welcome_channel="Channel for welcome messages",
        goodbye_channel="Channel for goodbye messages",
        welcome_message="Welcome message (supports {user.mention}, {server.name})",
        goodbye_message="Goodbye message",
        image_enabled="Generate welcome/goodbye images",
        background_url="URL to a custom background image",
        embed_color="Hex embed color",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        welcome_channel: Optional[discord.TextChannel] = None,
        goodbye_channel: Optional[discord.TextChannel] = None,
        welcome_message: Optional[str] = None,
        goodbye_message: Optional[str] = None,
        image_enabled: Optional[bool] = None,
        background_url: Optional[str] = None,
        embed_color: Optional[str] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(WelcomeSettings).where(
                    WelcomeSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = WelcomeSettings(guild_id=interaction.guild_id)
                session.add(row)
            if welcome_channel:
                row.welcome_channel_id = welcome_channel.id
            if goodbye_channel:
                row.goodbye_channel_id = goodbye_channel.id
            if welcome_message:
                row.welcome_message = welcome_message
            if goodbye_message:
                row.goodbye_message = goodbye_message
            if image_enabled is not None:
                row.welcome_image_enabled = image_enabled
            if background_url:
                row.background_url = background_url
            if embed_color:
                row.embed_color = embed_color
        await interaction.response.send_message(
            "✅ Welcome/goodbye settings updated.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
