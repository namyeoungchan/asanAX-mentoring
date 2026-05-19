"""
멘토 자기관리 명령어
- /mentor block   : 예약 불가일 지정 (본인만)
- /mentor unblock : 예약 불가일 해제 (본인만)
- /mentor schedule: 내 예약 현황 확인
"""
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import database

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _next_n_dates(n: int = 30) -> list[date]:
    today = date.today()
    return [today + timedelta(days=i) for i in range(n)]


async def _get_mentor(discord_id: str) -> dict | None:
    return await database.get_mentor_by_discord_id(discord_id)


class BlockDateView(discord.ui.View):
    """Select menu showing next 30 days — mentor picks dates to block."""

    def __init__(self, mentor: dict, blocked: list[str]) -> None:
        super().__init__(timeout=120)
        self.mentor = mentor
        self.blocked = set(blocked)

        dates = _next_n_dates(30)
        options = []
        for d in dates:
            ds = d.isoformat()
            label = f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"
            if ds in self.blocked:
                label += " 🚫"
            options.append(discord.SelectOption(label=label, value=ds))

        select = discord.ui.Select(
            placeholder="차단할 날짜를 선택하세요 (복수 선택 가능)",
            min_values=1,
            max_values=min(len(options), 10),
            options=options,
        )
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        selected: list[str] = interaction.data["values"]  # type: ignore[index]
        newly_blocked = []
        already = []
        for ds in selected:
            ok = await database.block_date(self.mentor["id"], ds)
            if ok:
                newly_blocked.append(ds)
            else:
                already.append(ds)

        lines = []
        if newly_blocked:
            lines.append("**차단 완료:**\n" + "\n".join(f"• {d}" for d in newly_blocked))
        if already:
            lines.append("**이미 차단된 날짜:**\n" + "\n".join(f"• {d}" for d in already))

        embed = discord.Embed(
            title="예약 불가일 설정 완료",
            description="\n\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)


class UnblockDateView(discord.ui.View):
    """Select menu showing currently blocked dates to unblock."""

    def __init__(self, mentor: dict, blocked: list[str]) -> None:
        super().__init__(timeout=120)
        self.mentor = mentor

        if not blocked:
            self.add_item(discord.ui.Select(
                placeholder="차단된 날짜가 없습니다",
                options=[discord.SelectOption(label="없음", value="none")],
                disabled=True,
            ))
            return

        options = []
        for ds in blocked:
            d = date.fromisoformat(ds)
            label = f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"
            options.append(discord.SelectOption(label=label, value=ds))

        select = discord.ui.Select(
            placeholder="해제할 날짜를 선택하세요",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        selected: list[str] = interaction.data["values"]  # type: ignore[index]
        for ds in selected:
            await database.unblock_date(self.mentor["id"], ds)

        embed = discord.Embed(
            title="예약 불가일 해제 완료",
            description="\n".join(f"• {d}" for d in selected),
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)


class MentorSelf(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    mentor_group = app_commands.Group(name="멘토", description="멘토 전용 명령어")

    async def _resolve_mentor(self, interaction: discord.Interaction) -> dict | None:
        mentor = await _get_mentor(str(interaction.user.id))
        if not mentor:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="권한 없음",
                    description="멘토로 등록된 계정만 사용할 수 있습니다.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
        return mentor

    # ── /mentor block ─────────────────────────────────────────────────────

    @mentor_group.command(name="block", description="예약 불가일을 지정합니다. (멘토 전용)")
    async def block(self, interaction: discord.Interaction) -> None:
        mentor = await self._resolve_mentor(interaction)
        if not mentor:
            return

        blocked = await database.get_blocked_dates(mentor["id"])
        embed = discord.Embed(
            title="예약 불가일 지정",
            description="차단할 날짜를 선택하세요. 해당 날 슬롯은 예약 불가 처리됩니다.",
            color=discord.Color.orange(),
        )
        if blocked:
            embed.add_field(
                name="현재 차단된 날짜",
                value="\n".join(f"• {d}" for d in blocked),
                inline=False,
            )
        await interaction.response.send_message(
            embed=embed,
            view=BlockDateView(mentor, blocked),
            ephemeral=True,
        )

    # ── /mentor unblock ───────────────────────────────────────────────────

    @mentor_group.command(name="unblock", description="예약 불가일을 해제합니다. (멘토 전용)")
    async def unblock(self, interaction: discord.Interaction) -> None:
        mentor = await self._resolve_mentor(interaction)
        if not mentor:
            return

        blocked = await database.get_blocked_dates(mentor["id"])
        embed = discord.Embed(
            title="예약 불가일 해제",
            description="해제할 날짜를 선택하세요.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=UnblockDateView(mentor, blocked),
            ephemeral=True,
        )

    # ── /mentor my-blocks ─────────────────────────────────────────────────

    @mentor_group.command(name="my-blocks", description="내 예약 불가일 목록을 확인합니다. (멘토 전용)")
    async def my_blocks(self, interaction: discord.Interaction) -> None:
        mentor = await self._resolve_mentor(interaction)
        if not mentor:
            return

        blocked = await database.get_blocked_dates(mentor["id"])
        embed = discord.Embed(
            title=f"{mentor['name']} 예약 불가일",
            color=discord.Color.orange(),
        )
        if blocked:
            embed.description = "\n".join(f"🚫 {d}" for d in blocked)
        else:
            embed.description = "차단된 날짜가 없습니다."
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentorSelf(bot))
