import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
GUILD_ID: int = int(os.environ["GUILD_ID"])
ADMIN_ROLE_ID: int = int(os.environ["ADMIN_ROLE_ID"])
DB_PATH: str = os.getenv("DB_PATH", "data/mentoring.db")
SYNC_GLOBALLY: bool = os.getenv("SYNC_GLOBALLY", "false").lower() == "true"
