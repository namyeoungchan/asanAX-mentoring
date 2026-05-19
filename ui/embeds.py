from datetime import date as date_cls

import discord


BRAND_COLOR = discord.Color.from_str("#2B5CE6")
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
WARNING_COLOR = discord.Color.orange()
NEUTRAL_COLOR = discord.Color.blurple()

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _date_label(ds: str) -> str:
    d = date_cls.fromisoformat(ds)
    return f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"


def _hm(iso: str) -> str:
    return iso[11:16]


# ── Panel / list embeds ───────────────────────────────────────────────────────

def mentor_list_embed(mentors: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="멘토 목록",
        description="아산 AX 멘토 목록입니다. `/book` 명령으로 예약하세요.",
        color=BRAND_COLOR,
    )
    if not mentors:
        embed.description = "등록된 멘토가 없습니다."
        return embed
    for m in mentors:
        embed.add_field(name=f"#{m['id']}  {m['name']}", value=m["bio"] or "소개 없음", inline=False)
    embed.set_footer(text="아산 AX 멘토링 예약 시스템")
    return embed


def slot_list_embed(mentor: dict, slots: list[dict], bookings_map: dict[int, dict]) -> discord.Embed:
    embed = discord.Embed(title=f"{mentor['name']} 멘토 예약 가능 시간", color=BRAND_COLOR)
    if not slots:
        embed.description = "현재 예약 가능한 슬롯이 없습니다."
        return embed

    lines = []
    for s in slots:
        booking = bookings_map.get(s["id"])
        if booking:
            status_text = booking.get("status", "")
            if status_text == "pending":
                icon, label = "🟡", f"대기 중 (@{booking['user_name']})"
            else:
                icon, label = "🔴", f"확정됨 (@{booking['user_name']})"
        else:
            icon, label = "🟢", "신청 가능"
        lines.append(f"{icon} `[{s['id']}]` **{s['label']}** — {label}")

    description = ""
    for line in lines:
        if len(description) + len(line) + 1 > 4000:
            description += "\n*... 슬롯이 너무 많아 일부만 표시됩니다. 메뉴에서 선택하세요.*"
            break
        description += line + "\n"

    embed.description = description.strip()
    embed.set_footer(text="아래 메뉴에서 슬롯을 선택하세요 · 아산 AX 멘토링")
    return embed


# ── Date / time select embeds ─────────────────────────────────────────────────

def date_select_embed(mentor: dict, dates: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mentor['name']} 멘토 멘토링 신청",
        color=BRAND_COLOR,
    )
    embed.description = mentor["bio"] or "소개 없음"
    if dates:
        embed.add_field(
            name="📅 예약 가능 날짜",
            value="\n".join(f"• {_date_label(d)}" for d in dates[:10])
                  + ("\n..." if len(dates) > 10 else ""),
            inline=False,
        )
        embed.set_footer(text="아래 메뉴에서 날짜를 선택하세요 · 아산 AX 멘토링")
    else:
        embed.add_field(name="예약 가능한 날짜 없음", value="현재 신청 가능한 날짜가 없습니다.", inline=False)
    return embed


def time_slot_embed(mentor: dict, selected_date: str, slots: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mentor['name']} 멘토 — {_date_label(selected_date)}",
        color=BRAND_COLOR,
    )
    if not slots:
        embed.description = "이 날짜에 등록된 슬롯이 없습니다."
        return embed

    lines = []
    for s in slots:
        status = s.get("booking_status")
        start, end = _hm(s["start_time"]), _hm(s["end_time"])
        if status == "pending":
            lines.append(f"🟡 **{start} ~ {end}** — 대기 중")
        elif status == "approved":
            lines.append(f"🔴 **{start} ~ {end}** — 확정됨")
        else:
            lines.append(f"🟢 **{start} ~ {end}** — 신청 가능")

    embed.description = "\n".join(lines)
    embed.set_footer(text="🟢 신청 가능  🟡 대기 중  🔴 확정됨 · 아산 AX 멘토링")
    return embed


# ── Booking request flow ──────────────────────────────────────────────────────

