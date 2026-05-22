"""
과제 시스템 v2
- 관리자: 과제 대시보드 채널에 패널 게시 → [➕ 팀 과제 생성] / [➕ 개인 과제 생성] 버튼으로 생성
          제출 항목(필드)을 자유롭게 지정 가능 (최대 4개)
- 수강생: 과제제출 채널의 버튼 → 팀 선택(팀 과제) → 커스텀 필드 Modal
- 대시보드: 과제 생성·제출 시 자동 갱신 (주차별 팀 제출 현황)
"""
import datetime
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import database

log = logging.getLogger("asanAX.assignment")

TEAMS = ["팀1", "팀2", "팀3", "팀4", "팀5", "팀6"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return any(r.id == config.ADMIN_ROLE_ID for r in member.roles)


def _parse_fields(raw: str | None) -> list[str]:
    if not raw:
        return ["제출 내용"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return [str(f) for f in parsed[:4]]
    except (json.JSONDecodeError, TypeError):
        pass
    return ["제출 내용"]


# ── Dashboard builder ─────────────────────────────────────────────────────────

async def build_dashboard_embeds() -> list[discord.Embed]:
    assignments = await database.get_assignments(active_only=True)
    now_str = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    if not assignments:
        return [
            discord.Embed(
                title="📋 과제 현황 대시보드",
                description=(
                    "현재 진행 중인 과제가 없습니다.\n\n"
                    "아래 버튼으로 과제를 생성하세요."
                ),
                color=discord.Color.blurple(),
            ).set_footer(text=f"아산 AX · {now_str}")
        ]

    embeds: list[discord.Embed] = []
    for a in assignments:
        subs = await database.get_submissions(a["id"])
        by_team: dict[str, list[dict]] = {}
        for s in subs:
            by_team.setdefault(s["team"], []).append(s)

        type_label = "팀별" if a["type"] == "team" else "개인별"
        field_names = _parse_fields(a.get("fields"))

        embed = discord.Embed(
            title=f"📌 {a['week']}주차 — {a['title']}",
            description=a["description"] or "",
            color=discord.Color.from_str("#2B5CE6"),
        )
        embed.add_field(name="마감일", value=a["due_date"], inline=True)
        embed.add_field(name="제출 방식", value=type_label, inline=True)
        embed.add_field(name="총 제출", value=f"{len(subs)}건", inline=True)
        embed.add_field(name="제출 항목", value=" · ".join(field_names), inline=False)

        lines = []
        for team in TEAMS:
            team_subs = by_team.get(team, [])
            if team_subs:
                names = ", ".join(s["user_name"] for s in team_subs[:3])
                if len(team_subs) > 3:
                    names += f" 외 {len(team_subs) - 3}명"
                lines.append(f"✅ **{team}** {len(team_subs)}명 — {names}")
            else:
                lines.append(f"❌ **{team}** — 미제출")

        embed.add_field(name="팀별 제출 현황", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"아산 AX · 과제 ID: {a['id']} · {now_str}")
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
        # Pass view so buttons are preserved after edit
        await msg.edit(embeds=new_embeds, view=AdminDashboardView(bot))
    except (discord.NotFound, discord.HTTPException) as e:
        log.warning("Dashboard refresh failed: %s", e)


# ── Admin: Assignment creation modal ──────────────────────────────────────────

class CreateAssignmentModal(discord.ui.Modal):
    week_input = discord.ui.TextInput(
        label="주차",
        placeholder="1",
        max_length=3,
    )
    title_input = discord.ui.TextInput(
        label="과제 제목",
        placeholder="아이디어 기획서 제출",
        max_length=100,
    )
    description_input = discord.ui.TextInput(
        label="과제 설명",
        placeholder="이번 주차 과제에 대한 안내를 입력하세요.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    due_date_input = discord.ui.TextInput(
        label="마감일 (YYYY-MM-DD)",
        placeholder="2026-05-30",
        max_length=10,
    )
    fields_input = discord.ui.TextInput(
        label="제출 항목 (쉼표로 구분, 최대 4개)",
        placeholder="제출 링크, 핵심 인사이트, 팀 역할 분담",
        default="제출 내용",
        required=False,
        max_length=200,
    )

    def __init__(self, bot: commands.Bot, assignment_type: str) -> None:
        type_label = "팀" if assignment_type == "team" else "개인"
        super().__init__(title=f"{type_label} 과제 생성")
        self.bot = bot
        self.assignment_type = assignment_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            week = int(self.week_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "주차는 숫자로 입력해주세요. (예: `1`)", ephemeral=True
            )
            return

        try:
            datetime.date.fromisoformat(self.due_date_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "날짜 형식이 올바르지 않습니다. 예: `2026-05-30`", ephemeral=True
            )
            return

        raw = self.fields_input.value.strip()
        field_names = (
            [f.strip() for f in raw.split(",") if f.strip()][:4]
            if raw else ["제출 내용"]
        )
        fields_json = json.dumps(field_names, ensure_ascii=False)

        assignment_id = await database.create_assignment(
            week=week,
            title=self.title_input.value.strip(),
            description=self.description_input.value.strip(),
            due_date=self.due_date_input.value.strip(),
            type_=self.assignment_type,
            fields=fields_json,
        )

        type_label = "팀별" if self.assignment_type == "team" else "개인별"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ 과제 생성 완료",
                description=(
                    f"**{week}주차 — {self.title_input.value.strip()}**\n"
                    f"마감일: {self.due_date_input.value.strip()} | {type_label}\n"
                    f"제출 항목: {', '.join(field_names)}\n"
                    f"ID: `{assignment_id}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await refresh_dashboard(self.bot)


# ── Admin: Submission detail view (ephemeral, paginated) ─────────────────────

def _build_submission_page(assignment: dict, subs: list[dict], page: int, per_page: int) -> list[discord.Embed]:
    total = len(subs)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = page * per_page
    page_subs = subs[start : start + per_page]

    header = discord.Embed(
        title=f"📋 {assignment['week']}주차 — {assignment['title']} 제출 내역",
        description=f"총 **{total}건** | {page + 1}/{total_pages} 페이지",
        color=discord.Color.from_str("#2B5CE6"),
    )
    embeds = [header]

    for sub in page_subs:
        try:
            field_values: dict = json.loads(sub["content"])
        except (json.JSONDecodeError, TypeError):
            field_values = {"내용": sub["content"]}

        sub_embed = discord.Embed(
            title=f"👤 {sub['user_name']} ({sub['team']})",
            color=discord.Color.green(),
        )
        for label, value in field_values.items():
            sub_embed.add_field(name=label, value=value[:512] or "—", inline=False)
        if sub["link"]:
            sub_embed.add_field(name="링크", value=sub["link"], inline=False)
        sub_embed.set_footer(text=f"제출 시각: {sub['submitted_at']}")
        embeds.append(sub_embed)

    return embeds


class SubmissionDetailView(discord.ui.View):
    PER_PAGE = 4  # header + 4 submissions = 5 embeds (Discord max 10)

    def __init__(self, assignment: dict, subs: list[dict], page: int = 0) -> None:
        super().__init__(timeout=120)
        self.assignment = assignment
        self.subs = subs
        self.page = page
        self.total_pages = max(1, (len(subs) + self.PER_PAGE - 1) // self.PER_PAGE)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embeds(self) -> list[discord.Embed]:
        return _build_submission_page(self.assignment, self.subs, self.page, self.PER_PAGE)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embeds=self.build_embeds(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embeds=self.build_embeds(), view=self)


class SubmissionAssignmentSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, assignments: list[dict]) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        options = [
            discord.SelectOption(
                label=f"{a['week']}주차 — {a['title'][:45]}",
                value=str(a["id"]),
                description=f"마감: {a['due_date']}",
            )
            for a in assignments[:25]
        ]
        select = discord.ui.Select(
            placeholder="제출 내역을 볼 과제를 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        assignment_id = int(interaction.data["values"][0])  # type: ignore[index]
        assignment = await database.get_assignment(assignment_id)
        if not assignment:
            await interaction.response.edit_message(content="과제를 찾을 수 없습니다.", embeds=[], view=None)
            return

        subs = await database.get_submissions(assignment_id)
        if not subs:
            await interaction.response.edit_message(
                embeds=[discord.Embed(
                    title=f"📋 {assignment['week']}주차 — {assignment['title']} 제출 내역",
                    description="아직 제출한 인원이 없습니다.",
                    color=discord.Color.orange(),
                )],
                view=None,
            )
            return

        view = SubmissionDetailView(assignment, subs)
        await interaction.response.edit_message(embeds=view.build_embeds(), view=view)


# ── Admin: Dashboard panel view (persistent) ──────────────────────────────────

class AdminDashboardView(discord.ui.View):
    """Survives bot restarts via custom_id."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="➕ 팀 과제 생성",
        style=discord.ButtonStyle.success,
        custom_id="assignment:create:team",
        row=0,
    )
    async def create_team(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(CreateAssignmentModal(self.bot, "team"))

    @discord.ui.button(
        label="➕ 개인 과제 생성",
        style=discord.ButtonStyle.primary,
        custom_id="assignment:create:individual",
        row=0,
    )
    async def create_individual(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(CreateAssignmentModal(self.bot, "individual"))

    @discord.ui.button(
        label="📋 제출 내역 보기",
        style=discord.ButtonStyle.secondary,
        custom_id="assignment:view_submissions",
        row=0,
    )
    async def view_submissions(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        assignments = await database.get_assignments(active_only=False)
        if not assignments:
            await interaction.response.send_message(
                embed=discord.Embed(description="등록된 과제가 없습니다.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        if len(assignments) == 1:
            assignment = assignments[0]
            subs = await database.get_submissions(assignment["id"])
            if not subs:
                await interaction.response.send_message(
                    embeds=[discord.Embed(
                        title=f"📋 {assignment['week']}주차 — {assignment['title']} 제출 내역",
                        description="아직 제출한 인원이 없습니다.",
                        color=discord.Color.orange(),
                    )],
                    ephemeral=True,
                )
                return
            view = SubmissionDetailView(assignment, subs)
            await interaction.response.send_message(
                embeds=view.build_embeds(), view=view, ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="📋 제출 내역 조회",
                    description="내역을 볼 과제를 선택하세요.",
                    color=discord.Color.from_str("#2B5CE6"),
                ),
                view=SubmissionAssignmentSelectView(self.bot, assignments),
                ephemeral=True,
            )

    @discord.ui.button(
        label="🔄 새로고침",
        style=discord.ButtonStyle.secondary,
        custom_id="assignment:dashboard:refresh",
        row=1,
    )
    async def refresh_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await refresh_dashboard(self.bot)
        await interaction.followup.send("✅ 대시보드가 새로고침되었습니다.", ephemeral=True)


# ── Student: Dynamic submit modal ─────────────────────────────────────────────

class DynamicSubmitModal(discord.ui.Modal):
    """Fields are built dynamically from assignment's fields config."""

    def __init__(self, bot: commands.Bot, assignment: dict, team: str) -> None:
        super().__init__(title="과제 제출")
        self.bot = bot
        self.assignment = assignment
        self.team = team

        field_names = _parse_fields(assignment.get("fields"))
        self._field_inputs: list[discord.ui.TextInput] = []

        for i, name in enumerate(field_names):
            inp = discord.ui.TextInput(
                label=name[:45],
                style=discord.TextStyle.paragraph if i == 0 else discord.TextStyle.short,
                required=True,
                max_length=500,
            )
            self.add_item(inp)
            self._field_inputs.append(inp)

        self._link_input = discord.ui.TextInput(
            label="링크 (선택 — GitHub, Notion, Drive 등)",
            placeholder="https://...",
            required=False,
            max_length=500,
        )
        self.add_item(self._link_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        field_values = {inp.label: inp.value.strip() for inp in self._field_inputs}
        link = self._link_input.value.strip()
        content_json = json.dumps(field_values, ensure_ascii=False)

        ok = await database.create_submission(
            assignment_id=self.assignment["id"],
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
            team=self.team,
            content=content_json,
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

        # Post public notice to 과제제출 channel
        submit_ch = interaction.guild.get_channel(config.ASSIGNMENT_SUBMIT_CHANNEL_ID)  # type: ignore[union-attr]
        if submit_ch and isinstance(submit_ch, discord.TextChannel):
            pub = discord.Embed(
                title="📝 과제 제출",
                description=f"**{self.assignment['week']}주차 — {self.assignment['title']}**",
                color=discord.Color.green(),
            )
            pub.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url,
            )
            pub.add_field(name="팀", value=self.team, inline=True)
            pub.add_field(name="제출자", value=interaction.user.mention, inline=True)
            for label, value in field_values.items():
                pub.add_field(name=label, value=value[:500] or "—", inline=False)
            if link:
                pub.add_field(name="링크", value=link, inline=False)
            await submit_ch.send(embed=pub)

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 제출 완료!",
                description=(
                    f"**{self.assignment['week']}주차 — {self.assignment['title']}** "
                    "과제가 제출되었습니다."
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await refresh_dashboard(self.bot)


# ── Student: Team select ──────────────────────────────────────────────────────

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
            DynamicSubmitModal(self.bot, self.assignment, team)
        )


# ── Student: Assignment select (multiple active) ──────────────────────────────

class AssignmentSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, assignments: list[dict]) -> None:
        super().__init__(timeout=120)
        self.bot = bot

        options = [
            discord.SelectOption(
                label=f"{a['week']}주차 — {a['title'][:45]}",
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
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
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

        if assignment["type"] == "team":
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"📌 {assignment['week']}주차 — {assignment['title']}",
                    description="소속 팀을 선택해주세요.",
                    color=discord.Color.from_str("#2B5CE6"),
                ),
                view=TeamSelectView(self.bot, assignment),
                ephemeral=True,
            )
        else:
            await interaction.response.send_modal(
                DynamicSubmitModal(self.bot, assignment, "개인")
            )


# ── Student: Submit panel (persistent) ───────────────────────────────────────

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

            if assignment["type"] == "team":
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title=f"📌 {assignment['week']}주차 — {assignment['title']}",
                        description=f"마감일: **{assignment['due_date']}**\n\n소속 팀을 선택해주세요.",
                        color=discord.Color.from_str("#2B5CE6"),
                    ),
                    view=TeamSelectView(self.bot, assignment),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_modal(
                    DynamicSubmitModal(self.bot, assignment, "개인")
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
        self.bot.add_view(AdminDashboardView(self.bot))

    # ── /과제 패널 ─────────────────────────────────────────────────────────────

    @group.command(name="패널", description="과제제출 채널에 제출 패널을 게시합니다 (관리자 전용)")
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
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
                "2. 진행 중인 과제 선택 (여러 개인 경우)\n"
                "3. 소속 팀 선택 (팀 과제인 경우)\n"
                "4. 제출 내용 작성 후 제출\n\n"
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

    @group.command(name="대시보드", description="과제 대시보드 패널을 게시합니다 (관리자 전용)")
    async def post_dashboard(self, interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        ch = interaction.guild.get_channel(config.ASSIGNMENT_DASHBOARD_CHANNEL_ID)  # type: ignore[union-attr]
        if not ch or not isinstance(ch, discord.TextChannel):
            await interaction.followup.send("과제 대시보드 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        new_embeds = await build_dashboard_embeds()
        msg = await ch.send(embeds=new_embeds, view=AdminDashboardView(self.bot))
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
                name=f"{a['week']}주차 — {a['title']}",
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
        if not _is_admin(interaction):
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
