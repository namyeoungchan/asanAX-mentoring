"""
팀 채널 참여도 대시보드
- 관리자: /참여도 명령어로 과제 대시보드 채널에 고정 패널 게시
- 패널: 팀1~5 채팅 채널의 인원별 메시지 수 통계, 기간 버튼으로 갱신
- 과제 대시보드처럼 같은 메시지를 계속 수정(edit)하는 방식, 매일 09:00 KST 자동 갱신
"""
import datetime
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import database
from ui.embeds import KST

log = logging.getLogger("asanAX.participation")

PANEL_TYPE = "participation"
TOP_N = 10  # 팀별 표시 인원 수 상한
DEFAULT_DAYS = 7
PERIODS = [(7, "최근 7일"), (14, "최근 14일"), (30, "최근 30일"), (0, "전체 기간")]


def _is_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return any(r.id == config.ADMIN_ROLE_ID for r in member.roles)


# ── Stats collection ──────────────────────────────────────────────────────────

async def collect_participation(
    guild: discord.Guild, after: datetime.datetime | None
) -> dict[str, dict[int, tuple[str, int]]]:
    """
    팀별 채널 히스토리를 스캔해 {팀: {user_id: (이름, 메시지 수)}} 반환.
    봇 메시지는 제외.
    """
    stats: dict[str, dict[int, tuple[str, int]]] = {}

    for team, channel_id in config.TEAM_CHANNELS.items():
        counts: dict[int, tuple[str, int]] = {}
        ch = guild.get_channel(channel_id)
        if not ch or not isinstance(ch, discord.TextChannel):
            log.warning("Team channel not found: %s (%d)", team, channel_id)
            stats[team] = counts
            continue

        try:
            async for msg in ch.history(limit=None, after=after):
                if msg.author.bot:
                    continue
                name, count = counts.get(msg.author.id, (msg.author.display_name, 0))
                counts[msg.author.id] = (name, count + 1)
        except discord.Forbidden:
            log.warning("No permission to read history: %s (%d)", team, channel_id)

        stats[team] = counts

    return stats


# ── Embed builder ─────────────────────────────────────────────────────────────

def _bar(value: int, max_value: int, width: int = 10) -> str:
    if max_value <= 0 or value <= 0:
        return "░" * width
    filled = max(1, round(width * value / max_value))
    return "█" * filled + "░" * (width - filled)


def build_participation_embed(
    stats: dict[str, dict[int, tuple[str, int]]], days: int
) -> discord.Embed:
    period = f"최근 {days}일" if days > 0 else "전체 기간"
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    embed = discord.Embed(
        title="📊 팀 채널 참여도 대시보드",
        description=(
            f"집계 기간: **{period}** · 팀 채팅 메시지 수 기준 (봇 제외)\n"
            "아래 버튼으로 기간을 바꾸거나 새로고침할 수 있습니다."
        ),
        color=discord.Color.from_str("#2B5CE6"),
    )

    # ── 팀별 총합 비교 ─────────────────────────────────────────────────────────
    team_totals = {
        team: sum(count for _, count in counts.values())
        for team, counts in stats.items()
    }
    max_total = max(team_totals.values(), default=0)
    total_lines = [
        f"`{_bar(total, max_total)}` **{team}** — {total}건"
        for team, total in sorted(team_totals.items(), key=lambda x: -x[1])
    ]
    embed.add_field(name="🏆 팀별 총 메시지", value="\n".join(total_lines), inline=False)

    # ── 팀별 인원 순위 ─────────────────────────────────────────────────────────
    medals = ["🥇", "🥈", "🥉"]
    for team in config.TEAM_CHANNELS:
        counts = stats.get(team, {})
        if not counts:
            embed.add_field(name=f"👥 {team}", value="메시지 없음", inline=False)
            continue

        ranked = sorted(counts.values(), key=lambda x: -x[1])
        lines = []
        for i, (name, count) in enumerate(ranked[:TOP_N]):
            rank = medals[i] if i < len(medals) else f"`{i + 1}.`"
            lines.append(f"{rank} {name} — **{count}**건")
        if len(ranked) > TOP_N:
            rest = sum(count for _, count in ranked[TOP_N:])
            lines.append(f"… 외 {len(ranked) - TOP_N}명 {rest}건")

        embed.add_field(
            name=f"👥 {team} — 총 {team_totals[team]}건 · {len(ranked)}명 참여",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(text=f"아산 AX · {now_str}")
    return embed


def _parse_days_from_embed(embed: discord.Embed) -> int:
    """패널 임베드 설명에서 현재 집계 기간을 복원 (재시작/자동갱신용)."""
    desc = embed.description or ""
    m = re.search(r"최근 (\d+)일", desc)
    if m:
        return int(m.group(1))
    if "전체 기간" in desc:
        return 0
    return DEFAULT_DAYS


# ── Panel refresh ─────────────────────────────────────────────────────────────

async def refresh_participation_panel(bot: commands.Bot, days: int | None = None) -> bool:
    """
    저장된 패널 메시지를 최신 통계로 edit.
    days=None이면 현재 패널에 표시된 기간을 유지.
    """
    panel = await database.get_assignment_panel(PANEL_TYPE)
    if not panel:
        return False
    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        return False
    ch = guild.get_channel(int(panel["channel_id"]))
    if not ch or not isinstance(ch, discord.TextChannel):
        return False

    try:
        msg = await ch.fetch_message(int(panel["message_id"]))
        if days is None:
            days = _parse_days_from_embed(msg.embeds[0]) if msg.embeds else DEFAULT_DAYS

        after = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
            if days > 0
            else None
        )
        stats = await collect_participation(guild, after)
        embed = build_participation_embed(stats, days)
        # Pass view so buttons are preserved after edit
        await msg.edit(embed=embed, view=ParticipationPanelView(bot))
        return True
    except (discord.NotFound, discord.HTTPException) as e:
        log.warning("Participation panel refresh failed: %s", e)
        return False


