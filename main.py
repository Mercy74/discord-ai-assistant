
import os
import re
import asyncio
import threading

from datetime import timedelta
from flask import Flask
import discord
from discord.ext import commands

from ai_engine import ask_groq


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")


# ============================================================
# RENDER KEEP-ALIVE SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Discord AI Assistant is running!"


def run_web_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    server_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )
    server_thread.start()


# ============================================================
# DISCORD BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# MEMBER SEARCH
# ============================================================

async def find_member(guild, member_name):
    """
    Find a member by Discord mention, ID, username,
    display name, or partial name.
    """

    member_name = member_name.strip()

    mention_match = re.fullmatch(
        r"<@!?(\d+)>",
        member_name
    )

    if mention_match:
        member_id = int(mention_match.group(1))

        member = guild.get_member(member_id)

        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except discord.NotFound:
                return None, "I couldn't find that member."
            except discord.HTTPException:
                return None, "I couldn't retrieve that member."

        return member, None

    if member_name.isdigit():
        member_id = int(member_name)

        member = guild.get_member(member_id)

        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except discord.NotFound:
                return None, "I couldn't find that member."
            except discord.HTTPException:
                return None, "I couldn't retrieve that member."

        return member, None

    members = guild.members

    search_name = member_name.lower()

    exact_matches = [
        member for member in members
        if search_name in (
            member.name.lower(),
            member.display_name.lower(),
            str(member).lower()
        )
    ]

    if len(exact_matches) == 1:
        return exact_matches[0], None

    if len(exact_matches) > 1:
        return None, (
            "I found multiple members with that name. "
            "Please use their Discord mention."
        )

    partial_matches = [
        member for member in members
        if (
            search_name in member.name.lower()
            or search_name in member.display_name.lower()
        )
    ]

    if len(partial_matches) == 1:
        return partial_matches[0], None

    if len(partial_matches) > 1:
        return None, (
            "I found multiple possible members. "
            "Please use their Discord mention."
        )

    return None, "I couldn't find that member."


# ============================================================
# CHANNEL SEARCH
# ============================================================

def find_target_channel(guild, channel_name, current_channel):
    """
    Find a channel by mention, name, or current-channel reference.
    """

    channel_name = channel_name.strip()

    current_references = [
        "here",
        "this channel",
        "current channel",
        "this chat"
    ]

    if channel_name.lower() in current_references:
        return current_channel

    mention_match = re.fullmatch(
        r"<#(\d+)>",
        channel_name
    )

    if mention_match:
        channel_id = int(mention_match.group(1))
        return guild.get_channel(channel_id)

    cleaned_name = channel_name.lstrip("#").lower()

    exact_matches = [
        channel for channel in guild.text_channels
        if channel.name.lower() == cleaned_name
    ]

    if len(exact_matches) == 1:
        return exact_matches[0]

    partial_matches = [
        channel for channel in guild.text_channels
        if cleaned_name in channel.name.lower()
    ]

    if len(partial_matches) == 1:
        return partial_matches[0]

    return None


# ============================================================
# CONFIRMATION SYSTEM
# ============================================================

async def get_confirmation(message, description):
    """
    Ask the staff member to confirm an action.
    """

    await message.reply(
        f"**Please confirm this action:**\n"
        f"{description}\n\n"
        f"Reply with **yes** to proceed or **no** to cancel.\n"
        f"You have 30 seconds.",
        mention_author=False
    )

    def check(response):
        return (
            response.author.id == message.author.id
            and response.channel.id == message.channel.id
            and not response.author.bot
        )

    try:
        response = await bot.wait_for(
            "message",
            timeout=30,
            check=check
        )

        answer = response.content.strip().lower()

        if answer in ["yes", "y", "confirm"]:
            return True

        if answer in ["no", "n", "cancel"]:
            await message.reply(
                "Action cancelled.",
                mention_author=False
            )
            return False

        await message.reply(
            "I didn't receive a valid confirmation. "
            "The action has been cancelled.",
            mention_author=False
        )
        return False

    except asyncio.TimeoutError:
        await message.reply(
            "Confirmation timed out. The action was cancelled.",
            mention_author=False
        )
        return False


# ============================================================
# MEMBER HIERARCHY CHECK
# ============================================================

def check_member_hierarchy(
    guild,
    member,
    staff_member,
    bot_member
):
    """
    Prevent actions against protected or higher-ranking members.
    """

    if member.id == guild.owner_id:
        return "The server owner cannot be targeted by this action."

    if member.id == bot_member.id:
        return "I cannot perform this action on myself."

    if member.id == staff_member.id:
        return (
            "You cannot use this assistant to perform "
            "this action on yourself."
        )

    if member.top_role >= bot_member.top_role:
        return (
            "I cannot manage this member because their highest "
            "role is above or equal to mine."
        )

    if staff_member.id == guild.owner_id:
        return None

    if member.top_role >= staff_member.top_role:
        return (
            "You cannot authorize an action against a member "
            "whose highest role is above or equal to yours."
        )

    return None


