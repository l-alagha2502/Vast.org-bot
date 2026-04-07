"""
Custom Commands — admins can create text or embed response commands.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import CustomCommand
from utils import db_session

log = logging.getLogger(__name__)


class CustomCommandsCog(commands.Cog, name="Custom Commands"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not content:
            return
        async with async_session() as session:
            row = await session.scalar(
                select(CustomCommand).where(
                    CustomCommand.guild_id == message.guild.id,
                    CustomCommand.trigger == content.lower(),
                )
            )
        if row is None:
            return
        if row.is_embed:
            color = int(row.embed_color.lstrip("#"), 16) if row.embed_color else 0x5865F2
            embed = discord.Embed(description=row.response, color=color)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send(row.response)

    @app_commands.command(
        name="cmd-create",
        description="[Admin] Create a custom command.",
    )
    @app_commands.describe(
        trigger="The command text users type",
        response="The bot's response",
        is_embed="Send response as an embed",
        embed_color="Hex color for the embed (e.g. #5865F2)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_create(
        self,
        interaction: discord.Interaction,
        trigger: str,
        response: str,
        is_embed: bool = False,
        embed_color: Optional[str] = None,
    ) -> None:
        async with db_session() as session:
            existing = await session.scalar(
                select(CustomCommand).where(
                    CustomCommand.guild_id == interaction.guild_id,
                    CustomCommand.trigger == trigger.lower(),
                )
            )
            if existing:
                existing.response = response
                existing.is_embed = is_embed
                existing.embed_color = embed_color
            else:
                session.add(
                    CustomCommand(
                        guild_id=interaction.guild_id,
                        trigger=trigger.lower(),
                        response=response,
                        is_embed=is_embed,
                        embed_color=embed_color,
                    )
                )
        await interaction.response.send_message(
            f"✅ Custom command `{trigger}` created/updated.", ephemeral=True
        )

    @app_commands.command(
        name="cmd-delete",
        description="[Admin] Delete a custom command.",
    )
    @app_commands.describe(trigger="The trigger to delete")
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_delete(
        self, interaction: discord.Interaction, trigger: str
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(CustomCommand).where(
                    CustomCommand.guild_id == interaction.guild_id,
                    CustomCommand.trigger == trigger.lower(),
                )
            )
            if row:
                await session.delete(row)
                await interaction.response.send_message(
                    f"✅ Custom command `{trigger}` deleted.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ No command with trigger `{trigger}` found.", ephemeral=True
                )

    @app_commands.command(
        name="cmd-list",
        description="List all custom commands.",
    )
    async def cmd_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(CustomCommand).where(
                    CustomCommand.guild_id == interaction.guild_id
                )
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message(
                "No custom commands configured.", ephemeral=True
            )
            return
        embed = discord.Embed(title="Custom Commands", color=0x5865F2)
        for row in items:
            embed.add_field(
                name=f"`{row.trigger}`",
                value=row.response[:80] + ("…" if len(row.response) > 80 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CustomCommandsCog(bot))
