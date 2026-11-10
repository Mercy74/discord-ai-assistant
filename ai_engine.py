import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL_NAME = "models/gemini-3.8-flash"

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY environment variable")

client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        timeout=30000
    )
)


async def ask_gemini(message: str) -> str:
    """Send a message to Gemini and return its response."""

    try:
        print("DEBUG: Sending request to Gemini Interactions API...")

        response = await client.aio.interactions.create(
            model=MODEL_NAME,
            input=message,
            system_instruction=(
                "You are an intelligent assistant for a Discord server. "
                "Understand the user's requests carefully. "
                "Be helpful, conversational, and concise. "
                "Never claim you have changed server settings, "
                "roles, channels, or members. You cannot perform "
                "Discord actions yet."
            )
        )

        print("DEBUG: Gemini returned a response.")

        return response.output_text or "I couldn't generate a response."

    except Exception as error:
        print(f"GEMINI ERROR TYPE: {type(error).__name__}")
        print(f"GEMINI ERROR DETAILS: {repr(error)}")
        raise