# ============================================================
# ROLE PERMISSION CHECK
# ============================================================

def check_role_hierarchy(
    role,
    staff_member,
    bot_member
):
    if role.is_default():
        return "I cannot assign or remove the @everyone role."

    if role.managed:
        return "I cannot manage an integration-managed role."

    if role >= bot_member.top_role:
        return (
            "I cannot manage that role because it is above "
            "or equal to my highest role."
        )

    if staff_member.id != staff_member.guild.owner_id:
        if role >= staff_member.top_role:
            return (
                "You cannot authorize changes to a role "
                "above or equal to your highest role."
            )

    return None


# ============================================================
# BOT READY EVENT
# ============================================================

@bot.event
async def on_ready():
    print("DEBUG: Bot is ready!")
    print(f"AI Assistant online: {bot.user}")
    print("Waiting for staff instructions...")


# ============================================================
# MESSAGE EVENT
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:
        return

    if bot.user is None:
        return

    # Only respond when directly mentioned.
    if bot.user not in message.mentions:
        return

    # --------------------------------------------------------
    # STAFF ACCESS CHECK
    # --------------------------------------------------------

    staff_permissions = message.author.guild_permissions

    if not (
        staff_permissions.administrator
        or staff_permissions.manage_guild
    ):
        await message.reply(
            "You don't have permission to use my staff commands.",
            mention_author=False
        )
        return

    print("DEBUG: Staff instruction received.")

    # --------------------------------------------------------
    # BUILD AI CONTEXT
    # --------------------------------------------------------

    clean_message = re.sub(
        rf"<@!?{bot.user.id}>",
        "",
        message.content
    ).strip()

    context = (
        f"SERVER: {message.guild.name}\n"
        f"CURRENT CHANNEL: #{message.channel.name}\n"
        f"CURRENT CHANNEL ID: {message.channel.id}\n"
        f"STAFF MEMBER: {message.author.display_name}\n"
        f"STAFF MEMBER ID: {message.author.id}\n\n"
        f"STAFF INSTRUCTION: {clean_message}"
    )

    # --------------------------------------------------------
    # ASK GROQ
    # --------------------------------------------------------

    async with message.channel.typing():

        try:
            result = await asyncio.wait_for(
                ask_groq(context),
                timeout=90
            )

        except asyncio.TimeoutError:
            await message.reply(
                "The AI request took too long. Please try again.",
                mention_author=False
            )
            return

        except Exception as error:
            print(f"AI ERROR: {repr(error)}")

            await message.reply(
                "I encountered an error while processing that request.",
                mention_author=False
            )
            return

    if not isinstance(result, dict):
        await message.reply(
            "I received an invalid response from the AI.",
            mention_author=False
        )
        return

    action_type = result.get("type")

    # --------------------------------------------------------
    # NORMAL AI RESPONSE
    # --------------------------------------------------------

    if action_type == "message":
        await message.reply(
            result.get("content", "I couldn't generate a response."),
            mention_author=False
        )
        return

    guild = message.guild
    staff_member = message.author
    bot_member = guild.me

    if bot_member is None:
        await message.reply(
            "I couldn't verify my server permissions.",
            mention_author=False
        )
        return

    # ========================================================
    # ROLE ASSIGNMENT
    # ========================================================

    if action_type == "assign_role":

        if not staff_permissions.manage_roles:
            await message.reply(
                "You don't have permission to authorize role changes.",
                mention_author=False
            )
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply(
                "I need the Manage Roles permission to do that.",
                mention_author=False
            )
            return

        member, error = await find_member(
            guild,
            result.get("member_name", "")
        )

        if error:
            await message.reply(error, mention_author=False)
            return

        role_name = result.get("role_name", "").strip()

        role = discord.utils.find(
            lambda item: item.name.lower() == role_name.lower(),
            guild.roles
        )

        if role is None:
            await message.reply(
                f"I couldn't find the role **{role_name}**.",
                mention_author=False
            )
            return

        hierarchy_error = check_role_hierarchy(
            role,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        if role in member.roles:
            await message.reply(
                f"{member.mention} already has the **{role.name}** role.",
                mention_author=False
            )
            return

        confirmed = await get_confirmation(
            message,
            f"Give the **{role.name}** role to {member.mention}?"
        )

        if not confirmed:
            return

        try:
            await member.add_roles(
                role,
                reason=f"Authorized by {staff_member}"
            )

            await message.reply(
                f"Successfully gave **{role.name}** to {member.mention}.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied that action. Check my role hierarchy "
                "and Manage Roles permission.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"ROLE ASSIGNMENT ERROR: {repr(error)}")

            await message.reply(
                "I couldn't assign that role because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # ROLE REMOVAL
    # ========================================================

    if action_type == "remove_role":

        if not staff_permissions.manage_roles:
            await message.reply(
                "You don't have permission to authorize role changes.",
                mention_author=False
            )
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply(
                "I need the Manage Roles permission to do that.",
                mention_author=False
            )
            return

        member, error = await find_member(
            guild,
            result.get("member_name", "")
        )

        if error:
            await message.reply(error, mention_author=False)
            return

        role_name = result.get("role_name", "").strip()

        role = discord.utils.find(
            lambda item: item.name.lower() == role_name.lower(),
            guild.roles
        )

        if role is None:
            await message.reply(
                f"I couldn't find the role **{role_name}**.",
                mention_author=False
            )
            return

        hierarchy_error = check_role_hierarchy(
            role,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        if role not in member.roles:
            await message.reply(
                f"{member.mention} doesn't have the **{role.name}** role.",
                mention_author=False
            )
            return

        confirmed = await get_confirmation(
            message,
            f"Remove the **{role.name}** role from {member.mention}?"
        )

        if not confirmed:
            return

        try:
            await member.remove_roles(
                role,
                reason=f"Authorized by {staff_member}"
            )

            await message.reply(
                f"Successfully removed **{role.name}** from {member.mention}.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied that action. Check my role hierarchy "
                "and Manage Roles permission.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"ROLE REMOVAL ERROR: {repr(error)}")

            await message.reply(
                "I couldn't remove that role because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # CHANNEL MESSAGES
    # ========================================================

    if action_type == "send_message":

        if not bot_member.guild_permissions.send_messages:
            await message.reply(
                "I don't have permission to send messages.",
                mention_author=False
            )
            return

        channel_name = result.get("channel_name", "")
        content = result.get("message_content", "")

        target_channel = find_target_channel(
            guild,
            channel_name,
            message.channel
        )

        if target_channel is None:
            await message.reply(
                "I couldn't find that channel. Please specify "
                "the channel name or mention it.",
                mention_author=False
            )
            return

        if not isinstance(
            target_channel,
            (discord.TextChannel, discord.Thread)
        ):
            await message.reply(
                "That isn't a supported text channel.",
                mention_author=False
            )
            return

        if not content.strip():
            await message.reply(
                "I need the message content before I can send it.",
                mention_author=False
            )
            return

        channel_permissions = target_channel.permissions_for(bot_member)

        if not channel_permissions.send_messages:
            await message.reply(
                "I don't have permission to send messages in "
                f"{target_channel.mention}.",
                mention_author=False
            )
            return

        if isinstance(target_channel, discord.Thread):
            if not channel_permissions.send_messages_in_threads:
                await message.reply(
                    "I don't have permission to send messages in that thread.",
                    mention_author=False
                )
                return

        confirmed = await get_confirmation(
            message,
            f"Send this message to {target_channel.mention}?\n\n"
            f"> {content}"
        )

        if not confirmed:
            return

        try:
            await target_channel.send(
                content,
                allowed_mentions=discord.AllowedMentions.none()
            )

            await message.reply(
                f"Message successfully sent to {target_channel.mention}.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied permission to send that message.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"CHANNEL MESSAGE ERROR: {repr(error)}")

            await message.reply(
                "I couldn't send the message because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # MEMBER BANS
    # ========================================================

    if action_type == "ban_member":

        if not staff_permissions.ban_members:
            await message.reply(
                "You don't have permission to authorize member bans.",
                mention_author=False
            )
            return

        if not bot_member.guild_permissions.ban_members:
            await message.reply(
                "I need the Ban Members permission to do that.",
                mention_author=False
            )
            return

        member, error = await find_member(
            guild,
            result.get("member_name", "")
        )

        if error:
            await message.reply(error, mention_author=False)
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        reason = result.get("reason") or "No reason provided"

        confirmed = await get_confirmation(
            message,
            f"**Permanently ban:** {member.mention}\n"
            f"**Reason:** {reason}"
        )

        if not confirmed:
            return

        # Recheck the member and permissions after confirmation.
        if not bot_member.guild_permissions.ban_members:
            await message.reply(
                "My Ban Members permission is no longer available.",
                mention_author=False
            )
            return

        if not staff_permissions.ban_members:
            await message.reply(
                "Your ban permission is no longer available.",
                mention_author=False
            )
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        try:
            await guild.ban(
                member,
                reason=f"Authorized by {staff_member}: {reason}",
                delete_message_seconds=0
            )

            await message.reply(
                f"Successfully banned **{member}**.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied the ban. Check my Ban Members permission "
                "and role hierarchy.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"BAN ERROR: {repr(error)}")

            await message.reply(
                "I couldn't ban that member because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # MEMBER TIMEOUTS
    # ========================================================

    if action_type == "timeout_member":

        if not staff_permissions.moderate_members:
            await message.reply(
                "You don't have permission to authorize member timeouts.",
                mention_author=False
            )
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "I need the Moderate Members permission to do that.",
                mention_author=False
            )
            return

        member, error = await find_member(
            guild,
            result.get("member_name", "")
        )

        if error:
            await message.reply(error, mention_author=False)
            return

        duration = result.get("duration_minutes")

        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 1
            or duration > 40320
        ):
            await message.reply(
                "The timeout duration must be between 1 minute "
                "and 28 days.",
                mention_author=False
            )
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        if member.is_timed_out():
            await message.reply(
                f"{member.mention} is already timed out. "
                f"Remove the existing timeout before applying another.",
                mention_author=False
            )
            return

        reason = result.get("reason") or "No reason provided"

        if duration < 60:
            duration_text = f"{duration} minute(s)"
        elif duration % 1440 == 0:
            duration_text = f"{duration // 1440} day(s)"
        elif duration % 60 == 0:
            duration_text = f"{duration // 60} hour(s)"
        else:
            duration_text = f"{duration} minutes"

        confirmed = await get_confirmation(
            message,
            f"**Timeout member:** {member.mention}\n"
            f"**Duration:** {duration_text}\n"
            f"**Reason:** {reason}"
        )

        if not confirmed:
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "My Moderate Members permission is no longer available.",
                mention_author=False
            )
            return

        if not staff_permissions.moderate_members:
            await message.reply(
                "Your Moderate Members permission is no longer available.",
                mention_author=False
            )
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        try:
            await member.timeout(
                timedelta(minutes=duration),
                reason=f"Authorized by {staff_member}: {reason}"
            )

            await message.reply(
                f"Successfully timed out {member.mention} "
                f"for **{duration_text}**.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied the timeout. Check my Moderate Members "
                "permission and role hierarchy.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"TIMEOUT ERROR: {repr(error)}")

            await message.reply(
                "I couldn't timeout that member because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # REMOVE MEMBER TIMEOUT
    # ========================================================

    if action_type == "remove_timeout":

        if not staff_permissions.moderate_members:
            await message.reply(
                "You don't have permission to authorize timeout removal.",
                mention_author=False
            )
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "I need the Moderate Members permission to do that.",
                mention_author=False
            )
            return

        member, error = await find_member(
            guild,
            result.get("member_name", "")
        )

        if error:
            await message.reply(error, mention_author=False)
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        if not member.is_timed_out():
            await message.reply(
                f"{member.mention} does not currently have an active timeout.",
                mention_author=False
            )
            return

        reason = result.get("reason") or "No reason provided"

        confirmed = await get_confirmation(
            message,
            f"**Remove timeout from:** {member.mention}\n"
            f"**Reason:** {reason}"
        )

        if not confirmed:
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "My Moderate Members permission is no longer available.",
                mention_author=False
            )
            return

        if not staff_permissions.moderate_members:
            await message.reply(
                "Your Moderate Members permission is no longer available.",
                mention_author=False
            )
            return

        hierarchy_error = check_member_hierarchy(
            guild,
            member,
            staff_member,
            bot_member
        )

        if hierarchy_error:
            await message.reply(
                hierarchy_error,
                mention_author=False
            )
            return

        try:
            await member.timeout(
                None,
                reason=f"Authorized by {staff_member}: {reason}"
            )

            await message.reply(
                f"Successfully removed the timeout from {member.mention}.",
                mention_author=False
            )

        except discord.Forbidden:
            await message.reply(
                "Discord denied the timeout removal. Check my Moderate Members "
                "permission and role hierarchy.",
                mention_author=False
            )

        except discord.HTTPException as error:
            print(f"TIMEOUT REMOVAL ERROR: {repr(error)}")

            await message.reply(
                "I couldn't remove that timeout because Discord returned an error.",
                mention_author=False
            )

        return

    # ========================================================
    # UNKNOWN ACTION
    # ========================================================

    await message.reply(
        "I understood your message, but I couldn't identify "
        "a supported action.",
        mention_author=False
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    keep_alive()

    print("DEBUG: Starting Discord AI Assistant...")

    bot.run(DISCORD_TOKEN)
