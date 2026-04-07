"""
Support Tickets — button-click system that opens private staff channels.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import Ticket, TicketSettings
from utils import db_session

log = logging.getLogger(__name__)


class TicketButton(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="📩 Open Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:open",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        guild = interaction.guild
        async with async_session() as session:
            settings = await session.scalar(
                select(TicketSettings).where(
                    TicketSettings.guild_id == guild.id
                )
            )
        if settings is None:
            await interaction.response.send_message(
                "❌ Tickets are not configured.", ephemeral=True
            )
            return

        # Check for existing open ticket
        async with async_session() as session:
            existing = await session.scalar(
                select(Ticket).where(
                    Ticket.guild_id == guild.id,
                    Ticket.user_id == interaction.user.id,
                    Ticket.status == "open",
                )
            )
        if existing:
            await interaction.response.send_message(
                f"You already have an open ticket: <#{existing.channel_id}>",
                ephemeral=True,
            )
            return

        # Create private channel
        category = (
            guild.get_channel(settings.ticket_category_id)
            if settings.ticket_category_id
            else None
        )
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        if settings.support_role_id:
            support_role = guild.get_role(settings.support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
            reason="Support ticket",
        )

        async with db_session() as session:
            ticket = Ticket(
                guild_id=guild.id,
                user_id=interaction.user.id,
                channel_id=channel.id,
            )
            session.add(ticket)

        close_view = CloseTicketView()
        embed = discord.Embed(
            title="Support Ticket",
            description=f"Hello {interaction.user.mention}! Support staff will be with you shortly.\n\nClick **Close Ticket** when your issue is resolved.",
            color=0x5865F2,
        )
        await channel.send(embed=embed, view=close_view)
        await interaction.response.send_message(
            f"✅ Ticket created: {channel.mention}", ephemeral=True
        )


class CloseTicketView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        channel = interaction.channel
        async with db_session() as session:
            row = await session.scalar(
                select(Ticket).where(
                    Ticket.guild_id == interaction.guild_id,
                    Ticket.channel_id == channel.id,
                    Ticket.status == "open",
                )
            )
            if row:
                row.status = "closed"
                row.closed_at = datetime.datetime.utcnow()
        await interaction.response.send_message("🔒 Ticket closed. Channel will be deleted shortly.")
        await asyncio.sleep(5)
        try:
            await channel.delete(reason="Ticket closed")
        except discord.HTTPException:
            pass


class TicketsCog(commands.Cog, name="Tickets"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(TicketButton())
        bot.add_view(CloseTicketView())

    @app_commands.command(
        name="ticket-setup",
        description="[Admin] Set up the ticket panel.",
    )
    @app_commands.describe(
        channel="Channel to post the panel in",
        support_role="Role that can see tickets",
        category="Category to create ticket channels in",
    )
    @app_commands.default_permissions(administrator=True)
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        support_role: Optional[discord.Role] = None,
        category: Optional[discord.CategoryChannel] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(TicketSettings).where(
                    TicketSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = TicketSettings(guild_id=interaction.guild_id)
                session.add(row)
            if support_role:
                row.support_role_id = support_role.id
            if category:
                row.ticket_category_id = category.id
            row.panel_channel_id = channel.id

        # Post panel
        embed = discord.Embed(
            title="📩 Support Tickets",
            description="Click the button below to open a support ticket.",
            color=0x5865F2,
        )
        view = TicketButton()
        msg = await channel.send(embed=embed, view=view)

        async with db_session() as session:
            row = await session.scalar(
                select(TicketSettings).where(
                    TicketSettings.guild_id == interaction.guild_id
                )
            )
            if row:
                row.panel_message_id = msg.id

        await interaction.response.send_message(
            "✅ Ticket panel created.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