# ── Panel view (persistent) ───────────────────────────────────────────────────

class ParticipationPanelView(discord.ui.View):
    """Survives bot restarts via custom_id."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

        for days, label in PERIODS:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if days == DEFAULT_DAYS else discord.ButtonStyle.secondary,
                custom_id=f"participation:period:{days}",
                row=0,
            )
            btn.callback = self._make_period_callback(days)
            self.add_item(btn)

        refresh = discord.ui.Button(
            label="🔄 새로고침",
            style=discord.ButtonStyle.secondary,
            custom_id="participation:refresh",
            row=1,
        )
        refresh.callback = self._on_refresh
        self.add_item(refresh)

    def _make_period_callback(self, days: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self._refresh(interaction, days)
        return callback

    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        await self._refresh(interaction, None)

    async def _refresh(self, interaction: discord.Interaction, days: int | None) -> None:
        # 히스토리 스캔은 오래 걸릴 수 있음
        await interaction.response.defer(ephemeral=True)
        ok = await refresh_participation_panel(self.bot, days)
        if ok:
            await interaction.followup.send("✅ 참여도 대시보드가 갱신되었습니다.", ephemeral=True)
        else:
            await interaction.followup.send(
                "갱신에 실패했습니다. `/참여도`로 패널을 다시 게시해주세요.", ephemeral=True
            )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Participation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(ParticipationPanelView(self.bot))
        self.daily_refresh.start()

    async def cog_unload(self) -> None:
        self.daily_refresh.cancel()

    # ── 매일 09:00 KST (00:00 UTC) 자동 갱신 ──────────────────────────────────
    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc))
    async def daily_refresh(self) -> None:
        refreshed = await refresh_participation_panel(self.bot)
        if refreshed:
            log.info("Participation panel auto-refreshed")

    @daily_refresh.before_loop
    async def before_daily_refresh(self) -> None:
        await self.bot.wait_until_ready()

    # ── /참여도 ────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="참여도",
        description="팀 채널 참여도 대시보드를 과제 대시보드 채널에 게시합니다 (관리자 전용)",
    )
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("서버에서만 사용할 수 있습니다.", ephemeral=True)
            return

        ch = guild.get_channel(config.ASSIGNMENT_DASHBOARD_CHANNEL_ID)
        if not ch or not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(
                "과제 대시보드 채널을 찾을 수 없습니다.", ephemeral=True
            )
            return

        # 히스토리 스캔은 오래 걸릴 수 있음
        await interaction.response.defer(ephemeral=True)

        after = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DEFAULT_DAYS)
        stats = await collect_participation(guild, after)
        embed = build_participation_embed(stats, DEFAULT_DAYS)

        msg = await ch.send(embed=embed, view=ParticipationPanelView(self.bot))
        await database.save_assignment_panel(PANEL_TYPE, str(ch.id), str(msg.id))

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 참여도 대시보드 게시 완료",
                description=f"{ch.mention} 채널에 게시되었습니다.\n버튼으로 기간 변경·새로고침이 가능하며, 매일 09:00 KST에 자동 갱신됩니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Participation(bot))
