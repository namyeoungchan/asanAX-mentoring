"""
과제 시스템
- 관리자: /과제 생성, /과제 패널, /과제 대시보드, /과제 목록, /과제 비활성화
- 수강생: 과제제출 채널 제출 패널 버튼 → 팀 선택 → Modal 작성
- 대시보드: 과제 생성·제출 시 자동 갱신
"""
import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import database

log = logging.getLogger("asanAX.assignment")

TEAMS = ["팀1", "팀2", "팀3", "팀4", "팀5", "팀6"]


# ── Dashboard builder ─────────────────────────────────────────────────────────

async def build_dashboard_embeds() -> list[discord.Embed]:
    assignments = await database.get_assignments(active_only=True)

    if not assignments:
        return [
            discord.Embed(
                title="📋 과제 현황 대시보드",
                description="현재 진행 중인 과제가 없습니다.",
                color=discord.Color.blurple(),
            )
        ]

    now_str = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    embeds: list[discord.Embed] = []

    for assignment in assignments:
        submissions = await database.get_submissions(assignment["id"])
        by_team: dict[str, list[dict]] = {}
        for sub in submissions:
            by_team.setdefault(sub["team"], []).append(sub)

        type_label = "팀별" if assignment["type"] == "team" else "개인별"
        embed = discord.Embed(
            title=f"📌 [{assignment['week']}주차] {assignment['title']}",
            description=assignment["description"] or "",
            color=discord.Color.from_str("#2B5CE6"),
        )
        embed.add_field(name="마감일", value=assignment["due_date"], inline=True)
        embed.add_field(name="제출 방식", value=type_label, inline=True)
        embed.add_field(name="총 제출", value=f"{len(submissions)}건", inline=True)

        lines = []
        for team in TEAMS:
            team_subs = by_team.get(team, [])
            if team_subs:
                lines.append(f"✅ **{team}** — {len(team_subs)}명 제출")
            else:
                lines.append(f"❌ **{team}** — 미제출")

        embed.add_field(
            name="팀별 제출 현황",
            value="\n".join(lines),
            inline=False,
        )
        embed.set_footer(text=f"아산 AX · 마지막 업데이트: {now_str}")
        embeds.append(embed)

    return embeds


async def refresh_dashboard(bot: commands.Bot) -> None:
    panel = await database.get_assignment_panel("dashboard")
    if not panel:
        return

    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        return

    ch = guild.get_channel(int(panel["channel_id"]))
    if not ch or not isinstance(ch, discord.TextChannel):
        return

    try:
        msg = await ch.fetch_message(int(panel["message_id"]))
        new_embeds = await build_dashboard_embeds()
        await msg.edit(embeds=new_embeds)
    except (discord.NotFound, discord.HTTPException) as e:
        log.warning("Dashboard refresh failed: %s", e)


# ── Submit Modal ──────────────────────────────────────────────────────────────

