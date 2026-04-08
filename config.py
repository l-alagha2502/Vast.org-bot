"""
Central configuration — all values are overridden by environment variables.
"""

import os


class BotConfig:
    # Bot identity
    BOT_NAME: str = os.getenv("BOT_NAME", "Vast Bot")
    BOT_AVATAR_URL: str = os.getenv("BOT_AVATAR_URL", "")
    PREFIX: str = os.getenv("PREFIX", "!")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))

    # Status
    STATUS_TYPE: str = os.getenv("STATUS_TYPE", "playing")   # playing|watching|listening
    STATUS_TEXT: str = os.getenv("STATUS_TEXT", "Vast.org")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///vast_bot.db")

    # Leveling
    TEXT_XP_MIN: int = int(os.getenv("TEXT_XP_MIN", "15"))
    TEXT_XP_MAX: int = int(os.getenv("TEXT_XP_MAX", "25"))
    TEXT_XP_COOLDOWN: int = int(os.getenv("TEXT_XP_COOLDOWN", "60"))   # seconds
    VOICE_XP_RATE: int = int(os.getenv("VOICE_XP_RATE", "10"))         # XP per minute

    # Moderation
    RAID_JOIN_THRESHOLD: int = int(os.getenv("RAID_JOIN_THRESHOLD", "10"))
    RAID_JOIN_WINDOW: int = int(os.getenv("RAID_JOIN_WINDOW", "10"))    # seconds
    RAID_ACCOUNT_AGE_DAYS: int = int(os.getenv("RAID_ACCOUNT_AGE_DAYS", "7"))

    # Anti-spam
    MAX_MENTIONS: int = int(os.getenv("MAX_MENTIONS", "5"))
    MAX_EMOJIS: int = int(os.getenv("MAX_EMOJIS", "10"))

    # Strike thresholds  (strikes -> action)
    STRIKE_WARN: int = int(os.getenv("STRIKE_WARN", "1"))
    STRIKE_MUTE: int = int(os.getenv("STRIKE_MUTE", "3"))
    STRIKE_KICK: int = int(os.getenv("STRIKE_KICK", "5"))

    # Social media polling intervals (seconds)
    TWITCH_POLL: int = int(os.getenv("TWITCH_POLL", "60"))
    YOUTUBE_POLL: int = int(os.getenv("YOUTUBE_POLL", "120"))
    TWITTER_POLL: int = int(os.getenv("TWITTER_POLL", "60"))
    REDDIT_POLL: int = int(os.getenv("REDDIT_POLL", "120"))
    INSTAGRAM_POLL: int = int(os.getenv("INSTAGRAM_POLL", "300"))
    TIKTOK_POLL: int = int(os.getenv("TIKTOK_POLL", "300"))

    # External API keys
    TWITCH_CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CLIENT_SECRET: str = os.getenv("TWITCH_CLIENT_SECRET", "")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")
    TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "vast-bot/1.0")

    # Instagram (optional — anonymous access works but is rate-limited)
    INSTAGRAM_USERNAME: str = os.getenv("INSTAGRAM_USERNAME", "")
    INSTAGRAM_PASSWORD: str = os.getenv("INSTAGRAM_PASSWORD", "")

    # Google Cloud Natural Language (AI Guard)
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )

    # Lavalink (music)
    LAVALINK_HOST: str = os.getenv("LAVALINK_HOST", "127.0.0.1")
    LAVALINK_PORT: int = int(os.getenv("LAVALINK_PORT", "2333"))
    LAVALINK_PASSWORD: str = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

    # Economy
    STARTING_BALANCE: int = int(os.getenv("STARTING_BALANCE", "100"))
    DAILY_COINS: int = int(os.getenv("DAILY_COINS", "50"))

    # Starboard
    STARBOARD_THRESHOLD: int = int(os.getenv("STARBOARD_THRESHOLD", "3"))

    # Leaderboard web URL (if hosted)
    LEADERBOARD_BASE_URL: str = os.getenv("LEADERBOARD_BASE_URL", "https://vast.org/leaderboard")
