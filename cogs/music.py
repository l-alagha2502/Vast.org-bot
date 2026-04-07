"""
MODULE 6 — Music & Audio Pro.

Uses wavelink 3 (Lavalink backend).

Features
---------
* /play /pause /resume /stop /skip /seek /loop /volume /queue /nowplaying
* 24/7 mode (stay in VC even when empty)
* Percentage-based vote-skip
* Saved personal playlists (/playlist-save, /playlist-load, /playlist-list)
* /record — records VC audio and sends MP3 (requires discord.py voice recording)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from typing import Literal, Optional

import discord
import wavelink
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from config import BotConfig
from database.base import async_session
from database.models import MusicSettings, SavedPlaylist
from utils import db_session, parse_duration

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_player(
    interaction: discord.Interaction,
) -> Optional[wavelink.Player]:
    """Return the guild's active player or None if not in a VC."""
    guild = interaction.guild
    if guild is None:
        return None
    return guild.voice_client  # type: ignore[return-value]


async def _ensure_voice(
    interaction: discord.Interaction,
) -> Optional[wavelink.Player]:
    """Connect to user's VC if needed; return the Player."""
    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.response.send_message(
            "❌ You must be in a voice channel.", ephemeral=True
        )
        return None
    player = await _get_player(interaction)
    if player is None:
        player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
    return player


