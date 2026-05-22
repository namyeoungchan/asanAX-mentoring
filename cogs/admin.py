from datetime import datetime, date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
from config import ADMIN_ROLE_ID
from ui import embeds
from ui.confirm_view import AdminSlotRemoveView
from ui.mentor_panel import MentorPanelView, build_panel_embed

PAGE_SIZE = 10


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)
    return app_commands.check(predicate)


class SlotAddModal(discord.ui.Modal, title="슬롯 추가"):
    label_input = discord.ui.TextInput(
        label="표시 이름",
        placeholder="예: 5/30 오후 2시 (1시간)",
        max_length=100,
    )
    start_input = discord.ui.TextInput(
        label="시작 시간 (ISO 형식)",
        placeholder="2026-05-30T14:00:00",
        max_length=30,
    )
    end_input = discord.ui.TextInput(
        label="종료 시간 (ISO 형식)",
        placeholder="2026-05-30T15:00:00",
        max_length=30,
    )

    def __init__(self, mentor: dict, bot: commands.Bot) -> None:
        super().__init__()
        self.mentor = mentor
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        start = self.start_input.value.strip()
        end = self.end_input.value.strip()

        for value, field in [(start, "시작 시간"), (end, "종료 시간")]:
            try:
                datetime.fromisoformat(value)
            except ValueError:
                await interaction.response.send_message(
                    embed=embeds.error_embed(
                        f"`{field}` 형식이 올바르지 않습니다. 예: `2026-05-30T14:00:00`"
                    ),
                    ephemeral=True,
                )
                return

        slot_id = await database.add_slot(
            self.mentor["id"], start, end, self.label_input.value.strip()
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="슬롯 추가 완료",
                description=(
                    f"**{self.mentor['name']}** 멘토에게 슬롯이 추가되었습니다.\n"
                    f"**{self.label_input.value}** (ID: {slot_id})"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        # Refresh all panels in background
        await refresh_all_panels(self.bot)


class MentorAddModal(discord.ui.Modal, title="멘토 등록"):
    name_input = discord.ui.TextInput(label="멘토 이름", max_length=50)
    bio_input = discord.ui.TextInput(
        label="소개",
        style=discord.TextStyle.paragraph,
        placeholder="멘토 소개를 입력하세요",
        required=False,
        max_length=300,
    )

    def __init__(self, user: discord.Member, bot: commands.Bot) -> None:
        super().__init__()
        self.user = user
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        existing = await database.get_mentor_by_discord_id(str(self.user.id))
        if existing:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"{self.user.mention}은(는) 이미 멘토로 등록되어 있습니다."),
                ephemeral=True,
            )
            return
        mentor_id = await database.add_mentor(
            str(self.user.id), self.name_input.value.strip(), self.bio_input.value.strip()
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="멘토 등록 완료",
                description=f"**{self.name_input.value}** 멘토가 등록되었습니다. (ID: {mentor_id})",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await refresh_all_panels(self.bot)


async def refresh_all_panels(bot: commands.Bot) -> None:
    """Update all posted panels with the latest mentor/slot data."""
    panels = await database.get_panels()
    mentors = await database.get_mentors()
    panel_embed = await build_panel_embed(mentors)
    view = MentorPanelView(mentors)

    for panel in panels:
        try:
            guild = bot.get_guild(int(panel["guild_id"]))
            if not guild:
                continue
            channel = guild.get_channel(int(panel["channel_id"]))
            if not channel or not isinstance(channel, discord.TextChannel):
                continue
            msg = await channel.fetch_message(int(panel["message_id"]))
            await msg.edit(embed=panel_embed, view=view)
        except (discord.NotFound, discord.Forbidden):
            await database.delete_panel(panel["id"])


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    admin_group = app_commands.Group(name="admin", description="관리자 전용 명령어")

    # ── Autocomplete ──────────────────────────────────────────────────────

    async def _mentor_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        mentors = await database.get_mentors()
        return [
            app_commands.Choice(name=m["name"], value=str(m["id"]))
            for m in mentors
            if current.lower() in m["name"].lower()
        ][:25]

    # ── /admin panel-post ─────────────────────────────────────────────────

    @admin_group.command(name="panel-post", description="이 채널에 멘토링 예약 패널을 게시합니다.")
    @is_admin()
    async def panel_post(self, interaction: discord.Interaction) -> None:
        mentors = await database.get_mentors()
        panel_embed = await build_panel_embed(mentors)
        view = MentorPanelView(mentors)

        await interaction.response.send_message("패널을 게시합니다...", ephemeral=True)

        msg = await interaction.channel.send(embed=panel_embed, view=view)  # type: ignore[union-attr]
        await database.save_panel(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            message_id=str(msg.id),
        )
        await interaction.edit_original_response(
            content=f"패널이 게시되었습니다. (메시지 ID: {msg.id})\n슬롯/멘토를 변경하면 자동으로 갱신됩니다."
        )

    # ── /admin panel-refresh ──────────────────────────────────────────────

    @admin_group.command(name="panel-refresh", description="모든 패널을 최신 정보로 새로고침합니다.")
    @is_admin()
    async def panel_refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await refresh_all_panels(self.bot)
        await interaction.followup.send("모든 패널이 갱신되었습니다.", ephemeral=True)

    # ── /admin mentor-add ─────────────────────────────────────────────────

    @admin_group.command(name="mentor-add", description="멘토를 등록합니다.")
    @app_commands.describe(user="멘토로 등록할 디스코드 유저")
    @is_admin()
    async def mentor_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.send_modal(MentorAddModal(user, self.bot))

    # ── /admin mentor-remove ──────────────────────────────────────────────

    @admin_group.command(name="mentor-remove", description="멘토를 제거합니다.")
    @app_commands.describe(mentor="제거할 멘토")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def mentor_remove(self, interaction: discord.Interaction, mentor: str) -> None:
        try:
            mentor_id = int(mentor)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return
        success = await database.remove_mentor(mentor_id)
        if success:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="멘토 제거 완료",
                    description=f"멘토 (ID: {mentor_id})가 제거되었습니다.",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
            await refresh_all_panels(self.bot)
        else:
            await interaction.response.send_message(
                embed=embeds.error_embed("해당 멘토를 찾을 수 없습니다."), ephemeral=True
            )

    # ── /admin slot-add ───────────────────────────────────────────────────

    @admin_group.command(name="slot-add", description="예약 슬롯을 추가합니다 (팝업 폼).")
    @app_commands.describe(mentor="슬롯을 추가할 멘토")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def slot_add(self, interaction: discord.Interaction, mentor: str) -> None:
        try:
            mentor_id = int(mentor)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return
        mentor_obj = await database.get_mentor_by_id(mentor_id)
        if not mentor_obj:
            await interaction.response.send_message(
                embed=embeds.error_embed("멘토를 찾을 수 없습니다."), ephemeral=True
            )
            return
        await interaction.response.send_modal(SlotAddModal(mentor_obj, self.bot))

    # ── /admin slot-remove ────────────────────────────────────────────────

    @admin_group.command(name="slot-remove", description="예약 슬롯을 비활성화합니다.")
    @app_commands.describe(slot_id="제거할 슬롯 ID")
    @is_admin()
    async def slot_remove(self, interaction: discord.Interaction, slot_id: int) -> None:
        slot = await database.get_slot(slot_id)
        if not slot:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"슬롯 ID {slot_id}을 찾을 수 없습니다."), ephemeral=True
            )
            return

        booking = await database.get_booking_for_slot(slot_id)
        if booking:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="경고: 예약이 있는 슬롯",
                    description=(
                        f"슬롯 `{slot_id}` ({slot['label']})에는 **@{booking['user_name']}**의 예약이 있습니다.\n"
                        "계속하면 예약이 취소됩니다. 정말 진행하시겠습니까?"
                    ),
                    color=discord.Color.orange(),
                ),
                view=AdminSlotRemoveView(slot_id, had_booking=True),
                ephemeral=True,
            )
        else:
            await database.deactivate_slot(slot_id)
            await interaction.response.send_message(
                embed=embeds.admin_slot_removed_embed(slot_id, had_booking=False),
                ephemeral=True,
            )
            await refresh_all_panels(self.bot)

    # ── /admin slot-list ──────────────────────────────────────────────────

    @admin_group.command(name="slot-list", description="멘토의 모든 슬롯을 조회합니다.")
    @app_commands.describe(mentor="조회할 멘토")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def slot_list(self, interaction: discord.Interaction, mentor: str) -> None:
        try:
            mentor_id = int(mentor)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return

        mentor_obj = await database.get_mentor_by_id(mentor_id)
        if not mentor_obj:
            await interaction.response.send_message(
                embed=embeds.error_embed("멘토를 찾을 수 없습니다."), ephemeral=True
            )
            return

        slots = await database.get_slots_for_mentor(mentor_id, active_only=False)
        slot_ids = [s["id"] for s in slots]
        bookings_map = await database.get_bookings_by_slot_ids(slot_ids)

        embed = discord.Embed(
            title=f"{mentor_obj['name']} 전체 슬롯 현황",
            color=discord.Color.blurple(),
        )
        if not slots:
            embed.description = "등록된 슬롯이 없습니다."
        else:
            lines = []
            for s in slots:
                active = "활성" if s["is_active"] else "비활성"
                booking = bookings_map.get(s["id"])
                booked = f"예약: @{booking['user_name']}" if booking else "예약 없음"
                lines.append(f"`[{s['id']}]` [{active}] **{s['label']}** — {booked}")
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /admin schedule-set ───────────────────────────────────────────────

    @admin_group.command(name="schedule-set", description="멘토의 기본 예약 시간대를 설정합니다.")
    @app_commands.describe(
        mentor="설정할 멘토",
        start="시작 시간 (HH:MM, 기본 19:00)",
        end="종료 시간 (HH:MM, 기본 21:00)",
        interval="슬롯 간격(분, 기본 30)",
    )
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def schedule_set(
        self,
        interaction: discord.Interaction,
        mentor: str,
        start: str = "19:00",
        end: str = "21:00",
        interval: int = 30,
    ) -> None:
        try:
            mentor_id = int(mentor)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return

        mentor_obj = await database.get_mentor_by_id(mentor_id)
        if not mentor_obj:
            await interaction.response.send_message(
                embed=embeds.error_embed("멘토를 찾을 수 없습니다."), ephemeral=True
            )
            return

        try:
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("시간 형식이 올바르지 않습니다. 예: `19:00`"), ephemeral=True
            )
            return

        await database.set_slot_template(mentor_id, sh, sm, eh, em, interval)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="스케줄 설정 완료",
                description=(
                    f"**{mentor_obj['name']}** 멘토 기본 시간대 설정됨\n"
                    f"⏰ {start} ~ {end} / {interval}분 단위\n\n"
                    "`/admin slots-generate` 로 날짜 범위에 슬롯을 생성하세요."
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ── /admin slots-generate ─────────────────────────────────────────────

    @admin_group.command(name="slots-generate", description="날짜 범위에 슬롯을 자동 생성합니다.")
    @app_commands.describe(
        mentor="슬롯을 생성할 멘토",
        date_from="시작일 (YYYY-MM-DD)",
        date_to="종료일 (YYYY-MM-DD)",
    )
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def slots_generate(
        self,
        interaction: discord.Interaction,
        mentor: str,
        date_from: str,
        date_to: str,
    ) -> None:
        try:
            mentor_id = int(mentor)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return

        mentor_obj = await database.get_mentor_by_id(mentor_id)
        if not mentor_obj:
            await interaction.response.send_message(
                embed=embeds.error_embed("멘토를 찾을 수 없습니다."), ephemeral=True
            )
            return

        template = await database.get_slot_template(mentor_id)
        if not template:
            await interaction.response.send_message(
                embed=embeds.error_embed(
                    "스케줄 템플릿이 없습니다. 먼저 `/admin schedule-set` 으로 시간대를 설정하세요."
                ),
                ephemeral=True,
            )
            return

        try:
            d_from = date.fromisoformat(date_from)
            d_to = date.fromisoformat(date_to)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("날짜 형식이 올바르지 않습니다. 예: `2026-05-30`"), ephemeral=True
            )
            return

        if d_to < d_from:
            await interaction.response.send_message(
                embed=embeds.error_embed("종료일이 시작일보다 앞입니다."), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
        interval = template["interval_minutes"]
        created = 0
        skipped_blocked = 0

        current = d_from
        while current <= d_to:
            if await database.is_date_blocked(mentor_id, current.isoformat()):
                skipped_blocked += 1
                current += timedelta(days=1)
                continue

            # Generate time slots for this day
            cur_h = template["start_hour"]
            cur_m = template["start_minute"]
            end_h = template["end_hour"]
            end_m = template["end_minute"]

            while (cur_h * 60 + cur_m) + interval <= end_h * 60 + end_m:
                next_total = cur_h * 60 + cur_m + interval
                next_h, next_m = divmod(next_total, 60)

                start_iso = f"{current.isoformat()}T{cur_h:02d}:{cur_m:02d}:00"
                end_iso = f"{current.isoformat()}T{next_h:02d}:{next_m:02d}:00"
                label = (
                    f"{current.month}/{current.day} ({WEEKDAYS[current.weekday()]}) "
                    f"{cur_h:02d}:{cur_m:02d}~{next_h:02d}:{next_m:02d}"
                )

                await database.add_slot(mentor_id, start_iso, end_iso, label)
                created += 1

                cur_h, cur_m = next_h, next_m

            current += timedelta(days=1)

        desc_lines = [f"✅ 생성된 슬롯: **{created}개**"]
        if skipped_blocked:
            desc_lines.append(f"🚫 예약 불가일로 건너뜀: **{skipped_blocked}일**")

        await interaction.followup.send(
            embed=discord.Embed(
                title="슬롯 자동 생성 완료",
                description="\n".join(desc_lines),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await refresh_all_panels(self.bot)

    # ── /admin bookings ───────────────────────────────────────────────────

    @admin_group.command(name="bookings", description="전체(또는 특정 멘토의) 예약을 조회합니다.")
    @app_commands.describe(mentor="특정 멘토만 조회 (선택)", page="페이지 번호 (기본: 1)")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    @is_admin()
    async def bookings(
        self,
        interaction: discord.Interaction,
        mentor: str | None = None,
        page: int = 1,
    ) -> None:
        mentor_id = None
        if mentor:
            try:
                mentor_id = int(mentor)
            except ValueError:
                await interaction.response.send_message(
                    embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
                )
                return

        all_bookings = await database.get_all_bookings(mentor_id)
        total_pages = max(1, (len(all_bookings) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_pages))
        page_data = all_bookings[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

        await interaction.response.send_message(
            embed=embeds.admin_bookings_embed(page_data, page, total_pages),
            ephemeral=True,
        )

    # ── /admin onboarding-panel ──────────────────────────────────────────

    @admin_group.command(
        name="onboarding-panel",
        description="#온보딩 채널에 고정 온보딩 버튼 메시지를 게시합니다.",
    )
    @is_admin()
    async def onboarding_panel(self, interaction: discord.Interaction) -> None:
        from cogs.onboarding import OnboardingView, _welcome_embed

        channel = self.bot.get_channel(config.ONBOARDING_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error_embed("온보딩 채널을 찾을 수 없습니다. ONBOARDING_CHANNEL_ID를 확인하세요."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="👋 Welcome to FOUNDERS 42",
            description=(
                "아산시 AX 글로벌 인재 양성 프로그램에 오신 것을 환영합니다!\n\n"
                "아래 **[✍️ 자기소개 작성하기]** 버튼을 눌러 온보딩을 시작해주세요.\n"
                "버튼을 누르면 본인에게만 보이는 화면이 열립니다."
            ),
            color=discord.Color.from_str("#2B5CE6"),
        )
        embed.add_field(
            name="✅ 온보딩 체크리스트",
            value=(
                "① 팀 선택\n"
                "② 자기소개 작성\n"
                "③ 닉네임 자동 변경 (`실명_팀명`)\n"
                "④ 팀 채널 및 협업 툴 접속 확인"
            ),
            inline=False,
        )
        embed.add_field(
            name="💡 이 과정에서 중요한 것",
            value="✔ 완벽보다 실행  ✔ 아이디어보다 검증\n✔ 혼자보다 협업  ✔ 스펙보다 결과물",
            inline=False,
        )
        embed.set_footer(text="자기소개까지 완료하면 모든 채널 접근 권한이 부여됩니다 · 아산 AX")

        await channel.send(embed=embed, view=OnboardingView(self.bot))
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ 온보딩 패널 게시 완료",
                description=f"{channel.mention} 채널에 온보딩 버튼 메시지를 게시했습니다.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ── /admin onboarding-test ────────────────────────────────────────────

    @admin_group.command(
        name="onboarding-test",
        description="특정 멤버에게 온보딩 플로우를 강제 실행합니다. (테스트용)",
    )
    @app_commands.describe(member="온보딩을 테스트할 멤버")
    @is_admin()
    async def onboarding_test(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        from cogs.onboarding import Onboarding

        cog: Onboarding | None = self.bot.get_cog("Onboarding")  # type: ignore[assignment]
        if not cog:
            await interaction.response.send_message(
                embed=embeds.error_embed("Onboarding cog이 로드되지 않았습니다."), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Reset DB state so the test can run cleanly
        import aiosqlite
        from config import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM onboarding_progress WHERE user_id = ?", (str(member.id),)
            )
            await db.commit()

        await cog.on_member_join(member)

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 온보딩 테스트 실행",
                description=f"{member.mention} 에게 온보딩 플로우를 실행했습니다.\n`#온보딩` 채널을 확인하세요.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
