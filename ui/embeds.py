import discord


BRAND_COLOR = discord.Color.from_str("#2B5CE6")
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
WARNING_COLOR = discord.Color.orange()
NEUTRAL_COLOR = discord.Color.blurple()


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
        embed.add_field(
            name=f"#{m['id']}  {m['name']}",
            value=m["bio"] or "소개 없음",
            inline=False,
        )
    embed.set_footer(text="아산 AX 멘토링 예약 시스템")
    return embed


def slot_list_embed(
    mentor: dict,
    slots: list[dict],
    bookings_map: dict[int, dict],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{mentor['name']} 멘토 예약 가능 시간",
        color=BRAND_COLOR,
    )
    if not slots:
        embed.description = "현재 예약 가능한 슬롯이 없습니다."
        return embed

    lines = []
    for s in slots:
        booking = bookings_map.get(s["id"])
        if booking:
            status = f"예약됨 (@{booking['user_name']})"
            icon = "🔴"
        else:
            status = "예약 가능"
            icon = "🟢"
        lines.append(f"{icon} `[{s['id']}]` **{s['label']}** — {status}")

    # Discord embed description limit: 4096 chars
    description = ""
    for line in lines:
        if len(description) + len(line) + 1 > 4000:
            description += "\n*... 슬롯이 너무 많아 일부만 표시됩니다. 메뉴에서 선택하세요.*"
            break
        description += line + "\n"

    embed.description = description.strip()
    embed.set_footer(text="아래 메뉴에서 슬롯을 선택하세요 · 아산 AX 멘토링")
    return embed


def booking_confirm_embed(slot: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="예약 확인",
        description="아래 내용으로 예약하시겠습니까?",
        color=WARNING_COLOR,
    )
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=slot["label"], inline=True)
    embed.set_footer(text="60초 내에 확인해주세요 · 아산 AX 멘토링")
    return embed


def booking_success_embed(slot: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="예약 완료!",
        description=f"**{mentor['name']}** 멘토와의 멘토링 세션이 예약되었습니다.",
        color=SUCCESS_COLOR,
    )
    embed.add_field(name="시간", value=slot["label"], inline=False)
    embed.set_footer(text="아산 AX 멘토링 예약 시스템")
    return embed


def booking_taken_embed() -> discord.Embed:
    return discord.Embed(
        title="예약 실패",
        description="방금 다른 사람이 해당 슬롯을 예약했습니다. 다른 시간을 선택해주세요.",
        color=ERROR_COLOR,
    )


def no_booking_embed() -> discord.Embed:
    return discord.Embed(
        title="예약 없음",
        description="현재 예약된 멘토링 세션이 없습니다.",
        color=NEUTRAL_COLOR,
    )


def my_booking_embed(booking: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="나의 예약",
        color=BRAND_COLOR,
    )
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=booking["label"], inline=True)
    embed.add_field(name="예약 일시", value=booking["booked_at"], inline=False)
    embed.set_footer(text="/cancel 명령으로 취소할 수 있습니다 · 아산 AX 멘토링")
    return embed


def cancel_confirm_embed(booking: dict, mentor: dict) -> discord.Embed:
    embed = discord.Embed(
        title="예약 취소 확인",
        description="아래 예약을 취소하시겠습니까?",
        color=WARNING_COLOR,
    )
    embed.add_field(name="멘토", value=mentor["name"], inline=True)
    embed.add_field(name="시간", value=booking["label"], inline=True)
    embed.set_footer(text="60초 내에 확인해주세요 · 아산 AX 멘토링")
    return embed


def cancel_success_embed() -> discord.Embed:
    return discord.Embed(
        title="예약 취소 완료",
        description="멘토링 예약이 취소되었습니다.",
        color=SUCCESS_COLOR,
    )


def admin_bookings_embed(bookings: list[dict], page: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"전체 예약 현황 (페이지 {page}/{total_pages})",
        color=BRAND_COLOR,
    )
    if not bookings:
        embed.description = "예약 내역이 없습니다."
        return embed
    lines = []
    for b in bookings:
        lines.append(
            f"슬롯 `{b['slot_id']}` | **{b['mentor_name']}** | {b['label']} | @{b['user_name']} | {b['booked_at']}"
        )
    embed.description = "\n".join(lines)
    embed.set_footer(text="아산 AX 멘토링 관리자")
    return embed


def admin_slot_removed_embed(slot_id: int, had_booking: bool) -> discord.Embed:
    desc = f"슬롯 `{slot_id}`이(가) 비활성화되었습니다."
    if had_booking:
        desc += "\n예약자의 예약도 함께 취소되었습니다."
    return discord.Embed(title="슬롯 제거 완료", description=desc, color=SUCCESS_COLOR)


def error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="오류", description=message, color=ERROR_COLOR)
