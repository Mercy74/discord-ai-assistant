
import os
import asyncio
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from ai_engine import ask_gemini
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print("DEBUG: Bot is ready!")
    print(f"AI Assistant online: {bot.user}")
    print("Waiting for staff instructions...")


@bot.event
async def on_message(message):
    print("DEBUG: Message event received!")

    if message.author.bot or message.guild is None:
        return

    if bot.user not in message.mentions:
        await bot.process_commands(message)
        return

    is_staff = (
        message.author.guild_permissions.administrator
        or message.author.guild_permissions.manage_guild
    )

    if not is_staff:
        await message.reply(
            "Sorry, this assistant is currently restricted "
            "to server administrators and managers.",
            mention_author=False
        )
        return

    prompt = message.content.replace(
        f"<@{bot.user.id}>", ""
    ).replace(
        f"<@!{bot.user.id}>", ""
    ).strip()

    if not prompt:
        await message.reply(
            "What would you like help with?",
            mention_author=False
        )
        return

    
    try:
        start_time = time.perf_counter()

        async with message.channel.typing():
            answer = await asyncio.wait_for(
                ask_gemini(prompt),
                timeout=30
            )

        elapsed = time.perf_counter() - start_time
        print(f"Gemini response time: {elapsed:.2f} seconds")

        await message.reply(
            answer[:1900],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

    except asyncio.TimeoutError:
        print("AI TIMEOUT: Gemini did not respond within 30 seconds.")

        await message.reply(
            "My AI service is taking too long to respond. Please try again.",
            mention_author=False
        )

    except Exception as error:
        print(f"AI ERROR TYPE: {type(error).__name__}")
        print(f"AI ERROR DETAILS: {repr(error)}")

        await message.reply(
    "I ran into an issue while contacting my AI service. "
    "Please try again later.",
    mention_author=False
)



if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

keep_alive()
bot.run(DISCORD_TOKEN)
