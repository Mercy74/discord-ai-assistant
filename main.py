
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from ai_engine import ask_gemini

# Load private environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Discord configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"AI Assistant online: {bot.user}")
    print("Waiting for staff instructions...")


@bot.event
async def on_message(message):

    # Ignore bots and direct messages
    if message.author.bot or message.guild is None:
        return

    # Only respond when directly mentioned
    if bot.user not in message.mentions:
        await bot.process_commands(message)
        return

    # Temporary staff permission check
    is_staff = (
        message.author.guild_permissions.administrator
        or message.author.guild_permissions.manage_guild
    )

    if not is_staff:
        await message.reply(
            "Sorry, this assistant is currently restricted to server administrators and managers.",
            mention_author=False
        )
        return

    # Remove the bot mention from the message
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

    # Ask Gemini and send its response
    try:
        async with message.channel.typing():
            answer = await ask_gemini(prompt)

        await message.reply(
            answer[:1900],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

    except Exception as error:
        print(f"AI error: {error}")

        await message.reply(
            "I ran into an issue while contacting my AI service. Please try again later.",
            mention_author=False
        )

    await bot.process_commands(message)


# Start the bot
if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

bot.run(DISCORD_TOKEN)
