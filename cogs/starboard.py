"""
Starboard — Hall of fame channel triggered by ⭐ reaction threshold.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import StarboardEntry, StarboardSettings
from utils import db_session

log = logging.getLogger(__name__)


async def _get_settings(guild_id: int) -> Optional[StarboardSettings]:
    async with async_session() as session:
        return await session.scalar(
            select(StarboardSettings).where(StarboardSettings.guild_id == guild_id)
        )


class StarboardCog(commands.Cog, name="Starboard"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._handle_reaction(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._handle_reaction(payload)

    async def _handle_reaction(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if not payload.guild_id:
            return
        settings = await _get_settings(payload.guild_id)
        if not settings or not settings.channel_id:
            return
        if str(payload.emoji) != settings.emoji:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        # Count emoji reactions
        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == settings.emoji:
                star_count = reaction.count
                break

        star_channel = guild.get_channel(settings.channel_id)
        if not isinstance(star_channel, discord.TextChannel):
            return

        async with db_session() as session:
            entry = await session.scalar(
                select(StarboardEntry).where(
                    StarboardEntry.guild_id == payload.guild_id,
                    StarboardEntry.original_message_id == payload.message_id,
                )
            )

            if star_count >= settings.threshold:
                embed = discord.Embed(
                    description=message.content or "",
                    color=0xFFD700,
                    timestamp=message.created_at,
                )
                embed.set_author(
                    name=message.author.display_name,
                    icon_url=message.author.display_avatar.url,
                )
                embed.add_field(
                    name="Source",
                    value=f"[Jump to message]({message.jump_url})",
                )
                if message.attachments:
                    embed.set_image(url=message.attachments[0].url)
                content = f"{settings.emoji} **{star_count}** | {channel.mention}"

                if entry is None:
                    star_msg = await star_channel.send(content=content, embed=embed)
                    session.add(
                        StarboardEntry(
                            guild_id=payload.guild_id,
                            original_message_id=payload.message_id,
                            star_message_id=star_msg.id,
                            star_count=star_count,
                        )
                    )
                else:
                    entry.star_count = star_count
                    # Update existing message
                    try:
                        star_msg = await star_channel.fetch_message(entry.star_message_id)
                        await star_msg.edit(content=content, embed=embed)
                    except discord.HTTPException:
                        pass
            elif entry and entry.star_message_id:
                # Below threshold — remove from starboard
                try:
                    star_msg = await star_channel.fetch_message(entry.star_message_id)
                    await star_msg.delete()
                except discord.HTTPException:
                    pass
                entry.star_message_id = None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="starboard-setup",
        description="[Admin] Configure the starboard.",
    )
    @app_commands.describe(
        channel="Starboard destination channel",
        threshold="Number of star reactions required",
        emoji="Emoji to use (default ⭐)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def starboard_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        threshold: int = 3,
        emoji: str = "⭐",
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(StarboardSettings).where(
                    StarboardSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = StarboardSettings(guild_id=interaction.guild_id)
                session.add(row)
            row.channel_id = channel.id
            row.threshold = threshold
            row.emoji = emoji
        await interaction.response.send_message(
            f"✅ Starboard set to {channel.mention} with threshold **{threshold}** {emoji}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StarboardCog(bot))