def booking_request_confirm_embed(slot: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="멘토링 신청 확인",
        description="아래 내용으로 멘토링을 신청하시겠습니까?\n멘토 승인 후 확정됩니다.",
        color=WARNING_COLOR,
    )
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=slot["label"], inline=True)
    embed.set_footer(text="60초 내에 확인해주세요 · 아산 AX 멘토링")
    return embed


def booking_request_sent_embed(slot: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="신청 완료 ⏳",
        description=(
            f"**{mentor['name']}** 멘토에게 신청이 전달되었습니다.\n"
            "멘토 승인 후 DM으로 알려드립니다."
        ),
        color=NEUTRAL_COLOR,
    )
    embed.add_field(name="시간", value=slot["label"], inline=False)
    embed.set_footer(text="/mybooking 으로 신청 현황을 확인하세요 · 아산 AX 멘토링")
    return embed


def booking_taken_embed() -> discord.Embed:
    return discord.Embed(
        title="신청 실패",
        description="방금 다른 사람이 해당 슬롯을 신청했습니다. 다른 시간을 선택해주세요.",
        color=ERROR_COLOR,
    )


# ── Mentor DM embeds ──────────────────────────────────────────────────────────

def mentor_notification_embed(slot: dict, user: discord.User | discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="📬 새 멘토링 신청",
        description=f"**{user.display_name}** 님이 멘토링을 신청했습니다.",
        color=BRAND_COLOR,
    )
    embed.add_field(name="신청자", value=f"{user.display_name} ({user.mention})", inline=True)
    embed.add_field(name="시간", value=slot["label"], inline=True)
    embed.set_footer(text="승인 또는 반려를 선택하세요 · 아산 AX 멘토링")
    return embed


def approval_done_embed(
    approved: bool,
    user_name: str,
    reason: str = "",
    alternative: str = "",
) -> discord.Embed:
    if approved:
        return discord.Embed(
            title="✅ 승인 완료",
            description=f"**{user_name}** 님의 신청을 승인했습니다.\n신청자에게 DM으로 알림이 전송되었습니다.",
            color=SUCCESS_COLOR,
        )
    embed = discord.Embed(
        title="❌ 반려 완료",
        description=f"**{user_name}** 님의 신청을 반려했습니다.\n신청자에게 DM으로 알림이 전송되었습니다.",
        color=ERROR_COLOR,
    )
    if reason:
        embed.add_field(name="반려 사유", value=reason, inline=False)
    if alternative:
        embed.add_field(name="제안한 대안 일정", value=alternative, inline=False)
    return embed


# ── User DM embeds ────────────────────────────────────────────────────────────

def booking_approved_embed(slot: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="✅ 멘토링 신청 승인!",
        description=f"**{mentor['name']}** 멘토가 신청을 승인했습니다.",
        color=SUCCESS_COLOR,
    )
    embed.add_field(name="확정 시간", value=slot["label"], inline=False)
    embed.set_footer(text="아산 AX 멘토링")
    return embed


def booking_rejected_embed(
    slot: dict,
    mentor: dict,
    reason: str = "",
    alternative: str = "",
) -> discord.Embed:
    embed = discord.Embed(
        title="❌ 멘토링 신청 반려",
        description=f"**{mentor['name']}** 멘토가 신청을 반려했습니다.",
        color=ERROR_COLOR,
    )
    embed.add_field(name="신청한 시간", value=slot["label"], inline=False)
    if reason:
        embed.add_field(name="반려 사유", value=reason, inline=False)
    if alternative:
        embed.add_field(
            name="💡 멘토가 제안한 대안 일정",
            value=f"{alternative}\n\nDiscord에서 다시 `/book` 으로 신청하거나 멘토에게 직접 문의하세요.",
            inline=False,
        )
    else:
        embed.add_field(name="안내", value="다른 시간으로 다시 신청해주세요.", inline=False)
    embed.set_footer(text="아산 AX 멘토링")
    return embed


# ── My booking / cancel ───────────────────────────────────────────────────────

def no_booking_embed() -> discord.Embed:
    return discord.Embed(
        title="신청 없음",
        description="현재 신청한 멘토링 세션이 없습니다.",
        color=NEUTRAL_COLOR,
    )


