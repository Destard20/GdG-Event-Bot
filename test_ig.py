import asyncio
from core.instagram import publish_instagram_story

async def main():
    print("Testing Instagram Publishing...")
    # A public URL to a random test image (Wikimedia Commons placeholder)
    test_image_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/React-icon.svg/1080px-React-icon.svg.png"
    
    success, msg = await publish_instagram_story(test_image_url)
    if success:
        print(f"SUCCESS: {msg}")
    else:
        print(f"FAILED: {msg}")

if __name__ == '__main__':
    asyncio.run(main())
