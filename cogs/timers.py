"""
Recurring Timers — automated messages at configurable intervals.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from database.base import async_session
from database.models import Timer
from utils import db_session, parse_duration

log = logging.getLogger(__name__)


class TimersCog(commands.Cog, name="Timers"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.timer_loop.start()

    def cog_unload(self) -> None:
        self.timer_loop.cancel()

    @tasks.loop(seconds=30)
    async def timer_loop(self) -> None:
        now = datetime.datetime.utcnow()
        async with async_session() as session:
            rows = await session.scalars(
                select(Timer).where(
                    Timer.enabled == True,  # noqa: E712
                    Timer.next_run_at <= now,
                )
            )
            due: list[Timer] = list(rows)

        for timer in due:
            guild = self.bot.get_guild(timer.guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(timer.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(timer.message)
                except discord.HTTPException as exc:
                    log.warning("Timer send failed: %s", exc)
            # Schedule next run
            async with db_session() as session:
                row = await session.get(Timer, timer.id)
                if row:
                    row.next_run_at = now + datetime.timedelta(
                        seconds=row.interval_seconds
                    )

    @timer_loop.before_loop
    async def before_timer(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(name="timer-create", description="[Admin] Create a recurring message timer.")
    @app_commands.describe(
        channel="Channel to send the message",
        interval="Interval duration (e.g. 6h, 1d)",
        message="Message to send",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def timer_create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        interval: str,
        message: str,
    ) -> None:
        seconds = parse_duration(interval)
        if seconds <= 0:
            await interaction.response.send_message("❌ Invalid interval.", ephemeral=True)
            return
        next_run = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
        async with db_session() as session:
            session.add(
                Timer(
                    guild_id=interaction.guild_id,
                    channel_id=channel.id,
                    message=message,
                    interval_seconds=seconds,
                    next_run_at=next_run,
                )
            )
        await interaction.response.send_message(
            f"✅ Timer created — will post every **{interval}** in {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="timer-list", description="List all timers.")
    @app_commands.default_permissions(manage_guild=True)
    async def timer_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(Timer).where(Timer.guild_id == interaction.guild_id)
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("No timers configured.", ephemeral=True)
            return
        embed = discord.Embed(title="⏱️ Timers", color=0x5865F2)
        for row in items:
            embed.add_field(
                name=f"#{row.id} — <#{row.channel_id}>",
                value=f"Every {row.interval_seconds}s | Enabled: {row.enabled}\n{row.message[:50]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="timer-delete", description="[Admin] Delete a timer.")
    @app_commands.describe(timer_id="ID of the timer to delete")
    @app_commands.default_permissions(manage_guild=True)
    async def timer_delete(self, interaction: discord.Interaction, timer_id: int) -> None:
        async with db_session() as session:
            row = await session.get(Timer, timer_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Not found.", ephemeral=True)
                return
            await session.delete(row)
        await interaction.response.send_message(
            f"✅ Timer #{timer_id} deleted.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimersCog(bot))
