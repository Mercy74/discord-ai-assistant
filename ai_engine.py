
import os

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL_NAME = "openai/gpt-oss-120b"

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY environment variable")

client = AsyncGroq(
    api_key=GROQ_API_KEY
)


async def ask_groq(message: str) -> str:
    """Send a message to Groq and return its response."""

    try:
        print("DEBUG: Sending request to Groq API...")

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intelligent assistant for a Discord server. "
                        "Understand the user's requests carefully. "
                        "Be helpful, conversational, and concise. "
                        "Never claim you have changed server settings, roles, "
                        "channels, or members. You cannot perform Discord "
                        "actions yet."
                    )
                },
                {
                    "role": "user",
                    "content": message
                }
            ],
            max_completion_tokens=1000
        )

        print("DEBUG: Groq returned a response.")

        return (
            response.choices[0].message.content
            or "I couldn't generate a response."
        )

    except Exception as error:
        print(f"GROQ ERROR TYPE: {type(error).__name__}")
        print(f"GROQ ERROR DETAILS: {repr(error)}")
        raise
