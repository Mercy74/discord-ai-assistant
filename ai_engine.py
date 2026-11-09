
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load private settings
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL_NAME = "gemini-3.8-flash"

# Connect to Gemini
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY environment variable")

client = genai.Client(api_key=GEMINI_API_KEY)


async def ask_gemini(message: str) -> str:
    """
    Send a message to Gemini and return its response.
    """

    response = await client.aio.models.generate_content(
        model=MODEL_NAME,
        contents=message,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are an intelligent assistant for a Discord server. "
                "Understand the user's requests carefully. "
                "Be helpful, conversational, and concise. "
                "Never claim you have changed server settings, "
                "roles, channels, or members. You cannot perform "
                "Discord actions yet."
            ),
            temperature=0.3,
            max_output_tokens=500
        )
    )

    return response.text or "I couldn't generate a response."
