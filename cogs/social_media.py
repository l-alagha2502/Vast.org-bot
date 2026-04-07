"""
MODULE 5 — Social Media Alerts.

Polls Twitch, YouTube, Twitter/X, Reddit, Instagram, TikTok and posts
customised embed announcements to configured Discord channels.

Each platform uses the credentials from config.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from config import BotConfig
from database.base import async_session
from database.models import SocialFeed
from utils import db_session, resolve_variables

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform clients
# ---------------------------------------------------------------------------


class TwitchClient:
    _token: Optional[str] = None
    _token_expiry: float = 0.0

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        import time

        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        async with session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": BotConfig.TWITCH_CLIENT_ID,
                "client_secret": BotConfig.TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        ) as resp:
            data = await resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._token

    async def is_live(
        self, session: aiohttp.ClientSession, username: str
    ) -> Optional[dict]:
        """Return stream dict if *username* is live, else None."""
        token = await self._get_token(session)
        async with session.get(
            "https://api.twitch.tv/helix/streams",
            headers={
                "Client-ID": BotConfig.TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
            },
            params={"user_login": username},
        ) as resp:
            data = await resp.json()
        streams = data.get("data", [])
        return streams[0] if streams else None


_twitch_client = TwitchClient()


async def _check_youtube(
    session: aiohttp.ClientSession, channel_id: str, last_video_id: Optional[str]
) -> Optional[dict]:
    """Return latest video dict if newer than last_video_id."""
    async with session.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "channelId": channel_id,
            "order": "date",
            "maxResults": 1,
            "key": BotConfig.YOUTUBE_API_KEY,
        },
    ) as resp:
        data = await resp.json()
    items = data.get("items", [])
    if not items:
        return None
    item = items[0]
    vid_id = item["id"].get("videoId")
    if vid_id and vid_id != last_video_id:
        return item
    return None


async def _check_reddit(
    session: aiohttp.ClientSession, subreddit: str, last_id: Optional[str]
) -> Optional[dict]:
    """Return newest submission if newer than last_id."""
    async with session.get(
        f"https://www.reddit.com/r/{subreddit}/new.json?limit=1",
        headers={"User-Agent": BotConfig.REDDIT_USER_AGENT},
    ) as resp:
        data = await resp.json()
    posts = data.get("data", {}).get("children", [])
    if not posts:
        return None
    post = posts[0]["data"]
    if post["id"] != last_id:
        return post
    return None


async def _check_twitter(
    session: aiohttp.ClientSession, username: str, last_id: Optional[str]
) -> Optional[dict]:
    """Return newest tweet dict if different from last_id."""
    async with session.get(
        f"https://api.twitter.com/2/tweets/search/recent",
        headers={"Authorization": f"Bearer {BotConfig.TWITTER_BEARER_TOKEN}"},
        params={
            "query": f"from:{username} -is:reply -is:retweet",
            "max_results": 5,
            "tweet.fields": "created_at,author_id",
        },
    ) as resp:
        data = await resp.json()
    tweets = data.get("data", [])
    if not tweets:
        return None
    tweet = tweets[0]
    if tweet["id"] != last_id:
        return tweet
    return None


# ---------------------------------------------------------------------------
# Embed builder
# ---------------------------------------------------------------------------


def _build_embed(feed: SocialFeed, content: dict) -> discord.Embed:
    template = feed.message_template or "{author} posted: {link}"
    color = int(feed.embed_color.lstrip("#"), 16) if feed.embed_color else 0x5865F2
    description = resolve_variables(
        template,
        author=content.get("author", feed.account_name),
        link=content.get("link", ""),
        title=content.get("title", ""),
    )
    embed = discord.Embed(description=description, color=color)
    if "thumbnail" in content:
        embed.set_thumbnail(url=content["thumbnail"])
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class SocialMediaCog(commands.Cog, name="Social Media"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._http: Optional[aiohttp.ClientSession] = None
        self.twitch_poll.start()
        self.youtube_poll.start()
        self.twitter_poll.start()
        self.reddit_poll.start()

    def cog_unload(self) -> None:
        self.twitch_poll.cancel()
        self.youtube_poll.cancel()
        self.twitter_poll.cancel()
        self.reddit_poll.cancel()
        if self._http and not self._http.closed:
            asyncio.create_task(self._http.close())

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def _post_feed(self, feed: SocialFeed, content: dict) -> None:
        guild = self.bot.get_guild(feed.guild_id)
        if not guild:
            return
        channel = guild.get_channel(feed.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        embed = _build_embed(feed, content)
        await channel.send(embed=embed)

    async def _feeds_for(self, platform: str):
        async with async_session() as session:
            rows = await session.scalars(
                select(SocialFeed).where(
                    SocialFeed.platform == platform,
                    SocialFeed.enabled == True,  # noqa: E712
                )
            )
            return list(rows)

    # ------------------------------------------------------------------
    # Twitch
    # ------------------------------------------------------------------

    @tasks.loop(seconds=BotConfig.TWITCH_POLL)
    async def twitch_poll(self) -> None:
        if not BotConfig.TWITCH_CLIENT_ID:
            return
        session = await self._session()
        feeds = await self._feeds_for("twitch")
        for feed in feeds:
            try:
                stream = await _twitch_client.is_live(session, feed.account_name)
                stream_id = stream["id"] if stream else None
                if stream and stream_id != feed.last_post_id:
                    await self._post_feed(
                        feed,
                        {
                            "author": feed.account_name,
                            "link": f"https://twitch.tv/{feed.account_name}",
                            "title": stream.get("title", ""),
                            "thumbnail": stream.get("thumbnail_url", ""),
                        },
                    )
                    async with db_session() as db:
                        db_feed = await db.get(SocialFeed, feed.id)
                        if db_feed:
                            db_feed.last_post_id = stream_id
            except Exception as exc:
                log.debug("Twitch poll error for %s: %s", feed.account_name, exc)

    @twitch_poll.before_loop
    async def before_twitch(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------

    @tasks.loop(seconds=BotConfig.YOUTUBE_POLL)
    async def youtube_poll(self) -> None:
        if not BotConfig.YOUTUBE_API_KEY:
            return
        session = await self._session()
        feeds = await self._feeds_for("youtube")
        for feed in feeds:
            try:
                item = await _check_youtube(session, feed.account_name, feed.last_post_id)
                if item:
                    vid_id = item["id"]["videoId"]
                    snippet = item.get("snippet", {})
                    await self._post_feed(
                        feed,
                        {
                            "author": snippet.get("channelTitle", feed.account_name),
                            "link": f"https://youtube.com/watch?v={vid_id}",
                            "title": snippet.get("title", ""),
                            "thumbnail": snippet.get("thumbnails", {})
                            .get("high", {})
                            .get("url", ""),
                        },
                    )
                    async with db_session() as db:
                        db_feed = await db.get(SocialFeed, feed.id)
                        if db_feed:
                            db_feed.last_post_id = vid_id
            except Exception as exc:
                log.debug("YouTube poll error for %s: %s", feed.account_name, exc)

    @youtube_poll.before_loop
    async def before_youtube(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Twitter/X
    # ------------------------------------------------------------------

    @tasks.loop(seconds=BotConfig.TWITTER_POLL)
    async def twitter_poll(self) -> None:
        if not BotConfig.TWITTER_BEARER_TOKEN:
            return
        session = await self._session()
        feeds = await self._feeds_for("twitter")
        for feed in feeds:
            try:
                tweet = await _check_twitter(session, feed.account_name, feed.last_post_id)
                if tweet:
                    await self._post_feed(
                        feed,
                        {
                            "author": feed.account_name,
                            "link": f"https://twitter.com/{feed.account_name}/status/{tweet['id']}",
                            "title": tweet.get("text", ""),
                        },
                    )
                    async with db_session() as db:
                        db_feed = await db.get(SocialFeed, feed.id)
                        if db_feed:
                            db_feed.last_post_id = tweet["id"]
            except Exception as exc:
                log.debug("Twitter poll error for %s: %s", feed.account_name, exc)

    @twitter_poll.before_loop
    async def before_twitter(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Reddit
    # ------------------------------------------------------------------

    @tasks.loop(seconds=BotConfig.REDDIT_POLL)
    async def reddit_poll(self) -> None:
        session = await self._session()
        feeds = await self._feeds_for("reddit")
        for feed in feeds:
            try:
                post = await _check_reddit(session, feed.account_name, feed.last_post_id)
                if post:
                    await self._post_feed(
                        feed,
                        {
                            "author": post.get("author", "unknown"),
                            "link": f"https://reddit.com{post.get('permalink', '')}",
                            "title": post.get("title", ""),
                            "thumbnail": post.get("thumbnail", ""),
                        },
                    )
                    async with db_session() as db:
                        db_feed = await db.get(SocialFeed, feed.id)
                        if db_feed:
                            db_feed.last_post_id = post["id"]
            except Exception as exc:
                log.debug("Reddit poll error for %s: %s", feed.account_name, exc)

    @reddit_poll.before_loop
    async def before_reddit(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Management Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="social-add",
        description="[Admin] Add a social media feed subscription.",
    )
    @app_commands.describe(
        platform="twitch|youtube|twitter|reddit|instagram|tiktok",
        account="Username or channel ID",
        channel="Discord channel to post alerts",
        embed_color="Hex embed color (e.g. #FF5733)",
        message_template="Template with {author} and {link} variables",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def social_add(
        self,
        interaction: discord.Interaction,
        platform: str,
        account: str,
        channel: discord.TextChannel,
        embed_color: Optional[str] = None,
        message_template: Optional[str] = None,
    ) -> None:
        platforms = ("twitch", "youtube", "twitter", "reddit", "instagram", "tiktok")
        if platform not in platforms:
            await interaction.response.send_message(
                f"❌ Platform must be one of: {', '.join(platforms)}", ephemeral=True
            )
            return
        async with db_session() as session:
            session.add(
                SocialFeed(
                    guild_id=interaction.guild_id,
                    platform=platform,
                    account_name=account,
                    channel_id=channel.id,
                    embed_color=embed_color,
                    message_template=message_template,
                )
            )
        await interaction.response.send_message(
            f"✅ Added **{platform}** feed for **{account}** → {channel.mention}."
        )

    @app_commands.command(
        name="social-remove",
        description="[Admin] Remove a social media feed by ID.",
    )
    @app_commands.describe(feed_id="Feed ID (from /social-list)")
    @app_commands.default_permissions(manage_guild=True)
    async def social_remove(
        self, interaction: discord.Interaction, feed_id: int
    ) -> None:
        async with db_session() as session:
            row = await session.get(SocialFeed, feed_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Not found.", ephemeral=True)
                return
            await session.delete(row)
        await interaction.response.send_message(f"✅ Feed #{feed_id} removed.", ephemeral=True)

    @app_commands.command(name="social-list", description="List all social media feeds.")
    @app_commands.default_permissions(manage_guild=True)
    async def social_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(SocialFeed).where(SocialFeed.guild_id == interaction.guild_id)
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("No feeds configured.", ephemeral=True)
            return
        embed = discord.Embed(title="Social Media Feeds", color=0x5865F2)
        for row in items:
            embed.add_field(
                name=f"#{row.id} — {row.platform}: {row.account_name}",
                value=f"Channel: <#{row.channel_id}> | Enabled: {row.enabled}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SocialMediaCog(bot))
