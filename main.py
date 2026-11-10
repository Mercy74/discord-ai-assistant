
import os
import asyncio
import time
import re

import discord
from discord.ext import commands
from dotenv import load_dotenv

from ai_engine import ask_groq
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

startup_test_complete = False


@bot.event
async def on_ready():
    global startup_test_complete

    print("DEBUG: Bot is ready!")
    print(f"AI Assistant online: {bot.user}")
    print("Waiting for staff instructions...")

    if not startup_test_complete:
        startup_test_complete = True

        try:
            print("DEBUG: Starting standalone Groq test...")

            result = await ask_groq(
                "Reply with exactly: RENDER GROQ TEST SUCCESSFUL"
            )

            print("GROQ STANDALONE TEST RESULT:", result)

        except Exception as error:
            print("GROQ STANDALONE TEST FAILED:", repr(error))


def find_member(guild, member_name):
    """Find a member by exact name or Discord mention."""

    mention_match = re.fullmatch(
        r"<@!?(\d+)>",
        member_name.strip()
    )

    if mention_match:
        return [guild.get_member(int(mention_match.group(1)))]

    search = member_name.strip().casefold()

    return [
        member for member in guild.members
        if search in {
            member.name.casefold(),
            member.display_name.casefold(),
            (member.global_name or "").casefold()
        }
    ]


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
                ask_groq(prompt),
                timeout=90
            )

        elapsed = time.perf_counter() - start_time
        print(f"Groq response time: {elapsed:.2f} seconds")

        # Handle role assignment and removal.
        action_type = answer.get("type")

        if action_type in {"assign_role", "remove_role"}:

            member_name = answer.get("member_name", "")
            role_name = answer.get("role_name", "")

            is_removal = action_type == "remove_role"

            action_word = "remove" if is_removal else "give"
            action_past = "removed" if is_removal else "assigned"

            members = find_member(message.guild, member_name)

            if not members or members[0] is None:
                await message.reply(
                    f"I couldn't find the member '{member_name}'.",
                    mention_author=False
                )
                return

            if len(members) > 1:
                await message.reply(
                    f"More than one member matches '{member_name}'. "
                    "Please use a Discord mention.",
                    mention_author=False
                )
                return

            member = members[0]

            roles = [
                role for role in message.guild.roles
                if role.name.casefold() == role_name.strip().casefold()
            ]

            if not roles:
                await message.reply(
                    f"I couldn't find the role '{role_name}'.",
                    mention_author=False
                )
                return

            if len(roles) > 1:
                await message.reply(
                    "I found multiple matching roles. "
                    "Please clarify which one you mean.",
                    mention_author=False
                )
                return

            role = roles[0]
            guild = message.guild
            bot_member = guild.me

            if bot_member is None:
                await message.reply(
                    "I couldn't verify my server permissions.",
                    mention_author=False
                )
                return

            if not bot_member.guild_permissions.manage_roles:
                await message.reply(
                    "I don't have permission to manage roles.",
                    mention_author=False
                )
                return

            if role.is_default() or role.managed:
                await message.reply(
                    "I cannot modify that role.",
                    mention_author=False
                )
                return

            if not is_removal and role.permissions.administrator:
                await message.reply(
                    "I cannot assign a role that grants Administrator access.",
                    mention_author=False
                )
                return

            if role >= bot_member.top_role:
                await message.reply(
                    "That role is above or equal to my highest role. "
                    "Please adjust my role hierarchy.",
                    mention_author=False
                )
                return

            if role >= message.author.top_role:
                await message.reply(
                    "You cannot authorize me to modify a role "
                    "that is above or equal to your highest role.",
                    mention_author=False
                )
                return

            if member.top_role >= bot_member.top_role:
                await message.reply(
                    "I cannot manage this member because their highest "
                    "role is above or equal to mine.",
                    mention_author=False
                )
                return

            if is_removal and role not in member.roles:
                await message.reply(
                    f"{member.display_name} does not have the "
                    f"{role.name} role.",
                    mention_author=False
                )
                return

            if not is_removal and role in member.roles:
                await message.reply(
                    f"{member.display_name} already has the "
                    f"{role.name} role.",
                    mention_author=False
                )
                return

            await message.reply(
                f"Please confirm: should I {action_word} **{role.name}** "
                f"{'from' if is_removal else 'to'} "
                f"**{member.display_name}**?\n\n"
                "Reply **yes** to confirm or **no** to cancel. "
                "You have 30 seconds.",
                mention_author=False
            )

            def confirmation_check(reply):
                return (
                    reply.author.id == message.author.id
                    and reply.channel.id == message.channel.id
                    and not reply.author.bot
                )

            try:
                confirmation = await bot.wait_for(
                    "message",
                    timeout=30,
                    check=confirmation_check
                )
            except asyncio.TimeoutError:
                await message.channel.send(
                    "Role modification cancelled because "
                    "confirmation timed out."
                )
                return

            if confirmation.content.strip().casefold() not in {
                "yes", "y", "confirm"
            }:
                await message.channel.send(
                    "Role modification cancelled."
                )
                return

            # Recheck permissions and server information.
            bot_member = guild.me

            if (
                not bot_member
                or not bot_member.guild_permissions.manage_roles
                or role >= bot_member.top_role
                or role >= message.author.top_role
                or role not in guild.roles
                or guild.get_member(member.id) is None
                or member.top_role >= bot_member.top_role
            ):
                await message.channel.send(
                    "The role modification could not be completed "
                    "because permissions or server information changed."
                )
                return

            if is_removal:
                if role not in member.roles:
                    await message.channel.send(
                        "That member no longer has this role."
                    )
                    return

                await member.remove_roles(
                    role,
                    reason=f"Confirmed by {message.author}"
                )

            else:
                if role.permissions.administrator:
                    await message.channel.send(
                        "I cannot assign a role that grants Administrator access."
                    )
                    return

                if role in member.roles:
                    await message.channel.send(
                        "That member already has this role."
                    )
                    return

                await member.add_roles(
                    role,
                    reason=f"Confirmed by {message.author}"
                )

            await message.channel.send(
                f"Successfully {action_past} **{role.name}** "
                f"{'from' if is_removal else 'to'} "
                f"**{member.display_name}**."
            )

            print(
                f"ROLE {action_past.upper()}: {role.name} "
                f"{'from' if is_removal else '->'} "
                f"{member.display_name} by {message.author}"
            )

            return

        # Handle ordinary AI responses.
        await message.reply(
            answer.get("content", "I couldn't generate a response.")[:1900],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none()
        )

    except asyncio.TimeoutError:
        print("AI TIMEOUT: Groq did not respond within 90 seconds.")

        await message.reply(
            "My AI service is taking too long to respond. Please try again.",
            mention_author=False
        )

    except discord.Forbidden:
        print("DISCORD ERROR: Missing permission to perform this action.")

        await message.reply(
            "I don't have the Discord permissions needed to complete that action.",
            mention_author=False
        )

    except Exception as error:
        print(f"AI ERROR TYPE: {type(error).__name__}")
        print(f"AI ERROR DETAILS: {repr(error)}")

        await message.reply(
            "I ran into an issue while processing your request. "
            "Please try again later.",
            mention_author=False
        )


if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

keep_alive()
bot.run(DISCORD_TOKEN)
