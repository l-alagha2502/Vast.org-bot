"""
Vast.org Bot — Main entry point.
Loads all cogs and connects to Discord.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import BotConfig
from database.base import init_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")


class VastBot(commands.Bot):
    """The central bot instance."""

    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(
            command_prefix=commands.when_mentioned_or(BotConfig.PREFIX),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.config = BotConfig

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        await init_db()
        await self._load_cogs()
        await self.tree.sync()
        log.info("Application commands synced.")

    async def _load_cogs(self) -> None:
        cog_modules = [
            "cogs.identity",
            "cogs.leveling",
            "cogs.moderation",
            "cogs.automations",
            "cogs.social_media",
            "cogs.music",
            "cogs.reaction_roles",
            "cogs.welcome",
            "cogs.birthdays",
            "cogs.timers",
            "cogs.tickets",
            "cogs.economy",
            "cogs.logs",
            "cogs.starboard",
            "cogs.custom_commands",
            "cogs.invites",
        ]
        for module in cog_modules:
            try:
                await self.load_extension(module)
                log.info("Loaded cog: %s", module)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", module, exc)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self._apply_presence()

    async def _apply_presence(self) -> None:
        """Set the bot status from config / database."""
        activity_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
        }
        activity_type = activity_map.get(
            BotConfig.STATUS_TYPE.lower(), discord.ActivityType.playing
        )
        activity = discord.Activity(
            type=activity_type,
            name=BotConfig.STATUS_TEXT,
        )
        await self.change_presence(activity=activity)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild: %s (ID: %s)", guild.name, guild.id)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        log.error("Command error in %s: %s", ctx.command, error)


async def main() -> None:
    bot = VastBot()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set.")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
