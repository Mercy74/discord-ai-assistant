
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load private environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Discord bot configuration
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
    print("Waiting for instructions...")


@bot.event
async def on_message(message):

    # Ignore the bot's own messages
    if message.author == bot.user:
        return

    # Ignore other bots
    if message.author.bot:
        return

    # Only respond when mentioned
    if bot.user.mentioned_in(message):

        await message.channel.send(
            f"Hello {message.author.mention}! "
            "I'm your AI server assistant. "
            "My AI brain is being connected!"
        )

    await bot.process_commands(message)


# Start the bot
if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

bot.run(DISCORD_TOKEN)
