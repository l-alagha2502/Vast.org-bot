"""
MODULE 4 — Automations Engine (IFTTT-style).

Trigger events → action steps with variable interpolation.

Supported triggers
------------------
message_sent | message_deleted | message_edited | reaction_added |
reaction_removed | voice_join | voice_leave | button_click

Supported actions (per step)
-----------------------------
send_message | add_role | remove_role | delete_message |
send_dm | create_thread | move_user
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.base import async_session
from database.models import Automation
from utils import db_session, resolve_variables

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action executor
# ---------------------------------------------------------------------------


async def _execute_actions(
    guild: discord.Guild,
    actions: list[dict],
    context: dict[str, Any],
    trigger_message: Optional[discord.Message] = None,
    trigger_member: Optional[discord.Member] = None,
) -> None:
    for step in actions:
        action_type = step.get("type")
        params = step.get("params", {})

        def _resolve(val: str) -> str:
            return resolve_variables(val, **context)

        try:
            if action_type == "send_message":
                channel = guild.get_channel(int(params.get("channel_id", 0)))
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(_resolve(params.get("content", "")))

            elif action_type == "add_role":
                member = trigger_member or (
                    guild.get_member(int(params.get("user_id", 0)))
                )
                role = guild.get_role(int(params.get("role_id", 0)))
                if member and role:
                    await member.add_roles(role)

            elif action_type == "remove_role":
                member = trigger_member or (
                    guild.get_member(int(params.get("user_id", 0)))
                )
                role = guild.get_role(int(params.get("role_id", 0)))
                if member and role:
                    await member.remove_roles(role)

            elif action_type == "delete_message":
                if trigger_message:
                    await trigger_message.delete()

            elif action_type == "send_dm":
                target = trigger_member or (
                    guild.get_member(int(params.get("user_id", 0)))
                )
                if target:
                    try:
                        await target.send(_resolve(params.get("content", "")))
                    except discord.Forbidden:
                        pass

            elif action_type == "create_thread":
                if trigger_message:
                    await trigger_message.create_thread(
                        name=_resolve(params.get("name", "Thread")),
                        auto_archive_duration=int(params.get("auto_archive", 1440)),
                    )

            elif action_type == "move_user":
                member = trigger_member
                channel = guild.get_channel(int(params.get("channel_id", 0)))
                if member and channel and isinstance(channel, discord.VoiceChannel):
                    await member.move_to(channel)

        except Exception as exc:
            log.warning("Automation action '%s' failed: %s", action_type, exc)


# ---------------------------------------------------------------------------
# Filter matching
# ---------------------------------------------------------------------------


def _matches_filter(trigger_filter: Optional[dict], ctx: dict[str, Any]) -> bool:
    if not trigger_filter:
        return True
    for key, expected in trigger_filter.items():
        actual = ctx.get(key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class AutomationsCog(commands.Cog, name="Automations"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _fire(
        self,
        guild: discord.Guild,
        event: str,
        context: dict[str, Any],
        **kwargs,
    ) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(Automation).where(
                    Automation.guild_id == guild.id,
                    Automation.enabled == True,  # noqa: E712
                    Automation.trigger_event == event,
                )
            )
            for row in rows:
                trigger_filter = json.loads(row.trigger_filter_json or "{}")
                if not _matches_filter(trigger_filter, context):
                    continue
                actions = json.loads(row.actions_json or "[]")
                await _execute_actions(guild, actions, context, **kwargs)

    # ------------------------------------------------------------------
    # Discord Events → fire automations
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        ctx = {
            "channel_id": str(message.channel.id),
            "user_id": str(message.author.id),
            "content": message.content,
            "user": {
                "mention": message.author.mention,
                "name": message.author.display_name,
                "id": str(message.author.id),
            },
            "channel": {"name": message.channel.name, "id": str(message.channel.id)},
            "server": {"member_count": str(message.guild.member_count)},
        }
        await self._fire(
            message.guild,
            "message_sent",
            ctx,
            trigger_message=message,
            trigger_member=message.author
            if isinstance(message.author, discord.Member)
            else None,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild:
            return
        ctx = {
            "channel_id": str(message.channel.id),
            "user_id": str(message.author.id),
            "channel": {"name": message.channel.name},
        }
        await self._fire(message.guild, "message_deleted", ctx)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if not after.guild:
            return
        ctx = {
            "channel_id": str(after.channel.id),
            "user_id": str(after.author.id),
            "channel": {"name": after.channel.name},
        }
        await self._fire(after.guild, "message_edited", ctx, trigger_message=after)

    @commands.Cog.listener()
    async def on_reaction_add(
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        if not reaction.message.guild:
            return
        ctx = {
            "emoji": str(reaction.emoji),
            "message_id": str(reaction.message.id),
            "user_id": str(user.id),
        }
        await self._fire(
            reaction.message.guild,
            "reaction_added",
            ctx,
            trigger_member=user if isinstance(user, discord.Member) else None,
        )

    @commands.Cog.listener()
    async def on_reaction_remove(
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        if not reaction.message.guild:
            return
        ctx = {
            "emoji": str(reaction.emoji),
            "message_id": str(reaction.message.id),
            "user_id": str(user.id),
        }
        await self._fire(
            reaction.message.guild,
            "reaction_removed",
            ctx,
            trigger_member=user if isinstance(user, discord.Member) else None,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel is None and after.channel is not None:
            ctx = {
                "channel_id": str(after.channel.id),
                "user_id": str(member.id),
                "channel": {"name": after.channel.name},
                "user": {"mention": member.mention, "name": member.display_name},
                "server": {"member_count": str(member.guild.member_count)},
            }
            await self._fire(member.guild, "voice_join", ctx, trigger_member=member)
        elif before.channel is not None and after.channel is None:
            ctx = {
                "channel_id": str(before.channel.id),
                "user_id": str(member.id),
                "channel": {"name": before.channel.name},
            }
            await self._fire(member.guild, "voice_leave", ctx, trigger_member=member)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if (
            interaction.type != discord.InteractionType.component
            or not interaction.guild
        ):
            return
        ctx = {
            "custom_id": interaction.data.get("custom_id", ""),
            "user_id": str(interaction.user.id),
            "user": {
                "mention": interaction.user.mention,
                "name": interaction.user.display_name,
            },
        }
        await self._fire(
            interaction.guild,
            "button_click",
            ctx,
            trigger_member=interaction.user
            if isinstance(interaction.user, discord.Member)
            else None,
        )

    # ------------------------------------------------------------------
    # Management Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="automation-create",
        description="[Admin] Create a new automation rule.",
    )
    @app_commands.describe(
        name="Rule name",
        trigger_event="Event that fires the rule",
        actions_json='JSON array of action steps, e.g. [{"type":"send_message","params":{...}}]',
        trigger_filter_json="Optional JSON filter object",
    )
    @app_commands.default_permissions(administrator=True)
    async def automation_create(
        self,
        interaction: discord.Interaction,
        name: str,
        trigger_event: str,
        actions_json: str,
        trigger_filter_json: Optional[str] = None,
    ) -> None:
        try:
            json.loads(actions_json)
        except json.JSONDecodeError:
            await interaction.response.send_message("❌ Invalid actions JSON.", ephemeral=True)
            return
        async with db_session() as session:
            session.add(
                Automation(
                    guild_id=interaction.guild_id,
                    name=name,
                    trigger_event=trigger_event,
                    actions_json=actions_json,
                    trigger_filter_json=trigger_filter_json,
                )
            )
        await interaction.response.send_message(
            f"✅ Automation **{name}** created.", ephemeral=True
        )

    @app_commands.command(name="automation-list", description="List all automation rules.")
    @app_commands.default_permissions(manage_guild=True)
    async def automation_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(Automation).where(Automation.guild_id == interaction.guild_id)
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("No automations configured.", ephemeral=True)
            return
        embed = discord.Embed(title="Automations", color=0x5865F2)
        for row in items:
            embed.add_field(
                name=f"#{row.id} — {row.name}",
                value=f"Trigger: `{row.trigger_event}` | Enabled: {row.enabled}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="automation-toggle", description="[Admin] Enable/disable an automation.")
    @app_commands.describe(automation_id="ID of the automation")
    @app_commands.default_permissions(administrator=True)
    async def automation_toggle(
        self, interaction: discord.Interaction, automation_id: int
    ) -> None:
        async with db_session() as session:
            row = await session.get(Automation, automation_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Not found.", ephemeral=True)
                return
            row.enabled = not row.enabled
            state = "enabled" if row.enabled else "disabled"
        await interaction.response.send_message(
            f"✅ Automation #{automation_id} is now **{state}**.", ephemeral=True
        )

    @app_commands.command(name="automation-delete", description="[Admin] Delete an automation.")
    @app_commands.describe(automation_id="ID of the automation")
    @app_commands.default_permissions(administrator=True)
    async def automation_delete(
        self, interaction: discord.Interaction, automation_id: int
    ) -> None:
        async with db_session() as session:
            row = await session.get(Automation, automation_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Not found.", ephemeral=True)
                return
            await session.delete(row)
        await interaction.response.send_message(
            f"✅ Automation #{automation_id} deleted.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomationsCog(bot))
