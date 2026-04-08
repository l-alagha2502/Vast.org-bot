# Vast.org Bot

A fully-featured, white-label Discord bot combining the feature sets of **MEE6 Pro** and **ProBot Premium**.

---

## Project Structure

```
Vast.org-bot/
├── bot.py                  # Entry point — VastBot class, cog loader
├── config.py               # All configuration (env-var driven)
├── requirements.txt        # Python dependencies
├── .env.example            # Example environment file (copy → .env)
│
├── database/
│   ├── __init__.py         # Async SQLAlchemy engine + session factory
│   ├── base.py             # Re-exports + init_db()
│   └── models.py           # Complete database schema (all modules)
│
├── utils/
│   ├── __init__.py         # parse_duration, level helpers, resolve_variables
│   └── image_gen.py        # Pillow rank cards + welcome/goodbye banners
│
└── cogs/
    ├── identity.py         # Module 1  — Bot identity & /vip commands
    ├── leveling.py         # Module 2  — Dual XP, multipliers, rank cards
    ├── moderation.py       # Module 3  — Ban/mute/kick, anti-raid, AI guard
    ├── automations.py      # Module 4  — IFTTT-style trigger/action engine
    ├── social_media.py     # Module 5  — Twitch/YouTube/Twitter/Reddit feeds
    ├── music.py            # Module 6  — Lavalink player, playlists, recording
    ├── reaction_roles.py   # Module 7a — Unlimited reaction roles
    ├── welcome.py          # Module 7b — Welcome/goodbye image cards
    ├── birthdays.py        # Module 7c — Birthday wishes + temp birthday role
    ├── timers.py           # Module 7d — Recurring automated messages
    ├── tickets.py          # Module 7e — Button-click support tickets
    ├── economy.py          # Module 7f — Coins, daily reward, shop
    ├── logs.py             # Module 7g — In-depth audit logging
    ├── starboard.py        # Module 7h — ⭐ reaction hall-of-fame
    ├── custom_commands.py  # Module 7i — Admin-created text/embed commands
    └── invites.py          # Module 7j — Invite tracking + role-on-join
```

---

## Quick Start