def my_booking_embed(booking: dict, mentor: dict) -> discord.Embed:
    status = booking.get("status", "approved")
    if status == "pending":
        status_text = "⏳ 승인 대기 중"
        color = WARNING_COLOR
    else:
        status_text = "✅ 확정됨"
        color = SUCCESS_COLOR

    embed = discord.Embed(title="나의 멘토링 신청", color=color)
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=booking["label"], inline=True)
    embed.add_field(name="상태", value=status_text, inline=True)
    embed.add_field(name="신청 일시", value=booking["booked_at"], inline=False)
    embed.set_footer(text="/cancel 명령으로 취소할 수 있습니다 · 아산 AX 멘토링")
    return embed


def cancel_confirm_embed(booking: dict, mentor: dict) -> discord.Embed:
    status = booking.get("status", "approved")
    desc = "아래 신청을 취소하시겠습니까?"
    if status == "pending":
        desc += "\n(아직 승인 대기 중인 신청입니다)"
    embed = discord.Embed(title="신청 취소 확인", description=desc, color=WARNING_COLOR)
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=booking["label"], inline=True)
    embed.set_footer(text="60초 내에 확인해주세요 · 아산 AX 멘토링")
    return embed


def cancel_success_embed() -> discord.Embed:
    return discord.Embed(title="신청 취소 완료", description="멘토링 신청이 취소되었습니다.", color=SUCCESS_COLOR)


# ── Admin embeds ──────────────────────────────────────────────────────────────

def admin_bookings_embed(bookings: list[dict], page: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(title=f"전체 예약 현황 (페이지 {page}/{total_pages})", color=BRAND_COLOR)
    if not bookings:
        embed.description = "예약 내역이 없습니다."
        return embed
    lines = []
    for b in bookings:
        status_icon = "⏳" if b.get("status") == "pending" else "✅"
        lines.append(
            f"{status_icon} `{b['slot_id']}` | **{b['mentor_name']}** | {b['label']} | @{b['user_name']}"
        )
    embed.description = "\n".join(lines)
    embed.set_footer(text="⏳ 대기중  ✅ 확정 · 아산 AX 멘토링 관리자")
    return embed


def admin_slot_removed_embed(slot_id: int, had_booking: bool) -> discord.Embed:
    desc = f"슬롯 `{slot_id}`이(가) 비활성화되었습니다."
    if had_booking:
        desc += "\n예약자의 신청도 함께 취소되었습니다."
    return discord.Embed(title="슬롯 제거 완료", description=desc, color=SUCCESS_COLOR)


# ── Legacy compat (slot_select still uses this) ───────────────────────────────

def booking_confirm_embed(slot: dict, mentor: dict) -> discord.Embed:
    return booking_request_confirm_embed(slot, mentor)


def booking_success_embed(slot: dict, mentor: dict) -> discord.Embed:
    return booking_approved_embed(slot, mentor)


def error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="오류", description=message, color=ERROR_COLOR)


# ── Reminder embeds ───────────────────────────────────────────────────────────

def reminder_embed(booking: dict, reminder_type: str, for_mentor: bool = False) -> discord.Embed:
    label = booking["label"]
    name = booking["mentor_name"] if not for_mentor else booking["user_name"]

    titles = {
        "day_before": "📅 멘토링 세션 하루 전 알림",
        "day_of":     "☀️ 멘토링 세션 당일 알림",
        "hour_before": "⏰ 멘토링 세션 1시간 전 알림",
    }
    descs = {
        "day_before": "내일 멘토링 세션이 있습니다. 잊지 마세요!",
        "day_of":     "오늘 멘토링 세션이 있습니다. 준비하세요!",
        "hour_before": "1시간 후 멘토링 세션이 시작됩니다!",
    }

    embed = discord.Embed(
        title=titles.get(reminder_type, "멘토링 알림"),
        description=descs.get(reminder_type, ""),
        color=BRAND_COLOR,
    )
    embed.add_field(
        name="멘토" if not for_mentor else "신청자",
        value=name,
        inline=True,
    )
    embed.add_field(name="시간", value=label, inline=True)
    embed.set_footer(text="아산 AX 멘토링")
    return embed
