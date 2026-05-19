import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
GUILD_ID: int = int(os.environ["GUILD_ID"])
ADMIN_ROLE_ID: int = int(os.environ["ADMIN_ROLE_ID"])
DB_PATH: str = os.getenv("DB_PATH", "data/mentoring.db")
SYNC_GLOBALLY: bool = os.getenv("SYNC_GLOBALLY", "false").lower() == "true"

# ── Onboarding ────────────────────────────────────────────────────────────────
# Role assigned immediately on join (restricted access)
STUDENT_ROLE_ID: int = int(os.getenv("STUDENT_ROLE_ID", "1503760182281244743"))
# Channel where the welcome+onboarding message is pinned
ONBOARDING_CHANNEL_ID: int = int(os.environ["ONBOARDING_CHANNEL_ID"])
# Channel where members post their self-introductions
INTRO_CHANNEL_ID: int = int(os.environ["INTRO_CHANNEL_ID"])
# Role granted after self-intro is submitted (unlocks full access); optional
_ONBOARDING_COMPLETE_ROLE_ID: str = os.getenv("ONBOARDING_COMPLETE_ROLE_ID", "")
ONBOARDING_COMPLETE_ROLE_ID: int | None = int(_ONBOARDING_COMPLETE_ROLE_ID) if _ONBOARDING_COMPLETE_ROLE_ID else None