### 1. Clone & install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in DISCORD_TOKEN plus any API keys you need
```

### 3. (Optional) Lavalink for Music

Download and run a [Lavalink](https://github.com/lavalink-devs/Lavalink) server, then set `LAVALINK_HOST`, `LAVALINK_PORT`, and `LAVALINK_PASSWORD` in your `.env`.

### 4. Start the bot

```bash
python bot.py
```

The bot automatically creates all database tables on first run (SQLite by default).

---

## Feature Modules

### Module 1 — Bot Identity & VIP Controls
| Command | Description |
|---|---|
| `/vip name <name>` | Set bot nickname (owner only) |
| `/vip status <type> <text>` | Change presence (playing/watching/listening) |
| `/vip avatar <url>` | Change bot avatar globally |
| `/vip transfer <user>` | Transfer bot ownership |

### Module 2 — Advanced Leveling
| Command | Description |
|---|---|
| `/rank [user]` | Display rank card with Pillow image |
| `/profile` | View XP stats |
| `/levels` | Web leaderboard link |
| `/give-xp <user> <amount>` | Admin: award XP |
| `/xp-settings` | Toggle global boost, set voice counter channel |
| `/xp-multiplier <role> <multiplier>` | Set role-based XP multiplier |
| `/xp-blacklist <type> <id>` | Blacklist channel/role from XP |
| `/level-reward <level> <role>` | Assign role at level milestone |
| `/profile-style` | Customise bar color, text color, background |

### Module 3 — Elite Moderation & Anti-Raid
| Command | Description |
|---|---|
| `/ban <user> [reason] [delete_days]` | Ban a member |
| `/kick <user> [reason]` | Kick a member |
| `/warn <user> [reason]` | Strike system (warn→mute→kick) |
| `/mute <type> <user> <duration> [reason]` | Text/voice/both mute with complex duration |
| `/unmute <user>` | Remove mute |
| `/clear <amount> [user] [bots]` | Bulk-delete messages |
| `/slowmode <seconds> [channel]` | Set channel slowmode |
| `/role-multiple <add/remove> <role> [filter]` | Mass role assignment |
| `/mod-settings` | Configure link protection, anti-raid, AI guard |
| `/link-whitelist <domain>` | Add domain to whitelist |

### Module 4 — Automations Engine
| Command | Description |
|---|---|
| `/automation-create` | Create IFTTT trigger→action rule |
| `/automation-list` | List all rules |
| `/automation-toggle <id>` | Enable/disable a rule |
| `/automation-delete <id>` | Remove a rule |

**Triggers:** `message_sent`, `message_deleted`, `message_edited`, `reaction_added`, `reaction_removed`, `voice_join`, `voice_leave`, `button_click`

**Actions:** `send_message`, `add_role`, `remove_role`, `delete_message`, `send_dm`, `create_thread`, `move_user`

**Variables:** `{user.mention}`, `{user.name}`, `{channel.name}`, `{server.member_count}`

### Module 5 — Social Media Alerts
| Command | Description |
|---|---|
| `/social-add` | Subscribe to Twitch/YouTube/Twitter/Reddit/Instagram/TikTok |
| `/social-remove <id>` | Remove a feed |
| `/social-list` | Show all feeds |

### Module 6 — Music & Audio Pro
| Command | Description |
|---|---|
| `/play <query>` | Play or queue a track |
| `/pause` / `/resume` | Pause/resume |
| `/stop` | Stop and clear queue |
| `/skip` | Vote-skip |
| `/seek <time>` | Seek to position |
| `/loop <track/queue/off>` | Set loop mode |
| `/volume <0-100>` | Set volume |
| `/queue` | View queue |
| `/nowplaying` | Current track info |
| `/247` | Toggle 24/7 mode |
| `/playlist-save <name>` | Save current queue |
| `/playlist-load <name>` | Load a saved playlist |
| `/playlist-list` | List your playlists |
| `/record` | Record VC audio and send WAV |

### Module 7 — Utilities

**Reaction Roles:** `/reaction-role-add`, `/reaction-role-remove`

**Welcome/Goodbye:** `/welcome-setup` — image banners, custom messages, background URL

**Birthdays:** `/birthday-set`, `/birthday-setup` — auto-wish + temporary role

**Timers:** `/timer-create`, `/timer-list`, `/timer-delete` — recurring messages

**Tickets:** `/ticket-setup` — button-click private channels with close button

**Economy:** `/balance`, `/daily`, `/give-coins`, `/shop`, `/buy`, `/shop-add`, `/leaderboard-coins`

**Audit Logs:** `/log-setup` — message edits/deletes, joins/leaves, role changes, bans, voice, channel changes

**Starboard:** `/starboard-setup` — configurable emoji + threshold

**Custom Commands:** `/cmd-create`, `/cmd-delete`, `/cmd-list` — text or embed responses

**Invites:** `/invite-track`, `/invite-list`, `/invite-delete` — role-on-join, expire by time or use count

---

## Database

All data is persisted in SQLite by default (upgradeable to PostgreSQL via `DATABASE_URL`).
Schema is automatically created on startup via SQLAlchemy `create_all`.

Key tables: `user_levels`, `xp_multipliers`, `xp_settings`, `xp_blacklist`, `level_role_rewards`,
`moderation_actions`, `user_strikes`, `link_whitelist`, `moderation_settings`, `automations`,
`social_feeds`, `music_settings`, `saved_playlists`, `reaction_roles`, `welcome_settings`,
`birthdays`, `birthday_settings`, `timers`, `tickets`, `ticket_settings`, `economy_accounts`,
`shop_items`, `starboard_settings`, `starboard_entries`, `custom_commands`, `invite_links`,
`invite_usage`, `audit_logs`, `audit_log_settings`, `bot_identity`

