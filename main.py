
import os
import asyncio
import time
import re

from datetime import timedelta

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


def find_target_channel(guild, current_channel, prompt, channel_name):
    """Resolve a channel mention, current channel reference, or exact name."""

    mention_match = re.search(r"<#(\d+)>", prompt)

    if mention_match:
        channel = guild.get_channel(int(mention_match.group(1)))

        if isinstance(channel, discord.TextChannel):
            return channel

        return None

    current_channel_phrases = re.search(
        r"\b(this channel|current channel|in here|to here|"
        r"post here|send here|put it here|post it here|send it here)\b",
        prompt,
        re.IGNORECASE
    )

    if current_channel_phrases:
        if isinstance(current_channel, discord.TextChannel):
            return current_channel

        return None

    search = channel_name.strip().lstrip("#").casefold()

    matches = [
        channel for channel in guild.text_channels
        if channel.name.casefold() == search
    ]

    if len(matches) == 1:
        return matches[0]

    return None


async def get_confirmation(message, description):
    """Ask the staff member to confirm an action."""

    await message.reply(
        f"**Please confirm this action:**\n\n"
        f"{description}\n\n"
        "Reply **yes** to confirm or **no** to cancel. "
        "You have 30 seconds.",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none()
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
            "Action cancelled because confirmation timed out."
        )
        return False

    if confirmation.content.strip().casefold() not in {
        "yes", "y", "confirm"
    }:
        await message.channel.send("Action cancelled.")
        return False

    return True


