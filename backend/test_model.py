import asyncio
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv

load_dotenv(".env.local")
async def main():
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY") or "DUMMY"
    )
    try:
        response = await client.chat.completions.create(
            model="google/gemini-3.1-pro",
            messages=[{"role": "user", "content": "hello"}],
            response_format={"type": "json_object"}
        )
        print("Success:", response)
    except Exception as e:
        print("Exception:", e.__class__.__name__, e)

asyncio.run(main())