class SubmitModal(discord.ui.Modal, title="과제 제출"):
    content_field = discord.ui.TextInput(
        label="제출 내용",
        placeholder="과제 내용을 입력하세요...",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    link_field = discord.ui.TextInput(
        label="링크 (선택 — GitHub, Notion, Drive 등)",
        placeholder="https://...",
        required=False,
        max_length=500,
    )

    def __init__(self, bot: commands.Bot, assignment: dict, team: str) -> None:
        super().__init__()
        self.bot = bot
        self.assignment = assignment
        self.team = team

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        content = self.content_field.value.strip()
        link = self.link_field.value.strip()

        ok = await database.create_submission(
            assignment_id=self.assignment["id"],
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            team=self.team,
            content=content,
            link=link,
        )

        if not ok:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="이미 제출하셨습니다",
                    description=(
                        f"**{self.assignment['title']}** 과제는 이미 제출하셨습니다.\n"
                        "중복 제출은 허용되지 않습니다."
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        # Post public submission notice to 과제제출 channel
        submit_ch = interaction.guild.get_channel(config.ASSIGNMENT_SUBMIT_CHANNEL_ID)  # type: ignore[union-attr]
        if submit_ch and isinstance(submit_ch, discord.TextChannel):
            pub_embed = discord.Embed(
                title="📝 과제 제출",
                description=f"**[{self.assignment['week']}주차] {self.assignment['title']}**",
                color=discord.Color.green(),
            )
            pub_embed.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url,
            )
            pub_embed.add_field(name="팀", value=self.team, inline=True)
            pub_embed.add_field(name="제출자", value=interaction.user.mention, inline=True)
            pub_embed.add_field(name="내용", value=content[:500], inline=False)
            if link:
                pub_embed.add_field(name="링크", value=link, inline=False)
            await submit_ch.send(embed=pub_embed)

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 제출 완료!",
                description=f"**[{self.assignment['week']}주차] {self.assignment['title']}** 과제가 제출되었습니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

        await refresh_dashboard(self.bot)


# ── Team select (shown after assignment is chosen) ────────────────────────────

class TeamSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, assignment: dict) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.assignment = assignment

        options = [discord.SelectOption(label=t, value=t, emoji="👥") for t in TEAMS]
        select = discord.ui.Select(
            placeholder="소속 팀을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_team_select
        self.add_item(select)

    async def _on_team_select(self, interaction: discord.Interaction) -> None:
        team = interaction.data["values"][0]  # type: ignore[index]
        await interaction.response.send_modal(
            SubmitModal(self.bot, self.assignment, team)
        )


# ── Assignment select (shown when multiple active assignments) ─────────────────

class AssignmentSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, assignments: list[dict]) -> None:
        super().__init__(timeout=120)
        self.bot = bot

        options = [
            discord.SelectOption(
                label=f"[{a['week']}주차] {a['title'][:50]}",
                value=str(a["id"]),
                description=f"마감: {a['due_date']}",
            )
            for a in assignments[:25]
        ]
        select = discord.ui.Select(
            placeholder="제출할 과제를 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_assignment_select
        self.add_item(select)

    async def _on_assignment_select(self, interaction: discord.Interaction) -> None:
        assignment_id = int(interaction.data["values"][0])  # type: ignore[index]
        assignment = await database.get_assignment(assignment_id)
        if not assignment:
            await interaction.response.send_message("과제를 찾을 수 없습니다.", ephemeral=True)
            return

        existing = await database.get_submission(assignment_id, str(interaction.user.id))
        if existing:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="이미 제출하셨습니다",
                    description=f"**{assignment['title']}** 과제는 이미 제출하셨습니다.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"📌 [{assignment['week']}주차] {assignment['title']}",
                description="소속 팀을 선택해주세요.",
                color=discord.Color.from_str("#2B5CE6"),
            ),
            view=TeamSelectView(self.bot, assignment),
            ephemeral=True,
        )


# ── Persistent submit panel ───────────────────────────────────────────────────