async def _get_settings(guild_id: int) -> MusicSettings:
    async with async_session() as session:
        row = await session.scalar(
            select(MusicSettings).where(MusicSettings.guild_id == guild_id)
        )
        if row is None:
            row = MusicSettings(guild_id=guild_id)
            session.add(row)
            await session.commit()
    return row


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class MusicCog(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._vote_skips: dict[int, set[int]] = {}  # guild_id -> set of user_ids
        self._recordings: dict[int, discord.sinks.WaveSink] = {}

    async def cog_load(self) -> None:
        if BotConfig.LAVALINK_HOST:
            node = wavelink.Node(
                uri=f"http://{BotConfig.LAVALINK_HOST}:{BotConfig.LAVALINK_PORT}",
                password=BotConfig.LAVALINK_PASSWORD,
            )
            try:
                await wavelink.Pool.connect(nodes=[node], client=self.bot)
                log.info("Connected to Lavalink node.")
            except Exception as exc:
                log.warning("Could not connect to Lavalink: %s", exc)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ) -> None:
        player = payload.player
        if player and player.queue:
            await player.play(player.queue.get())

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Disconnect or stay based on 24/7 setting."""
        if member.bot:
            return
        guild = member.guild
        player: Optional[wavelink.Player] = guild.voice_client  # type: ignore
        if player is None or player.channel is None:
            return
        # If channel is now empty (only bot)
        if len([m for m in player.channel.members if not m.bot]) == 0:
            settings = await _get_settings(guild.id)
            if not settings.stay_247:
                await asyncio.sleep(30)
                # Re-check
                if len([m for m in player.channel.members if not m.bot]) == 0:
                    await player.disconnect()

    # ------------------------------------------------------------------
    # /play
    # ------------------------------------------------------------------

    @app_commands.command(name="play", description="Play a song or URL.")
    @app_commands.describe(query="Song name or URL")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        player = await _ensure_voice(interaction)
        if player is None:
            return
        await interaction.response.defer()
        tracks = await wavelink.Playable.search(query)
        if not tracks:
            await interaction.followup.send("❌ No tracks found.")
            return
        track = tracks[0]
        if player.playing:
            player.queue.put(track)
            await interaction.followup.send(f"➕ Queued **{track.title}**.")
        else:
            settings = await _get_settings(interaction.guild_id)
            player.volume = settings.default_volume
            await player.play(track)
            await interaction.followup.send(f"▶️ Now playing **{track.title}**.")

    # ------------------------------------------------------------------
    # /pause & /resume
    # ------------------------------------------------------------------

    @app_commands.command(name="pause", description="Pause the current track.")
    async def pause(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if player and player.playing:
            await player.pause(True)
            await interaction.response.send_message("⏸️ Paused.")
        else:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused track.")
    async def resume(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if player and player.paused:
            await player.pause(False)
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("❌ Not paused.", ephemeral=True)

    # ------------------------------------------------------------------
    # /stop
    # ------------------------------------------------------------------

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if player:
            player.queue.clear()
            await player.stop()
            await interaction.response.send_message("⏹️ Stopped and queue cleared.")
        else:
            await interaction.response.send_message("❌ Not playing.", ephemeral=True)

    # ------------------------------------------------------------------
    # /skip (vote-skip)
    # ------------------------------------------------------------------

    @app_commands.command(name="skip", description="Vote to skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if not player or not player.playing:
            await interaction.response.send_message("❌ Nothing to skip.", ephemeral=True)
            return
        settings = await _get_settings(interaction.guild_id)
        votes = self._vote_skips.setdefault(interaction.guild_id, set())
        votes.add(interaction.user.id)
        listeners = [m for m in player.channel.members if not m.bot]
        needed = max(1, round(len(listeners) * settings.vote_skip_percent / 100))
        if len(votes) >= needed:
            votes.clear()
            await player.skip()
            await interaction.response.send_message("⏭️ Skipped!")
        else:
            await interaction.response.send_message(
                f"🗳️ Skip vote: **{len(votes)}/{needed}** needed."
            )

    # ------------------------------------------------------------------
    # /seek
    # ------------------------------------------------------------------

    @app_commands.command(name="seek", description="Seek to a position in the track.")
    @app_commands.describe(time="Position to seek to, e.g. 1m30s or 90")
    async def seek(self, interaction: discord.Interaction, time: str) -> None:
        player = await _get_player(interaction)
        if not player or not player.playing:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
            return
        seconds = parse_duration(time)
        ms = seconds * 1000
        await player.seek(ms)
        await interaction.response.send_message(f"⏩ Seeked to **{time}**.")

    # ------------------------------------------------------------------
    # /loop
    # ------------------------------------------------------------------

    @app_commands.command(name="loop", description="Set loop mode.")
    @app_commands.describe(mode="track | queue | off")
    async def loop(
        self,
        interaction: discord.Interaction,
        mode: Literal["track", "queue", "off"],
    ) -> None:
        player = await _get_player(interaction)
        if not player:
            await interaction.response.send_message("❌ Not playing.", ephemeral=True)
            return
        mode_map = {
            "track": wavelink.QueueMode.loop,
            "queue": wavelink.QueueMode.loop_all,
            "off": wavelink.QueueMode.normal,
        }
        player.queue.mode = mode_map[mode]
        await interaction.response.send_message(f"🔁 Loop mode set to **{mode}**.")

    # ------------------------------------------------------------------
    # /volume
    # ------------------------------------------------------------------

    @app_commands.command(name="volume", description="Set the playback volume.")
    @app_commands.describe(level="Volume 0–100")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        player = await _get_player(interaction)
        if not player:
            await interaction.response.send_message("❌ Not playing.", ephemeral=True)
            return
        level = max(0, min(level, 100))
        await player.set_volume(level)
        async with db_session() as session:
            row = await session.scalar(
                select(MusicSettings).where(
                    MusicSettings.guild_id == interaction.guild_id
                )
            )
            if row:
                row.default_volume = level
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.")

    # ------------------------------------------------------------------
    # /queue
    # ------------------------------------------------------------------

    @app_commands.command(name="queue", description="View the current queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if not player:
            await interaction.response.send_message("❌ Not playing.", ephemeral=True)
            return
        tracks = list(player.queue)
        if not tracks:
            await interaction.response.send_message("📋 Queue is empty.")
            return
        embed = discord.Embed(title="🎵 Queue", color=0x5865F2)
        for i, track in enumerate(tracks[:15], 1):
            embed.add_field(
                name=f"{i}. {track.title}",
                value=f"by {track.author}",
                inline=False,
            )
        if len(tracks) > 15:
            embed.set_footer(text=f"+{len(tracks) - 15} more")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /nowplaying
    # ------------------------------------------------------------------

    @app_commands.command(name="nowplaying", description="Show the current track.")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = await _get_player(interaction)
        if not player or not player.current:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
            return
        track = player.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{track.title}** by {track.author}",
            color=0x5865F2,
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        embed.add_field(name="Duration", value=f"{track.length // 1000}s")
        embed.add_field(name="Volume", value=f"{player.volume}%")
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /24-7
    # ------------------------------------------------------------------

    @app_commands.command(name="247", description="[Admin] Toggle 24/7 mode.")
    @app_commands.default_permissions(manage_guild=True)
    async def mode_247(self, interaction: discord.Interaction) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(MusicSettings).where(
                    MusicSettings.guild_id == interaction.guild_id
                )
            )
            if row is None:
                row = MusicSettings(guild_id=interaction.guild_id)
                session.add(row)
            row.stay_247 = not row.stay_247
            state = "enabled" if row.stay_247 else "disabled"
        await interaction.response.send_message(f"🔁 24/7 mode **{state}**.")

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    @app_commands.command(name="playlist-save", description="Save the current queue as a playlist.")
    @app_commands.describe(name="Playlist name")
    async def playlist_save(self, interaction: discord.Interaction, name: str) -> None:
        player = await _get_player(interaction)
        if not player:
            await interaction.response.send_message("❌ Not playing.", ephemeral=True)
            return
        tracks_data = [t.uri for t in list(player.queue) if t.uri]
        if player.current and player.current.uri:
            tracks_data.insert(0, player.current.uri)

        async with db_session() as session:
            existing = await session.scalar(
                select(SavedPlaylist).where(
                    SavedPlaylist.user_id == interaction.user.id,
                    SavedPlaylist.name == name,
                )
            )
            if existing:
                existing.tracks_json = json.dumps(tracks_data)
            else:
                session.add(
                    SavedPlaylist(
                        user_id=interaction.user.id,
                        name=name,
                        tracks_json=json.dumps(tracks_data),
                    )
                )
        await interaction.response.send_message(
            f"✅ Saved playlist **{name}** with **{len(tracks_data)}** tracks."
        )

    @app_commands.command(name="playlist-load", description="Load a saved playlist.")
    @app_commands.describe(name="Playlist name")
    async def playlist_load(self, interaction: discord.Interaction, name: str) -> None:
        player = await _ensure_voice(interaction)
        if player is None:
            return
        async with async_session() as session:
            row = await session.scalar(
                select(SavedPlaylist).where(
                    SavedPlaylist.user_id == interaction.user.id,
                    SavedPlaylist.name == name,
                )
            )
        if row is None:
            await interaction.response.send_message("❌ Playlist not found.", ephemeral=True)
            return
        await interaction.response.defer()
        urls = json.loads(row.tracks_json)
        loaded = 0
        for url in urls:
            results = await wavelink.Playable.search(url)
            if results:
                player.queue.put(results[0])
                loaded += 1
        if not player.playing and not player.queue.is_empty:
            await player.play(player.queue.get())
        await interaction.followup.send(
            f"▶️ Loaded playlist **{name}** ({loaded} tracks)."
        )

    @app_commands.command(name="playlist-list", description="List your saved playlists.")
    async def playlist_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(SavedPlaylist).where(
                    SavedPlaylist.user_id == interaction.user.id
                )
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("You have no saved playlists.", ephemeral=True)
            return
        embed = discord.Embed(title="🎵 Your Playlists", color=0x5865F2)
        for row in items:
            count = len(json.loads(row.tracks_json))
            embed.add_field(name=row.name, value=f"{count} tracks", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /record  (Discord.py native voice recording — PyNaCl required)
    # ------------------------------------------------------------------

    @app_commands.command(name="record", description="Record voice channel audio and receive an MP3.")
    async def record(self, interaction: discord.Interaction) -> None:
        if interaction.user.voice is None:
            await interaction.response.send_message(
                "❌ You must be in a voice channel.", ephemeral=True
            )
            return
        guild_id = interaction.guild_id
        if guild_id in self._recordings:
            await interaction.response.send_message(
                "⏹️ Recording stopped. Processing...", ephemeral=True
            )
            sink = self._recordings.pop(guild_id)
            vc = interaction.guild.voice_client
            if vc:
                vc.stop_recording()
            return

        await interaction.response.send_message(
            "🔴 Recording started. Use `/record` again to stop.", ephemeral=True
        )
        vc = interaction.guild.voice_client
        if vc is None:
            vc = await interaction.user.voice.channel.connect()

        sink = discord.sinks.WaveSink()
        self._recordings[guild_id] = sink

        async def finished_callback(
            _sink: discord.sinks.WaveSink, _channel: discord.TextChannel, *args
        ) -> None:
            for user_id, audio in _sink.audio_data.items():
                buf = io.BytesIO(audio.file.getvalue())
                user = interaction.guild.get_member(user_id)
                name = user.display_name if user else str(user_id)
                try:
                    await interaction.user.send(
                        f"🎙️ Recording from {name}:",
                        file=discord.File(buf, filename=f"{name}.wav"),
                    )
                except discord.Forbidden:
                    pass

        vc.start_recording(sink, finished_callback, interaction.channel)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
