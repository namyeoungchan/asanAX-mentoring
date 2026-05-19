from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
