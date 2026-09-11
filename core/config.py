import os
from dotenv import load_dotenv

# Support both .environments and .env
if os.path.exists(".environments"):
    load_dotenv(dotenv_path=".environments")
else:
    load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")

PUBLIC_CHANNEL_ID = os.getenv("PUBLIC_CHANNEL_ID")
DISCUSSION_GROUP_ID = os.getenv("DISCUSSION_GROUP_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_POST_CATEGORY = os.getenv("WP_POST_CATEGORY")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")

MAX_EVENTS_PER_ROW = int(os.getenv("MAX_EVENTS_PER_ROW", "0"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_DATA_DIR = os.path.join(PROJECT_ROOT, "data")

DATA_DIR = os.getenv("DATA_DIR", DEFAULT_DATA_DIR)
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

FONTS_DIR = os.path.join(PROJECT_ROOT, "data") # Fonts remain in the project's data folder

DB_PATH = os.path.join(DATA_DIR, "bot_database.db")

LOGS_DIR = os.path.join(DATA_DIR, "logs")
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR, exist_ok=True)

