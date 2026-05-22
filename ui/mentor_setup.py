"""
Mentor self-service setup panel.
Accessible via /멘토 설정
"""
from datetime import date, timedelta

import discord
from discord.ext import commands

import database
from ui import embeds
from ui.date_select import WEEKDAYS


# ── Modals ────────────────────────────────────────────────────────────────────

class ScheduleSetModal(discord.ui.Modal, title="멘토링 시간대 설정"):
    start_time = discord.ui.TextInput(
        label="시작 시간 (HH:MM)",
        placeholder="19:00",
        default="19:00",
        max_length=5,
    )
    end_time = discord.ui.TextInput(
        label="종료 시간 (HH:MM)",
        placeholder="21:00",
        default="21:00",
        max_length=5,
    )
    interval = discord.ui.TextInput(
        label="슬롯 간격 (분)",
        placeholder="30",
        default="30",
        max_length=3,
    )

    def __init__(self, mentor: dict, bot: commands.Bot) -> None:
        super().__init__()
        self.mentor = mentor
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            sh, sm = map(int, self.start_time.value.strip().split(":"))
            eh, em = map(int, self.end_time.value.strip().split(":"))
            ivl = int(self.interval.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed(
                    "형식이 올바르지 않습니다.\n시작/종료: `HH:MM` 형식 (예: `19:00`)\n간격: 숫자만 입력 (예: `30`)"
                ),
                ephemeral=True,
            )
            return

        if sh * 60 + sm >= eh * 60 + em:
            await interaction.response.send_message(
                embed=embeds.error_embed("종료 시간이 시작 시간보다 앞에 있습니다."), ephemeral=True
            )
            return
        if not (5 <= ivl <= 120):
            await interaction.response.send_message(
                embed=embeds.error_embed("간격은 5~120분 사이로 입력해주세요."), ephemeral=True
            )
            return

        await database.set_slot_template(self.mentor["id"], sh, sm, eh, em, ivl)

        slots_per_day = (eh * 60 + em - sh * 60 - sm) // ivl
        embed = discord.Embed(
            title="✅ 시간대 설정 완료",
            description=(
                f"**{self.start_time.value.strip()} ~ {self.end_time.value.strip()}** "
                f"/ {ivl}분 단위\n"
                f"하루 최대 **{slots_per_day}개** 슬롯\n\n"
                "이제 **[📅 슬롯 생성]** 버튼으로 날짜를 선택해 슬롯을 만드세요."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SlotGenerateModal(discord.ui.Modal, title="슬롯 생성"):
    date_from = discord.ui.TextInput(
        label="시작 날짜 (YYYY-MM-DD)",
        placeholder="2026-06-01",
        max_length=10,
    )
    date_to = discord.ui.TextInput(
        label="종료 날짜 (YYYY-MM-DD)",
        placeholder="2026-06-30",
        max_length=10,
    )

    def __init__(self, mentor: dict, bot: commands.Bot) -> None:
        super().__init__()
        self.mentor = mentor
        self.bot = bot
        # pre-fill sensible defaults
        today = date.today()
        self.date_from.default = today.isoformat()
        self.date_to.default = (today + timedelta(days=30)).isoformat()

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            d_from = date.fromisoformat(self.date_from.value.strip())
            d_to = date.fromisoformat(self.date_to.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("날짜 형식이 올바르지 않습니다. 예: `2026-06-01`"),
                ephemeral=True,
            )
            return

        if d_to < d_from:
            await interaction.response.send_message(
                embed=embeds.error_embed("종료 날짜가 시작 날짜보다 앞에 있습니다."), ephemeral=True
            )
            return
        if (d_to - d_from).days > 90:
            await interaction.response.send_message(
                embed=embeds.error_embed("한 번에 최대 90일까지 생성할 수 있습니다."), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        created, skipped = await database.generate_slots_for_range(
            self.mentor["id"], d_from, d_to
        )

        desc = [f"✅ 생성된 슬롯: **{created}개**"]
        if skipped:
            desc.append(f"🚫 예약 불가일로 건너뜀: **{skipped}일**")

        await interaction.followup.send(
            embed=discord.Embed(
                title="슬롯 생성 완료",
                description="\n".join(desc),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(self.bot)


# ── Slot clear confirmation view ──────────────────────────────────────────────

class SlotClearConfirmView(discord.ui.View):
    def __init__(self, mentor: dict, bot: commands.Bot) -> None:
        super().__init__(timeout=60)
        self.mentor = mentor
        self.bot = bot

    @discord.ui.button(label="✅ 확인 — 초기화", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        deleted, kept = await database.clear_slots(self.mentor["id"])

        lines = [f"🗑️ 삭제된 슬롯: **{deleted}개**"]
        if kept:
            lines.append(f"⚠️ 예약이 있어 유지된 슬롯: **{kept}개**")

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="슬롯 초기화 완료",
                description="\n".join(lines),
                color=discord.Color.green(),
            ),
            view=None,
        )

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(self.bot)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(description="초기화가 취소되었습니다.", color=discord.Color.blurple()),
            view=None,
        )


# ── Setup panel view ──────────────────────────────────────────────────────────

class MentorSetupView(discord.ui.View):
    def __init__(self, mentor: dict, template: dict | None, bot: commands.Bot) -> None:
        super().__init__(timeout=180)
        self.mentor = mentor
        self.template = template
        self.bot = bot

        # Disable slot generate if no template yet
        if template is None:
            for item in self.children:
                if hasattr(item, "label") and item.label == "📅 슬롯 생성":  # type: ignore[attr-defined]
                    item.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="⏰ 시간대 설정", style=discord.ButtonStyle.primary, row=0)
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = ScheduleSetModal(self.mentor, self.bot)
        if self.template:
            modal.start_time.default = (
                f"{self.template['start_hour']:02d}:{self.template['start_minute']:02d}"
            )
            modal.end_time.default = (
                f"{self.template['end_hour']:02d}:{self.template['end_minute']:02d}"
            )
            modal.interval.default = str(self.template["interval_minutes"])
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📅 슬롯 생성", style=discord.ButtonStyle.success, row=0)
    async def generate_slots(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.template:
            await interaction.response.send_message(
                embed=embeds.error_embed("먼저 **[⏰ 시간대 설정]** 을 완료해주세요."),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(SlotGenerateModal(self.mentor, self.bot))

    @discord.ui.button(label="🚫 예약 불가일", style=discord.ButtonStyle.secondary, row=0)
    async def block_dates(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from cogs.mentor import BlockDateView  # lazy import to avoid circular dependency

        blocked = await database.get_blocked_dates(self.mentor["id"])
        embed = discord.Embed(
            title="예약 불가일 지정",
            description="차단할 날짜를 선택하세요.",
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
            view=BlockDateView(self.mentor, blocked),
            ephemeral=True,
        )

    @discord.ui.button(label="📆 요일 차단", style=discord.ButtonStyle.secondary, row=1)
    async def block_weekdays(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from cogs.mentor import BlockWeekdayView

        blocked_wdays = await database.get_blocked_weekdays(self.mentor["id"])
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📆 예약 불가 요일 설정",
                description="매주 반복해서 예약을 받지 않을 요일을 선택하세요.\n선택하지 않으면 모든 요일이 차단 해제됩니다.",
                color=discord.Color.orange(),
            ),
            view=BlockWeekdayView(self.mentor, blocked_wdays),
            ephemeral=True,
        )

    @discord.ui.button(label="🗑️ 슬롯 초기화", style=discord.ButtonStyle.danger, row=1)
    async def clear_slots(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        slots = await database.get_slots_for_mentor(self.mentor["id"], active_only=True)
        slot_ids = [s["id"] for s in slots]
        bookings_map = await database.get_bookings_by_slot_ids(slot_ids)
        no_booking = sum(1 for s in slots if s["id"] not in bookings_map)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚠️ 슬롯 초기화",
                description=(
                    f"예약이 없는 슬롯 **{no_booking}개**가 삭제됩니다.\n"
                    + (f"예약이 있는 슬롯 **{len(bookings_map)}개**는 유지됩니다.\n" if bookings_map else "")
                    + "\n정말 초기화하시겠습니까?"
                ),
                color=discord.Color.red(),
            ),
            view=SlotClearConfirmView(self.mentor, self.bot),
            ephemeral=True,
        )

    @discord.ui.button(label="🔄 새로고침", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        template = await database.get_slot_template(self.mentor["id"])
        embed = await build_setup_embed(self.mentor, template)
        await interaction.response.edit_message(
            embed=embed,
            view=MentorSetupView(self.mentor, template, self.bot),
        )


async def build_setup_embed(mentor: dict, template: dict | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚙️ {mentor['name']} 멘토 설정 패널",
        color=discord.Color.from_str("#2B5CE6"),
    )

    # Schedule template
    if template:
        sh, sm = template["start_hour"], template["start_minute"]
        eh, em = template["end_hour"], template["end_minute"]
        ivl = template["interval_minutes"]
        slots_per_day = (eh * 60 + em - sh * 60 - sm) // ivl
        embed.add_field(
            name="⏰ 현재 시간대",
            value=f"`{sh:02d}:{sm:02d} ~ {eh:02d}:{em:02d}` / {ivl}분 단위 (하루 {slots_per_day}슬롯)",
            inline=False,
        )
    else:
        embed.add_field(
            name="⏰ 시간대",
            value="미설정 — **[⏰ 시간대 설정]** 버튼으로 먼저 설정하세요",
            inline=False,
        )

    # Slot stats
    slots = await database.get_slots_for_mentor(mentor["id"], active_only=True)
    slot_ids = [s["id"] for s in slots]
    bookings_map = await database.get_bookings_by_slot_ids(slot_ids)
    available = sum(1 for s in slots if s["id"] not in bookings_map)
    pending = sum(1 for b in bookings_map.values() if b.get("status") == "pending")
    approved = sum(1 for b in bookings_map.values() if b.get("status") == "approved")

    embed.add_field(
        name="🗓️ 슬롯 현황",
        value=(
            f"전체 활성: **{len(slots)}개**\n"
            f"🟢 신청 가능: **{available}개**\n"
            f"🟡 대기 중: **{pending}건**\n"
            f"✅ 확정: **{approved}건**"
        ),
        inline=True,
    )

    # Blocked dates
    blocked = await database.get_blocked_dates(mentor["id"])
    embed.add_field(
        name="🚫 예약 불가일",
        value="\n".join(f"• {d}" for d in blocked) if blocked else "없음",
        inline=True,
    )

    # Blocked weekdays
    _wd = ["월", "화", "수", "목", "금", "토", "일"]
    blocked_wdays = await database.get_blocked_weekdays(mentor["id"])
    embed.add_field(
        name="📆 예약 불가 요일",
        value=" · ".join(f"{_wd[w]}요일" for w in blocked_wdays) if blocked_wdays else "없음",
        inline=True,
    )

    embed.set_footer(text="아산 AX 멘토링 · 멘토 설정")
    return embed