class SubmitPanelView(discord.ui.View):
    """Survives bot restarts via custom_id."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="📝 과제 제출하기",
        style=discord.ButtonStyle.primary,
        custom_id="assignment:submit",
    )
    async def submit(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        assignments = await database.get_assignments(active_only=True)

        if not assignments:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="진행 중인 과제 없음",
                    description="현재 제출 가능한 과제가 없습니다.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        if len(assignments) == 1:
            assignment = assignments[0]
            existing = await database.get_submission(assignment["id"], str(interaction.user.id))
            if existing:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="이미 제출하셨습니다",
                        description=f"**{assignment['title']}** 과제는 이미 제출하셨습니다.",
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"📌 [{assignment['week']}주차] {assignment['title']}",
                    description=f"마감일: **{assignment['due_date']}**\n\n소속 팀을 선택해주세요.",
                    color=discord.Color.from_str("#2B5CE6"),
                ),
                view=TeamSelectView(self.bot, assignment),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="📋 과제 선택",
                    description="제출할 과제를 선택하세요.",
                    color=discord.Color.from_str("#2B5CE6"),
                ),
                view=AssignmentSelectView(self.bot, assignments),
                ephemeral=True,
            )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Assignment(commands.Cog):
    group = app_commands.Group(name="과제", description="과제 관리")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(SubmitPanelView(self.bot))

    # ── Admin helpers ──────────────────────────────────────────────────────────

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        return any(r.id == config.ADMIN_ROLE_ID for r in member.roles)

    # ── /과제 생성 ─────────────────────────────────────────────────────────────

    @group.command(name="생성", description="새 과제를 등록합니다 (관리자 전용)")
    @app_commands.describe(
        week="주차 번호",
        title="과제 제목",
        description="과제 설명 (간략히)",
        due_date="마감일 (YYYY-MM-DD 형식)",
        type="제출 방식",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="팀별", value="team"),
        app_commands.Choice(name="개인별", value="individual"),
    ])
    async def create_assignment(
        self,
        interaction: discord.Interaction,
        week: int,
        title: str,
        description: str,
        due_date: str,
        type: str = "team",
    ) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        try:
            datetime.date.fromisoformat(due_date)
        except ValueError:
            await interaction.response.send_message(
                "날짜 형식이 올바르지 않습니다. 예: `2026-05-25`", ephemeral=True
            )
            return

        assignment_id = await database.create_assignment(week, title, description, due_date, type)
        type_label = "팀별" if type == "team" else "개인별"

        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ 과제 생성 완료",
                description=(
                    f"**[{week}주차] {title}**\n"
                    f"마감일: {due_date} | 제출 방식: {type_label}\n"
                    f"ID: `{assignment_id}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

        await refresh_dashboard(self.bot)

    # ── /과제 패널 ─────────────────────────────────────────────────────────────

    @group.command(name="패널", description="과제제출 채널에 제출 패널을 게시합니다 (관리자 전용)")
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        ch = interaction.guild.get_channel(config.ASSIGNMENT_SUBMIT_CHANNEL_ID)  # type: ignore[union-attr]
        if not ch or not isinstance(ch, discord.TextChannel):
            await interaction.followup.send("과제제출 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📝 과제 제출",
            description=(
                "아래 버튼을 눌러 과제를 제출하세요.\n\n"
                "**제출 방법**\n"
                "1. **[📝 과제 제출하기]** 버튼 클릭\n"
                "2. 제출할 과제 선택 (진행 중인 과제가 여러 개인 경우)\n"
                "3. 소속 팀 선택\n"
                "4. 제출 내용 및 링크 작성 후 제출\n\n"
                "제출 후 이 채널에 공개됩니다."
            ),
            color=discord.Color.from_str("#2B5CE6"),
        )
        embed.set_footer(text="아산 AX · 과제 제출 시스템")

        msg = await ch.send(embed=embed, view=SubmitPanelView(self.bot))
        await database.save_assignment_panel("submit", str(ch.id), str(msg.id))

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 제출 패널 게시 완료",
                description=f"{ch.mention} 채널에 게시되었습니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ── /과제 대시보드 ──────────────────────────────────────────────────────────

    @group.command(name="대시보드", description="과제 대시보드를 게시합니다 (관리자 전용)")
    async def post_dashboard(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        ch = interaction.guild.get_channel(config.ASSIGNMENT_DASHBOARD_CHANNEL_ID)  # type: ignore[union-attr]
        if not ch or not isinstance(ch, discord.TextChannel):
            await interaction.followup.send("과제 대시보드 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        new_embeds = await build_dashboard_embeds()
        msg = await ch.send(embeds=new_embeds)
        await database.save_assignment_panel("dashboard", str(ch.id), str(msg.id))

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 대시보드 게시 완료",
                description=f"{ch.mention} 채널에 게시되었습니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ── /과제 목록 ─────────────────────────────────────────────────────────────

    @group.command(name="목록", description="과제 목록을 확인합니다")
    async def list_assignments(self, interaction: discord.Interaction) -> None:
        assignments = await database.get_assignments(active_only=False)

        if not assignments:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="과제 없음",
                    description="등록된 과제가 없습니다.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 과제 목록", color=discord.Color.from_str("#2B5CE6"))
        for a in assignments[:10]:
            status = "✅ 활성" if a["is_active"] else "🚫 비활성"
            type_label = "팀별" if a["type"] == "team" else "개인별"
            embed.add_field(
                name=f"[{a['week']}주차] {a['title']}",
                value=f"ID: `{a['id']}` | 마감: {a['due_date']} | {type_label} | {status}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /과제 비활성화 ─────────────────────────────────────────────────────────

    @group.command(name="비활성화", description="과제를 비활성화합니다 (관리자 전용)")
    @app_commands.describe(assignment_id="비활성화할 과제 ID (/과제 목록에서 확인)")
    async def deactivate(
        self, interaction: discord.Interaction, assignment_id: int
    ) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        ok = await database.deactivate_assignment(assignment_id)
        if not ok:
            await interaction.response.send_message(
                "해당 ID의 과제를 찾을 수 없습니다.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ 비활성화 완료",
                description=f"과제 ID `{assignment_id}`이(가) 비활성화되었습니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await refresh_dashboard(self.bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Assignment(bot))
