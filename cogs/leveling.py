"""
MODULE 2 — Advanced Leveling & Engagement.

Features
--------
* Dual XP tracking (text + voice)
* XP cooldown (configurable per config.py)
* Role-specific XP multipliers + global 50 % boost toggle
* Level role rewards
* Channel/role XP blacklists
* Custom rank & profile cards (Pillow)
* Voice Online Counter channel
* /rank, /profile, /levels, /give-xp, /xp-settings
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, func

from config import BotConfig
from database.base import async_session
from database.models import (
    LevelRoleReward,
    UserLevel,
    XpBlacklist,
    XpMultiplier,
    XpSettings,
)
from utils import db_session, level_from_xp, xp_for_level
from utils.image_gen import generate_rank_card

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_settings(guild_id: int) -> XpSettings:
    async with async_session() as session:
        row = await session.scalar(
            select(XpSettings).where(XpSettings.guild_id == guild_id)
        )
        if row is None:
            row = XpSettings(guild_id=guild_id)
            session.add(row)
            await session.commit()
    return row


async def _get_user_level(guild_id: int, user_id: int) -> UserLevel:
    async with async_session() as session:
        row = await session.scalar(
            select(UserLevel).where(
                UserLevel.guild_id == guild_id, UserLevel.user_id == user_id
            )
        )
        if row is None:
            row = UserLevel(guild_id=guild_id, user_id=user_id)
            session.add(row)
            await session.commit()
    return row


async def _compute_multiplier(guild_id: int, member: discord.Member) -> float:
    """Returns the effective XP multiplier for *member* in *guild_id*."""
    settings = await _get_settings(guild_id)
    base = settings.global_boost_multiplier if settings.global_boost_enabled else 1.0

    role_ids = {r.id for r in member.roles}
    async with async_session() as session:
        rows = await session.scalars(
            select(XpMultiplier).where(XpMultiplier.guild_id == guild_id)
        )
        best = 1.0
        for row in rows:
            if row.role_id in role_ids:
                best = max(best, row.multiplier)
    return base * best


async def _is_blacklisted(guild_id: int, channel_id: int, role_ids: set[int]) -> bool:
    async with async_session() as session:
        rows = await session.scalars(
            select(XpBlacklist).where(XpBlacklist.guild_id == guild_id)
        )
        for row in rows:
            if row.target_type == "channel" and row.target_id == channel_id:
                return True
            if row.target_type == "role" and row.target_id in role_ids:
                return True
    return False


async def _check_level_up(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    old_level: int,
    new_level: int,
) -> None:
    if new_level <= old_level:
        return
    guild = bot.get_guild(guild_id)
    if guild is None:
        return
    member = guild.get_member(user_id)
    if member is None:
        return

    # Assign role rewards for every level between old_level+1 … new_level
    async with async_session() as session:
        rewards = await session.scalars(
            select(LevelRoleReward).where(
                LevelRoleReward.guild_id == guild_id,
                LevelRoleReward.level <= new_level,
                LevelRoleReward.level > old_level,
            )
        )
        for reward in rewards:
            role = guild.get_role(reward.role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Level {reward.level} reward")
                except discord.HTTPException as exc:
                    log.warning("Could not assign level role: %s", exc)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class LevelingCog(commands.Cog, name="Leveling"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> {user_id -> last_xp_timestamp}
        self._text_cooldowns: dict[int, dict[int, datetime.datetime]] = {}
        self._voice_tracking: dict[int, dict[int, datetime.datetime]] = {}
        self.voice_xp_loop.start()
        self.update_voice_counter.start()

    def cog_unload(self) -> None:
        self.voice_xp_loop.cancel()
        self.update_voice_counter.cancel()

    # ------------------------------------------------------------------
    # Text XP
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        # Blacklist check
        role_ids = {r.id for r in message.author.roles}
        if await _is_blacklisted(guild_id, message.channel.id, role_ids):
            return

        # Cooldown check
        now = datetime.datetime.utcnow()
        cooldowns = self._text_cooldowns.setdefault(guild_id, {})
        last = cooldowns.get(user_id)
        if last and (now - last).total_seconds() < BotConfig.TEXT_XP_COOLDOWN:
            return
        cooldowns[user_id] = now

        multiplier = await _compute_multiplier(guild_id, message.author)
        raw_xp = random.randint(BotConfig.TEXT_XP_MIN, BotConfig.TEXT_XP_MAX)
        xp_gain = int(raw_xp * multiplier)

        async with db_session() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.guild_id == guild_id, UserLevel.user_id == user_id
                )
            )
            if row is None:
                row = UserLevel(guild_id=guild_id, user_id=user_id)
                session.add(row)
            old_level = row.text_level
            row.text_xp += xp_gain
            row.last_text_xp_at = now
            new_level = level_from_xp(row.text_xp)
            row.text_level = new_level

        await _check_level_up(self.bot, guild_id, user_id, old_level, new_level)

    # ------------------------------------------------------------------
    # Voice XP — track joins/leaves to accumulate session minutes
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        guild_id = member.guild.id
        user_id = member.id
        tracking = self._voice_tracking.setdefault(guild_id, {})
        now = datetime.datetime.utcnow()

        if before.channel is None and after.channel is not None:
            # Joined voice
            tracking[user_id] = now
        elif before.channel is not None and after.channel is None:
            # Left voice — award accumulated XP
            if user_id in tracking:
                elapsed = (now - tracking.pop(user_id)).total_seconds() / 60.0
                await self._award_voice_xp(guild_id, member, elapsed)

    async def _award_voice_xp(
        self, guild_id: int, member: discord.Member, minutes: float
    ) -> None:
        if minutes <= 0:
            return
        multiplier = await _compute_multiplier(guild_id, member)
        xp_gain = int(BotConfig.VOICE_XP_RATE * minutes * multiplier)
        if xp_gain <= 0:
            return
        async with db_session() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.guild_id == guild_id, UserLevel.user_id == member.id
                )
            )
            if row is None:
                row = UserLevel(guild_id=guild_id, user_id=member.id)
                session.add(row)
            old_level = row.voice_level
            row.voice_xp += xp_gain
            new_level = level_from_xp(row.voice_xp)
            row.voice_level = new_level
        await _check_level_up(self.bot, guild_id, member.id, old_level, new_level)

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self) -> None:
        """Every minute award XP for all currently-in-voice users."""
        now = datetime.datetime.utcnow()
        for guild_id, tracking in self._voice_tracking.items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            for user_id, joined_at in list(tracking.items()):
                member = guild.get_member(user_id)
                if member is None:
                    continue
                elapsed_min = (now - joined_at).total_seconds() / 60.0
                if elapsed_min >= 1:
                    tracking[user_id] = now
                    await self._award_voice_xp(guild_id, member, elapsed_min)

    @voice_xp_loop.before_loop
    async def before_voice_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Voice Online Counter
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def update_voice_counter(self) -> None:
        for guild in self.bot.guilds:
            settings = await _get_settings(guild.id)
            if not settings.voice_counter_channel_id:
                continue
            channel = guild.get_channel(settings.voice_counter_channel_id)
            if channel is None:
                continue
            count = sum(
                1
                for vc in guild.voice_channels
                for m in vc.members
                if not m.bot
            )
            new_name = f"🎤 In Voice: {count}"
            if channel.name != new_name:
                try:
                    await channel.edit(name=new_name)
                except discord.HTTPException:
                    pass

    @update_voice_counter.before_loop
    async def before_counter_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Slash Commands
    # ------------------------------------------------------------------

    @app_commands.command(name="rank", description="View your rank card or another user's.")
    @app_commands.describe(user="The user to check (defaults to you)")
    async def rank(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("❌ Could not find member.", ephemeral=True)
            return
        await interaction.response.defer()

        row = await _get_user_level(interaction.guild_id, target.id)

        # Global rank by text XP
        async with async_session() as session:
            count = await session.scalar(
                select(func.count()).select_from(UserLevel).where(
                    UserLevel.guild_id == interaction.guild_id,
                    UserLevel.text_xp > row.text_xp,
                )
            )
        rank_pos = (count or 0) + 1

        total_xp = row.text_xp
        current_level = row.text_level
        xp_needed = xp_for_level(current_level + 1) - xp_for_level(current_level)
        xp_in_level = total_xp - xp_for_level(current_level)

        buf = generate_rank_card(
            username=target.display_name,
            discriminator=getattr(target, "discriminator", "0"),
            avatar_url=str(target.display_avatar.url),
            level=current_level,
            current_xp=xp_in_level,
            required_xp=xp_needed,
            rank=rank_pos,
            bar_color=row.bar_color,
            text_color=row.text_color,
            background_url=row.background_url,
        )

        file = discord.File(buf, filename="rank.png")
        await interaction.followup.send(file=file)

    @app_commands.command(name="profile", description="View or update your rank card profile.")
    async def profile(self, interaction: discord.Interaction) -> None:
        row = await _get_user_level(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Profile",
            color=int(row.bar_color.lstrip("#"), 16),
        )
        embed.add_field(name="Text XP", value=f"{row.text_xp:,}", inline=True)
        embed.add_field(name="Text Level", value=str(row.text_level), inline=True)
        embed.add_field(name="Voice XP", value=f"{row.voice_xp:,}", inline=True)
        embed.add_field(name="Voice Level", value=str(row.voice_level), inline=True)
        embed.add_field(name="Bar Color", value=row.bar_color, inline=True)
        embed.add_field(name="Text Color", value=row.text_color, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="levels", description="View the server leaderboard link.")
    async def levels(self, interaction: discord.Interaction) -> None:
        url = f"{BotConfig.LEADERBOARD_BASE_URL}/{interaction.guild_id}"
        embed = discord.Embed(
            title="🏆 Server Leaderboard",
            description=f"[Click here to view the full leaderboard!]({url})",
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give-xp", description="[Admin] Give XP to a user.")
    @app_commands.describe(user="Target user", amount="XP to give")
    @app_commands.default_permissions(administrator=True)
    async def give_xp(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ) -> None:
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        async with db_session() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.guild_id == interaction.guild_id,
                    UserLevel.user_id == user.id,
                )
            )
            if row is None:
                row = UserLevel(guild_id=interaction.guild_id, user_id=user.id)
                session.add(row)
            old_level = row.text_level
            row.text_xp += amount
            row.text_level = level_from_xp(row.text_xp)
        await _check_level_up(self.bot, interaction.guild_id, user.id, old_level, row.text_level)
        await interaction.response.send_message(
            f"✅ Gave **{amount:,} XP** to {user.mention}."
        )

    @app_commands.command(name="xp-settings", description="[Admin] Configure XP settings.")
    @app_commands.describe(
        global_boost="Enable global 50% XP boost",
        voice_counter_channel="Channel to display voice user count",
    )
    @app_commands.default_permissions(administrator=True)
    async def xp_settings(
        self,
        interaction: discord.Interaction,
        global_boost: Optional[bool] = None,
        voice_counter_channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(XpSettings).where(XpSettings.guild_id == interaction.guild_id)
            )
            if row is None:
                row = XpSettings(guild_id=interaction.guild_id)
                session.add(row)
            if global_boost is not None:
                row.global_boost_enabled = global_boost
            if voice_counter_channel is not None:
                row.voice_counter_channel_id = voice_counter_channel.id
        await interaction.response.send_message("✅ XP settings updated.", ephemeral=True)

    @app_commands.command(name="xp-multiplier", description="[Admin] Set a role XP multiplier.")
    @app_commands.describe(role="Target role", multiplier="e.g. 2.0 for 2x")
    @app_commands.default_permissions(administrator=True)
    async def xp_multiplier(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        multiplier: float,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(XpMultiplier).where(
                    XpMultiplier.guild_id == interaction.guild_id,
                    XpMultiplier.role_id == role.id,
                )
            )
            if row is None:
                row = XpMultiplier(guild_id=interaction.guild_id, role_id=role.id)
                session.add(row)
            row.multiplier = multiplier
        await interaction.response.send_message(
            f"✅ Set **{multiplier}x** XP multiplier for {role.mention}."
        )

    @app_commands.command(name="xp-blacklist", description="[Admin] Blacklist a channel or role from XP.")
    @app_commands.describe(target_type="channel or role", target_id="ID of the channel/role")
    @app_commands.default_permissions(administrator=True)
    async def xp_blacklist(
        self,
        interaction: discord.Interaction,
        target_type: str,
        target_id: str,
    ) -> None:
        if target_type not in ("channel", "role"):
            await interaction.response.send_message("❌ target_type must be 'channel' or 'role'.", ephemeral=True)
            return
        try:
            tid = int(target_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid ID.", ephemeral=True)
            return
        async with db_session() as session:
            existing = await session.scalar(
                select(XpBlacklist).where(
                    XpBlacklist.guild_id == interaction.guild_id,
                    XpBlacklist.target_id == tid,
                    XpBlacklist.target_type == target_type,
                )
            )
            if existing is None:
                session.add(
                    XpBlacklist(
                        guild_id=interaction.guild_id,
                        target_id=tid,
                        target_type=target_type,
                    )
                )
        await interaction.response.send_message(
            f"✅ Blacklisted {target_type} `{tid}` from XP gain."
        )

    @app_commands.command(name="level-reward", description="[Admin] Set a role reward for a level.")
    @app_commands.describe(level="Level to trigger reward", role="Role to assign")
    @app_commands.default_permissions(administrator=True)
    async def level_reward(
        self,
        interaction: discord.Interaction,
        level: int,
        role: discord.Role,
    ) -> None:
        async with db_session() as session:
            existing = await session.scalar(
                select(LevelRoleReward).where(
                    LevelRoleReward.guild_id == interaction.guild_id,
                    LevelRoleReward.level == level,
                    LevelRoleReward.role_id == role.id,
                )
            )
            if existing is None:
                session.add(
                    LevelRoleReward(
                        guild_id=interaction.guild_id,
                        level=level,
                        role_id=role.id,
                    )
                )
        await interaction.response.send_message(
            f"✅ Users reaching level **{level}** will receive {role.mention}."
        )

    @app_commands.command(
        name="profile-style",
        description="Customize your rank card bar/text color and background.",
    )
    @app_commands.describe(
        bar_color="Hex color for the XP bar (e.g. #FF5733)",
        text_color="Hex color for the text (e.g. #FFFFFF)",
        background_url="Direct URL to a background image",
    )
    async def profile_style(
        self,
        interaction: discord.Interaction,
        bar_color: Optional[str] = None,
        text_color: Optional[str] = None,
        background_url: Optional[str] = None,
    ) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.guild_id == interaction.guild_id,
                    UserLevel.user_id == interaction.user.id,
                )
            )
            if row is None:
                row = UserLevel(guild_id=interaction.guild_id, user_id=interaction.user.id)
                session.add(row)
            if bar_color:
                row.bar_color = bar_color
            if text_color:
                row.text_color = text_color
            if background_url:
                row.background_url = background_url
        await interaction.response.send_message("✅ Profile style updated.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LevelingCog(bot))
