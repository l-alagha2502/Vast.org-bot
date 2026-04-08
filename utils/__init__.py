"""
Utility helpers shared across cogs.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from database.base import async_session


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """Context manager that yields an AsyncSession and commits/rolls back."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def parse_duration(text: str) -> int:
    """
    Parse a human-friendly duration string into total seconds.

    Examples
    --------
    >>> parse_duration("1d 12h")
    129600
    >>> parse_duration("30m")
    1800
    >>> parse_duration("2h 30m 15s")
    9015
    """
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    total = 0
    for match in re.finditer(r"(\d+)\s*([dhms])", text.lower()):
        total += int(match.group(1)) * units[match.group(2)]
    if total == 0 and text.strip().isdigit():
        total = int(text.strip())
    return total


def xp_for_level(level: int) -> int:
    """Total cumulative XP required to *reach* ``level``."""
    return int(5 * (level**2) + 50 * level + 100) * level // 2


def level_from_xp(xp: int) -> int:
    """Derive the current level from total accumulated XP."""
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def resolve_variables(template: str, **context: object) -> str:
    """
    Replace ``{key}`` placeholders with values from *context*.

    Supported tags (examples):
        {user.mention}  {user.name}  {channel.name}  {server.member_count}
    """
    # Flatten nested keys: "user.mention" → context["user"]["mention"]
    def _get(parts: list[str], obj: object) -> str:
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part, "")
            else:
                obj = getattr(obj, part, "")
        return str(obj)

    def replacer(m: re.Match) -> str:
        key = m.group(1)
        parts = key.split(".")
        root = parts[0]
        if root in context:
            return _get(parts[1:], context[root]) if len(parts) > 1 else str(context[root])
        return m.group(0)

    return re.sub(r"\{([\w.]+)\}", replacer, template)
