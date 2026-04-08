"""
Birthdays — auto-wish and assign a temporary Birthday Role for 24 hours.
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
from database.models import Birthday, BirthdaySettings
from utils import db_session

log = logging.getLogger(__name__)


class BirthdaysCog(commands.Cog, name="Birthdays"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.birthday_check.start()

    def cog_unload(self) -> None:
        self.birthday_check.cancel()

    @tasks.loop(hours=1)
    async def birthday_check(self) -> None:
        now = datetime.datetime.utcnow()
        today_month = now.month
        today_day = now.day

        async with async_session() as session:
            birthdays = await session.scalars(
                select(Birthday).where(
                    Birthday.birthday_month == today_month,
                    Birthday.birthday_day == today_day,
                )
            )
            for bday in birthdays:
                guild = self.bot.get_guild(bday.guild_id)
                if guild is None:
                    continue
                member = guild.get_member(bday.user_id)
                if member is None:
                    continue

                # Fetch guild settings
                settings = await session.scalar(
                    select(BirthdaySettings).where(
                        BirthdaySettings.guild_id == bday.guild_id
                    )
                )
                if settings is None:
                    continue

                # Send birthday message
                if settings.birthday_channel_id:
                    channel = guild.get_channel(settings.birthday_channel_id)
                    if isinstance(channel, discord.TextChannel):
                        msg = settings.birthday_message or "🎂 Happy Birthday {user.mention}!"
                        await channel.send(msg.replace("{user.mention}", member.mention))

                # Assign birthday role
                if settings.birthday_role_id and not bday.birthday_role_active:
                    role = guild.get_role(settings.birthday_role_id)
                    if role:
                        try:
                            await member.add_roles(role, reason="Birthday!")
                            bday.birthday_role_active = True
                        except discord.HTTPException:
                            pass

            await session.commit()

        # Remove birthday roles that are no longer today
        async with async_session() as session:
            active = await session.scalars(
                select(Birthday).where(Birthday.birthday_role_active == True)  # noqa: E712
            )
            for bday in active:
                if bday.birthday_month == today_month and bday.birthday_day == today_day:
                    continue  # still their birthday
                guild = self.bot.get_guild(bday.guild_id)
                if guild is None:
                    continue
                member = guild.get_member(bday.user_id)
                if member is None:
                    continue
                settings = await session.scalar(
                    select(BirthdaySettings).where(
                        BirthdaySettings.guild_id == bday.guild_id
                    )
                )
                if settings and settings.birthday_role_id:
                    role = guild.get_role(settings.birthday_role_id)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Birthday over")
                        except discord.HTTPException:
                            pass
                bday.birthday_role_active = False
            await session.commit()

    @birthday_check.before_loop
    async def before_birthday(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(name="birthday-set", description="Set your birthday.")
    @app_commands.describe(month="Month (1–12)", day="Day (1–31)")
    async def birthday_set(
        self, interaction: discord.Interaction, month: int, day: int
    ) -> None:
        if not (1 <= month <= 12) or not (1 <= day <= 31):
            await interaction.response.send_message("❌ Invalid date.", ephemeral=True)
            return
        async with db_session() as session:
            row = await session.scalar(
                select(Birthday).where(
                    Birthday.guild_id == interaction.guild_id,
                    Birthday.user_id == interaction.user.id,
                )
            )
            if row is None:
                row = Birthday(
                    guild_id=interaction.guild_id, user_id=interaction.user.id
                )
                session.add(row)
            row.birthday_month = month
            row.birthday_day = day
        await interaction.response.send_message(
            f"✅ Birthday set to **{month}/{day}**.", ephemeral=True
        )

    @app_commands.command(
        name="birthday-setup",
        description="[Admin] Configure birthday announcements.",
    )
    @app_commands.describe(
        channel="Birthday announcement channel",
        role="Temporary birthday role",
        message="Birthday message (supports {user.mention})",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_setup(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        role: Optional[discord.Role] = None,
        message: Optional[str] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(BirthdaySettings).where(
                    BirthdaySettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = BirthdaySettings(guild_id=interaction.guild_id)
                session.add(row)
            if channel:
                row.birthday_channel_id = channel.id
            if role:
                row.birthday_role_id = role.id
            if message:
                row.birthday_message = message
        await interaction.response.send_message(
            "✅ Birthday settings updated.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BirthdaysCog(bot))
