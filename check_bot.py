import asyncio
from core.config import TELEGRAM_BOT_TOKEN, PUBLIC_CHANNEL_ID
from telegram import Bot

async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        chat = await bot.get_chat(chat_id=PUBLIC_CHANNEL_ID)
        print(f"Success! Bot can see channel: {chat.title}")
    except Exception as e:
        print(f"Error accessing channel: {e}")

if __name__ == '__main__':
    asyncio.run(main())
