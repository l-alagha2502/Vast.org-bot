"""
Economy Engine — coins, daily reward, shop (roles/icons), balance commands.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func

from config import BotConfig
from database.base import async_session
from database.models import EconomyAccount, ShopItem
from utils import db_session

log = logging.getLogger(__name__)


async def _get_account(guild_id: int, user_id: int) -> EconomyAccount:
    async with async_session() as session:
        row = await session.scalar(
            select(EconomyAccount).where(
                EconomyAccount.guild_id == guild_id,
                EconomyAccount.user_id == user_id,
            )
        )
        if row is None:
            row = EconomyAccount(
                guild_id=guild_id,
                user_id=user_id,
                balance=BotConfig.STARTING_BALANCE,
            )
            session.add(row)
            await session.commit()
    return row


class EconomyCog(commands.Cog, name="Economy"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="balance", description="Check your coin balance.")
    @app_commands.describe(user="User to check (admin only for others)")
    async def balance(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        target = user or interaction.user
        if user and user != interaction.user:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ You can only check your own balance.", ephemeral=True
                )
                return
        account = await _get_account(interaction.guild_id, target.id)
        embed = discord.Embed(
            title=f"💰 {target.display_name}'s Balance",
            description=f"**{account.balance:,}** coins",
            color=0xFFD700,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily coin reward.")
    async def daily(self, interaction: discord.Interaction) -> None:
        async with db_session() as session:
            row = await session.scalar(
                select(EconomyAccount).where(
                    EconomyAccount.guild_id == interaction.guild_id,
                    EconomyAccount.user_id == interaction.user.id,
                )
            )
            if row is None:
                row = EconomyAccount(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    balance=BotConfig.STARTING_BALANCE,
                )
                session.add(row)

            now = datetime.datetime.utcnow()
            if row.last_daily_at:
                elapsed = (now - row.last_daily_at).total_seconds()
                if elapsed < 86400:
                    remaining = 86400 - elapsed
                    h, m = divmod(int(remaining), 3600)
                    m //= 60
                    await interaction.response.send_message(
                        f"⏳ You already claimed today. Try again in **{h}h {m}m**.",
                        ephemeral=True,
                    )
                    return
            row.balance += BotConfig.DAILY_COINS
            row.last_daily_at = now

        await interaction.response.send_message(
            f"✅ You claimed **{BotConfig.DAILY_COINS:,}** coins! "
            f"New balance: **{row.balance:,}**."
        )

    @app_commands.command(name="give-coins", description="[Admin] Give coins to a user.")
    @app_commands.describe(user="Recipient", amount="Amount of coins")
    @app_commands.default_permissions(administrator=True)
    async def give_coins(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ) -> None:
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        async with db_session() as session:
            row = await session.scalar(
                select(EconomyAccount).where(
                    EconomyAccount.guild_id == interaction.guild_id,
                    EconomyAccount.user_id == user.id,
                )
            )
            if row is None:
                row = EconomyAccount(
                    guild_id=interaction.guild_id,
                    user_id=user.id,
                    balance=BotConfig.STARTING_BALANCE,
                )
                session.add(row)
            row.balance += amount
        await interaction.response.send_message(
            f"✅ Gave **{amount:,}** coins to {user.mention}."
        )

    @app_commands.command(name="shop", description="Browse the server shop.")
    async def shop(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(ShopItem).where(ShopItem.guild_id == interaction.guild_id)
            )
            items = list(rows)
        if not items:
            await interaction.response.send_message("🛒 The shop is empty.", ephemeral=True)
            return
        embed = discord.Embed(title="🛒 Server Shop", color=0xFFD700)
        for item in items:
            stock_str = "∞" if item.stock == -1 else str(item.stock)
            embed.add_field(
                name=f"{item.name} — {item.price:,} coins",
                value=f"{item.description or ''} | Type: {item.item_type} | Stock: {stock_str}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item_name="Name of the item to buy")
    async def buy(self, interaction: discord.Interaction, item_name: str) -> None:
        async with db_session() as session:
            item = await session.scalar(
                select(ShopItem).where(
                    ShopItem.guild_id == interaction.guild_id,
                    ShopItem.name == item_name,
                )
            )
            if item is None:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            if item.stock == 0:
                await interaction.response.send_message("❌ Out of stock.", ephemeral=True)
                return

            account = await session.scalar(
                select(EconomyAccount).where(
                    EconomyAccount.guild_id == interaction.guild_id,
                    EconomyAccount.user_id == interaction.user.id,
                )
            )
            if account is None:
                account = EconomyAccount(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    balance=BotConfig.STARTING_BALANCE,
                )
                session.add(account)
            if account.balance < item.price:
                await interaction.response.send_message(
                    f"❌ Not enough coins. You need {item.price:,} but have {account.balance:,}.",
                    ephemeral=True,
                )
                return
            account.balance -= item.price
            if item.stock > 0:
                item.stock -= 1

            # Fulfil role purchase
            if item.item_type == "role" and item.role_id:
                role = interaction.guild.get_role(item.role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Shop purchase")
                    except discord.HTTPException:
                        pass

        await interaction.response.send_message(
            f"✅ You bought **{item.name}** for **{item.price:,}** coins!"
        )

    @app_commands.command(name="shop-add", description="[Admin] Add an item to the shop.")
    @app_commands.describe(
        name="Item name",
        price="Cost in coins",
        item_type="role or icon",
        description="Item description",
        role="Role to assign (if type is role)",
        stock="Stock quantity (-1 for unlimited)",
    )
    @app_commands.default_permissions(administrator=True)
    async def shop_add(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        item_type: str,
        description: Optional[str] = None,
        role: Optional[discord.Role] = None,
        stock: int = -1,
    ) -> None:
        async with db_session() as session:
            session.add(
                ShopItem(
                    guild_id=interaction.guild_id,
                    name=name,
                    description=description,
                    price=price,
                    item_type=item_type,
                    role_id=role.id if role else None,
                    stock=stock,
                )
            )
        await interaction.response.send_message(
            f"✅ Added **{name}** to the shop for **{price:,}** coins.", ephemeral=True
        )

    @app_commands.command(name="leaderboard-coins", description="Top coin holders in the server.")
    async def leaderboard_coins(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rows = await session.scalars(
                select(EconomyAccount)
                .where(EconomyAccount.guild_id == interaction.guild_id)
                .order_by(EconomyAccount.balance.desc())
                .limit(10)
            )
            top = list(rows)
        embed = discord.Embed(title="💰 Coin Leaderboard", color=0xFFD700)
        for i, row in enumerate(top, 1):
            member = interaction.guild.get_member(row.user_id)
            name = member.display_name if member else f"User {row.user_id}"
            embed.add_field(
                name=f"#{i} {name}", value=f"{row.balance:,} coins", inline=False
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