def check_member_hierarchy(guild, member, staff_member, bot_member):
    """Check whether the bot and staff member can act on this member."""

    if member.id == guild.owner_id:
        return "The server owner cannot be targeted by this action."

    if member.id == bot_member.id:
        return "I cannot perform this action on myself."

    if member.id == staff_member.id:
        return "You cannot use this assistant to perform this action on yourself."

    if member.top_role >= bot_member.top_role:
        return (
            "I cannot manage this member because their highest role "
            "is above or equal to mine."
        )

    if member.top_role >= staff_member.top_role:
        return (
            "You cannot authorize an action against a member whose "
            "highest role is above or equal to yours."
        )

    return None


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

        ai_prompt = (
            f"Current Discord channel: #{message.channel.name} "
            f"(ID: {message.channel.id}). "
            "If staff say 'here', 'this channel', or 'current channel', "
            "they mean this channel.\n\n"
            f"Staff instruction: {prompt}"
        )

        async with message.channel.typing():
            answer = await asyncio.wait_for(
                ask_groq(ai_prompt),
                timeout=90
            )

        elapsed = time.perf_counter() - start_time
        print(f"Groq response time: {elapsed:.2f} seconds")

        action_type = answer.get("type")

        # -----------------------------------------
        # CHANNEL MESSAGES
        # -----------------------------------------

        if action_type == "send_message":

            channel_name = answer.get("channel_name", "").strip()
            message_content = answer.get("message_content", "").strip()

            target_channel = find_target_channel(
                message.guild,
                message.channel,
                prompt,
                channel_name
            )

            if target_channel is None:
                await message.reply(
                    "I couldn't identify the requested text channel. "
                    "Please mention the channel or give me its exact name.",
                    mention_author=False
                )
                return

            if not message_content:
                await message.reply(
                    "I couldn't prepare a message to send.",
                    mention_author=False
                )
                return

            if len(message_content) > 1900:
                await message.reply(
                    "That message is too long to send safely. "
                    "Please shorten it.",
                    mention_author=False
                )
                return

            bot_member = message.guild.me

            if bot_member is None:
                await message.reply(
                    "I couldn't verify my server permissions.",
                    mention_author=False
                )
                return

            permissions = target_channel.permissions_for(bot_member)

            if not permissions.view_channel or not permissions.send_messages:
                await message.reply(
                    "I don't have permission to send messages in that channel.",
                    mention_author=False
                )
                return

            confirmed = await get_confirmation(
                message,
                f"**Action:** Send a message\n"
                f"**Channel:** {target_channel.mention}\n"
                f"**Message:**\n{message_content}"
            )

            if not confirmed:
                return

            bot_member = message.guild.me

            if (
                bot_member is None
                or message.guild.get_channel(target_channel.id) is None
            ):
                await message.channel.send(
                    "I can no longer access that channel."
                )
                return

            permissions = target_channel.permissions_for(bot_member)

            if not permissions.view_channel or not permissions.send_messages:
                await message.channel.send(
                    "I can no longer send messages in that channel."
                )
                return

            await target_channel.send(
                message_content,
                allowed_mentions=discord.AllowedMentions.none()
            )

            await message.channel.send(
                f"Successfully sent your message to {target_channel.mention}."
            )

            print(
                f"CHANNEL MESSAGE SENT: #{target_channel.name} "
                f"by {message.author}"
            )

            return

        # -----------------------------------------
        # ROLE ASSIGNMENT AND REMOVAL
        # -----------------------------------------

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
                    "That role is above or equal to my highest role.",
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

            if member.top_role >= message.author.top_role:
                await message.reply(
                    "You cannot authorize an action against a member "
                    "whose highest role is above or equal to yours.",
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

            confirmed = await get_confirmation(
                message,
                f"**Action:** {'Remove' if is_removal else 'Assign'} role\n"
                f"**Role:** {role.name}\n"
                f"**Member:** {member.display_name}"
            )

            if not confirmed:
                return

            bot_member = guild.me

            if (
                not bot_member
                or not bot_member.guild_permissions.manage_roles
                or role >= bot_member.top_role
                or role >= message.author.top_role
                or role not in guild.roles
                or guild.get_member(member.id) is None
                or member.top_role >= bot_member.top_role
                or member.top_role >= message.author.top_role
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

        # -----------------------------------------
        # MEMBER BANS
        # -----------------------------------------

        if action_type == "ban_member":

            member_name = answer.get("member_name", "")
            reason = answer.get("reason", "No reason provided")

            members = find_member(message.guild, member_name)

            if not members or members[0] is None:
                await message.reply(
                    f"I couldn't find the member '{member_name}'.",
                    mention_author=False
                )
                return

            if len(members) > 1:
                await message.reply(
                    "More than one member matches that name. "
                    "Please use a Discord mention.",
                    mention_author=False
                )
                return

            member = members[0]
            guild = message.guild
            bot_member = guild.me

            if bot_member is None:
                await message.reply(
                    "I couldn't verify my server permissions.",
                    mention_author=False
                )
                return

            if not bot_member.guild_permissions.ban_members:
                await message.reply(
                    "I don't have permission to ban members.",
                    mention_author=False
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.reply(
                    hierarchy_error,
                    mention_author=False
                )
                return

            confirmed = await get_confirmation(
                message,
                f"**Action:** Permanently ban member\n"
                f"**Member:** {member.display_name}\n"
                f"**Reason:** {reason}\n\n"
                "**Warning:** This will remove the member from the server."
            )

            if not confirmed:
                return

            bot_member = guild.me

            if (
                bot_member is None
                or not bot_member.guild_permissions.ban_members
                or guild.get_member(member.id) is None
            ):
                await message.channel.send(
                    "The ban could not be completed because "
                    "permissions or member information changed."
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.channel.send(hierarchy_error)
                return

            await guild.ban(
                member,
                reason=f"{reason} | Confirmed by {message.author}",
                delete_message_seconds=0
            )

            await message.channel.send(
                f"Successfully banned **{member.display_name}**."
            )

            print(
                f"MEMBER BANNED: {member} by {message.author}. "
                f"Reason: {reason}"
            )

            return

        # -----------------------------------------
        # MEMBER TIMEOUTS
        # -----------------------------------------

        if action_type == "timeout_member":

            member_name = answer.get("member_name", "")
            duration_minutes = answer.get("duration_minutes")
            reason = answer.get("reason", "No reason provided")

            if (
                not isinstance(duration_minutes, int)
                or isinstance(duration_minutes, bool)
                or duration_minutes < 1
                or duration_minutes > 40320
            ):
                await message.reply(
                    "That timeout duration is invalid. "
                    "Please choose a duration between 1 minute and 28 days.",
                    mention_author=False
                )
                return

            members = find_member(message.guild, member_name)

            if not members or members[0] is None:
                await message.reply(
                    f"I couldn't find the member '{member_name}'.",
                    mention_author=False
                )
                return

            if len(members) > 1:
                await message.reply(
                    "More than one member matches that name. "
                    "Please use a Discord mention.",
                    mention_author=False
                )
                return

            member = members[0]
            guild = message.guild
            bot_member = guild.me

            if bot_member is None:
                await message.reply(
                    "I couldn't verify my server permissions.",
                    mention_author=False
                )
                return

            if not bot_member.guild_permissions.moderate_members:
                await message.reply(
                    "I don't have permission to timeout members.",
                    mention_author=False
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.reply(
                    hierarchy_error,
                    mention_author=False
                )
                return

            if member.is_timed_out():
                await message.reply(
                    "That member already has an active timeout.",
                    mention_author=False
                )
                return

            hours, remainder = divmod(duration_minutes, 60)
            days, hours = divmod(hours, 24)

            duration_parts = []

            if days:
                duration_parts.append(f"{days} day(s)")

            if hours:
                duration_parts.append(f"{hours} hour(s)")

            if remainder:
                duration_parts.append(f"{remainder} minute(s)")

            duration_text = ", ".join(duration_parts)

            confirmed = await get_confirmation(
                message,
                f"**Action:** Timeout member\n"
                f"**Member:** {member.display_name}\n"
                f"**Duration:** {duration_text}\n"
                f"**Reason:** {reason}"
            )

            if not confirmed:
                return

            bot_member = guild.me

            if (
                bot_member is None
                or not bot_member.guild_permissions.moderate_members
                or guild.get_member(member.id) is None
            ):
                await message.channel.send(
                    "The timeout could not be completed because "
                    "permissions or member information changed."
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.channel.send(hierarchy_error)
                return

            if member.is_timed_out():
                await message.channel.send(
                    "That member already has an active timeout."
                )
                return

            until = discord.utils.utcnow() + timedelta(
                minutes=duration_minutes
            )

            await member.timeout(
                until,
                reason=f"{reason} | Confirmed by {message.author}"
            )

            await message.channel.send(
                f"Successfully timed out **{member.display_name}** "
                f"for **{duration_text}**."
            )

            print(
                f"MEMBER TIMED OUT: {member} by {message.author}. "
                f"Duration: {duration_text}. Reason: {reason}"
            )

            return

        # -----------------------------------------
        # REMOVE MEMBER TIMEOUT
        # -----------------------------------------

        if action_type == "remove_timeout":

            member_name = answer.get("member_name", "")
            reason = answer.get("reason", "No reason provided")

            members = find_member(message.guild, member_name)

            if not members or members[0] is None:
                await message.reply(
                    f"I couldn't find the member '{member_name}'.",
                    mention_author=False
                )
                return

            if len(members) > 1:
                await message.reply(
                    "More than one member matches that name. "
                    "Please use a Discord mention.",
                    mention_author=False
                )
                return

            member = members[0]
            guild = message.guild
            bot_member = guild.me

            if bot_member is None:
                await message.reply(
                    "I couldn't verify my server permissions.",
                    mention_author=False
                )
                return

            if not bot_member.guild_permissions.moderate_members:
                await message.reply(
                    "I don't have permission to remove timeouts.",
                    mention_author=False
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.reply(
                    hierarchy_error,
                    mention_author=False
                )
                return

            if not member.is_timed_out():
                await message.reply(
                    "That member does not currently have an active timeout.",
                    mention_author=False
                )
                return

            confirmed = await get_confirmation(
                message,
                f"**Action:** Remove timeout\n"
                f"**Member:** {member.display_name}\n"
                f"**Reason:** {reason}"
            )

            if not confirmed:
                return

            bot_member = guild.me

            if (
                bot_member is None
                or not bot_member.guild_permissions.moderate_members
                or guild.get_member(member.id) is None
            ):
                await message.channel.send(
                    "The timeout could not be removed because "
                    "permissions or member information changed."
                )
                return

            hierarchy_error = check_member_hierarchy(
                guild, member, message.author, bot_member
            )

            if hierarchy_error:
                await message.channel.send(hierarchy_error)
                return

            if not member.is_timed_out():
                await message.channel.send(
                    "That member no longer has an active timeout."
                )
                return

            await member.timeout(
                None,
                reason=f"{reason} | Confirmed by {message.author}"
            )

            await message.channel.send(
                f"Successfully removed the timeout from "
                f"**{member.display_name}**."
            )

            print(
                f"TIMEOUT REMOVED: {member} by {message.author}. "
                f"Reason: {reason}"
            )

            return

        # -----------------------------------------
        # ORDINARY AI RESPONSES
        # -----------------------------------------

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
