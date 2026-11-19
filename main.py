
import os
import re
import asyncio
import threading
from datetime import timedelta

from flask import Flask
import discord
from discord.ext import commands

from ai_engine import ask_groq


# =========================================================
# CONFIGURATION
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")


# =========================================================
# FLASK KEEP-ALIVE SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Discord AI Assistant is running!"


def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# =========================================================
# DISCORD BOT SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# Pending confirmations are stored in memory while the bot runs.
# Each confirmation is tied to one staff member, one channel,
# and one server.
pending_confirmations = {}


# =========================================================
# GENERAL HELPERS
# =========================================================

def confirmation_key(message):
    return (
        message.guild.id,
        message.channel.id,
        message.author.id
    )


def is_staff(member):
    permissions = member.guild_permissions
    return permissions.administrator or permissions.manage_guild


def get_bot_member(guild):
    if bot.user is None:
        return None

    return guild.get_member(bot.user.id)


def get_user_id(value):
    """Extract a numeric Discord ID from an ID or user mention."""

    if value is None:
        return None

    value = str(value).strip()

    mention_match = re.fullmatch(r"<@!?(\d+)>", value)

    if mention_match:
        return int(mention_match.group(1))

    if value.isdigit():
        return int(value)

    return None


async def find_member(guild, member_name):
    """Find a current server member by mention, ID, username, or display name."""

    user_id = get_user_id(member_name)

    if user_id:
        member = guild.get_member(user_id)

        if member:
            return member

        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException:
            return None

    search = str(member_name).strip().lower()

    if not search:
        return None

    for member in guild.members:
        if (
            member.name.lower() == search
            or member.display_name.lower() == search
            or str(member) .lower() == search
        ):
            return member

    matches = [
        member for member in guild.members
        if search in member.name.lower()
        or search in member.display_name.lower()
    ]

    if len(matches) == 1:
        return matches[0]

    return None


def find_role(guild, role_name):
    search = str(role_name).strip().lower()

    for role in guild.roles:
        if role.name.lower() == search:
            return role

    return None


async def find_target_channel(guild, channel_name, current_channel):
    search = str(channel_name).strip().lower()

    if not search or search in ("here", "this channel", "current channel"):
        return current_channel

    channel_match = re.fullmatch(r"<#(\d+)>", search)

    if channel_match:
        channel_id = int(channel_match.group(1))
        channel = guild.get_channel(channel_id)

        if channel:
            return channel

        try:
            return await guild.fetch_channel(channel_id)
        except discord.HTTPException:
            return None

    for channel in guild.text_channels:
        if channel.name.lower() == search:
            return channel

    matches = [
        channel for channel in guild.text_channels
        if search in channel.name.lower()
    ]

    if len(matches) == 1:
        return matches[0]

    return None


# =========================================================
# PERMISSION AND HIERARCHY CHECKS
# =========================================================

def check_member_hierarchy(guild, target, staff_member, bot_member):
    """Return an error message if a member cannot be moderated."""

    if target.id == guild.owner_id:
        return "I cannot moderate the server owner."

    if bot_member and target.id == bot_member.id:
        return "I cannot moderate myself."

    if target.id == staff_member.id:
        return "You cannot use this action on yourself."

    if bot_member and target.top_role >= bot_member.top_role:
        return "That member has a role equal to or higher than my highest role."

    if staff_member.id != guild.owner_id:
        if target.top_role >= staff_member.top_role:
            return "You cannot moderate a member with a role equal to or higher than your highest role."

    return None


def check_role_hierarchy(role, staff_member, bot_member):
    if role.is_default():
        return "I cannot assign or remove the @everyone role."

    if role.managed:
        return "That role is managed by an integration and cannot be changed."

    if bot_member and role >= bot_member.top_role:
        return "That role is equal to or higher than my highest role."

    if staff_member.id != staff_member.guild.owner_id:
        if role >= staff_member.top_role:
            return "You cannot manage a role equal to or higher than your highest role."

    return None


# =========================================================
# CONFIRMATION SYSTEM
# =========================================================

async def get_confirmation(message, description):
    """
    Ask for confirmation and wait for a reply from the
    original staff member in the original channel.
    """

    key = confirmation_key(message)

    if key in pending_confirmations:
        await message.reply(
            "You already have an action awaiting confirmation in this channel."
        )
        return False

    future = asyncio.get_running_loop().create_future()
    pending_confirmations[key] = future

    try:
        await message.reply(
            f"**Please confirm this action:**\n"
            f"{description}\n\n"
            "Reply **yes** to proceed or **no** to cancel. "
            "You have 60 seconds."
        )

        try:
            return await asyncio.wait_for(future, timeout=60)
        except asyncio.TimeoutError:
            await message.channel.send(
                "Confirmation expired. The action was cancelled."
            )
            return False

    finally:
        if pending_confirmations.get(key) is future:
            pending_confirmations.pop(key, None)


async def handle_pending_confirmation(message):
    """Intercept confirmation replies before sending messages to the AI."""

    key = confirmation_key(message)
    future = pending_confirmations.get(key)

    if future is None:
        return False

    if future.done():
        return True

    content = re.sub(r"<@!?\d+>", "", message.content).strip().lower()

    if content in ("yes", "y", "confirm"):
        future.set_result(True)
        await message.reply("Confirmation received. Processing the action.")
        return True

    if content in ("no", "n", "cancel"):
        future.set_result(False)
        await message.reply("Action cancelled.")
        return True

    await message.reply(
        "You have an action awaiting confirmation. "
        "Reply **yes** to proceed or **no** to cancel."
    )

    return True


# =========================================================
# BOT READY EVENT
# =========================================================

@bot.event
async def on_ready():
    print("DEBUG: Bot is ready!")
    print(f"AI Assistant online: {bot.user}")
    print("Waiting for staff instructions...")


# =========================================================
# MESSAGE HANDLER
# =========================================================

@bot.event
async def on_message(message):

    # Ignore bots and direct messages.
    if message.author.bot or message.guild is None:
        return

    if not bot.is_ready():
        return

    # IMPORTANT:
    # Handle pending confirmations BEFORE requiring a bot mention.
    if await handle_pending_confirmation(message):
        return

    # Only respond to staff.
    if not is_staff(message.author):
        return

    # Normal instructions must mention the bot.
    if bot.user not in message.mentions:
        return

    print("DEBUG: Staff instruction received.")

    # Remove the bot mention from the instruction.
    instruction = re.sub(
        rf"<@!?{bot.user.id}>",
        "",
        message.content
    ).strip()

    if not instruction:
        await message.reply("What would you like me to do?")
        return

    prompt = (
        f"Server: {message.guild.name}\n"
        f"Server ID: {message.guild.id}\n"
        f"Current channel: #{message.channel.name}\n"
        f"Current channel ID: {message.channel.id}\n"
        f"Staff member: {message.author.display_name}\n"
        f"Staff user ID: {message.author.id}\n\n"
        f"Staff instruction: {instruction}"
    )

    try:
        async with message.channel.typing():
            result = await asyncio.wait_for(
                ask_groq(prompt),
                timeout=90
            )

    except asyncio.TimeoutError:
        await message.reply(
            "The AI request took too long. Please try again."
        )
        return

    except Exception as error:
        print(f"AI ERROR: {type(error).__name__}: {error}")
        await message.reply(
            "I encountered an error while processing that request."
        )
        return

    if not isinstance(result, dict):
        await message.reply(str(result))
        return

    action_type = result.get("type")

    if action_type == "message":
        await message.reply(
            result.get("content", "I couldn't generate a response.")
        )
        return

    guild = message.guild
    staff_member = message.author
    bot_member = get_bot_member(guild)

    if bot_member is None:
        await message.reply(
            "I couldn't verify my server membership. Please try again."
        )
        return

    # =====================================================
    # ASSIGN ROLE
    # =====================================================

    if action_type == "assign_role":

        if not staff_member.guild_permissions.manage_roles:
            await message.reply(
                "You need the Manage Roles permission to do that."
            )
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply(
                "I need the Manage Roles permission to do that."
            )
            return

        member = await find_member(guild, result.get("member_name"))
        role = find_role(guild, result.get("role_name"))

        if not member:
            await message.reply("I couldn't find that server member.")
            return

        if not role:
            await message.reply("I couldn't find that role.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        ) or check_role_hierarchy(role, staff_member, bot_member)

        if error:
            await message.reply(error)
            return

        if role in member.roles:
            await message.reply("That member already has that role.")
            return

        confirmed = await get_confirmation(
            message,
            f"Give **{role.name}** to **{member.display_name}**?"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.manage_roles:
            await message.reply("Your Manage Roles permission is no longer available.")
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply("I no longer have Manage Roles permission.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        ) or check_role_hierarchy(role, staff_member, bot_member)

        if error:
            await message.reply(error)
            return

        try:
            await member.add_roles(role, reason="AI Assistant staff request")
            await message.channel.send(
                f"Successfully gave **{role.name}** to **{member.display_name}**."
            )
        except discord.Forbidden:
            await message.reply("Discord denied the role assignment.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # REMOVE ROLE
    # =====================================================

    if action_type == "remove_role":

        if not staff_member.guild_permissions.manage_roles:
            await message.reply(
                "You need the Manage Roles permission to do that."
            )
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply(
                "I need the Manage Roles permission to do that."
            )
            return

        member = await find_member(guild, result.get("member_name"))
        role = find_role(guild, result.get("role_name"))

        if not member:
            await message.reply("I couldn't find that server member.")
            return

        if not role:
            await message.reply("I couldn't find that role.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        ) or check_role_hierarchy(role, staff_member, bot_member)

        if error:
            await message.reply(error)
            return

        if role not in member.roles:
            await message.reply("That member doesn't have that role.")
            return

        confirmed = await get_confirmation(
            message,
            f"Remove **{role.name}** from **{member.display_name}**?"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.manage_roles:
            await message.reply("Your Manage Roles permission is no longer available.")
            return

        if not bot_member.guild_permissions.manage_roles:
            await message.reply("I no longer have Manage Roles permission.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        ) or check_role_hierarchy(role, staff_member, bot_member)

        if error:
            await message.reply(error)
            return

        try:
            await member.remove_roles(role, reason="AI Assistant staff request")
            await message.channel.send(
                f"Successfully removed **{role.name}** from **{member.display_name}**."
            )
        except discord.Forbidden:
            await message.reply("Discord denied the role removal.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # SEND CHANNEL MESSAGE
    # =====================================================

    if action_type == "send_message":

        if not bot_member.guild_permissions.send_messages:
            await message.reply(
                "I don't have permission to send messages."
            )
            return

        channel = await find_target_channel(
            guild,
            result.get("channel_name"),
            message.channel
        )

        content = result.get("message_content", "").strip()

        if not channel:
            await message.reply("I couldn't find that text channel.")
            return

        if not content:
            await message.reply("The message content cannot be empty.")
            return

        permissions = channel.permissions_for(bot_member)

        if not permissions.send_messages:
            await message.reply(
                "I don't have permission to send messages in that channel."
            )
            return

        confirmed = await get_confirmation(
            message,
            f"Send this message in **#{channel.name}**?\n\n"
            f"> {content}"
        )

        if not confirmed:
            return

        if not bot_member.guild_permissions.send_messages:
            await message.reply("I no longer have permission to send messages.")
            return

        permissions = channel.permissions_for(bot_member)

        if not permissions.send_messages:
            await message.reply(
                "I can no longer send messages in that channel."
            )
            return

        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await message.channel.send(
                f"Successfully sent the message in **#{channel.name}**."
            )
        except discord.Forbidden:
            await message.reply("Discord denied permission to send that message.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # BAN MEMBER - INCLUDING USERS OUTSIDE THE SERVER
    # =====================================================

    if action_type == "ban_member":

        if not staff_member.guild_permissions.ban_members:
            await message.reply(
                "You need the Ban Members permission to do that."
            )
            return

        if not bot_member.guild_permissions.ban_members:
            await message.reply(
                "I need the Ban Members permission to do that."
            )
            return

        target_value = result.get("member_name")
        target_id = get_user_id(target_value)

        member = None
        ban_target = None

        if target_id:
            if target_id == staff_member.id:
                await message.reply("You cannot ban yourself.")
                return

            if target_id == bot_member.id:
                await message.reply("I cannot ban myself.")
                return

            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                # The user is not in the server.
                # A Discord Object allows banning by ID.
                ban_target = discord.Object(id=target_id)
            except discord.HTTPException:
                await message.reply(
                    "I couldn't verify that user ID. Please try again."
                )
                return

        else:
            member = await find_member(guild, target_value)

            if not member:
                await message.reply(
                    "I couldn't find that member. To ban someone who has "
                    "left the server, provide their numeric Discord User ID."
                )
                return

        if member:
            error = check_member_hierarchy(
                guild, member, staff_member, bot_member
            )

            if error:
                await message.reply(error)
                return

            ban_target = member
            target_description = (
                f"**{member.display_name}** "
                f"(User ID: `{member.id}`)"
            )
        else:
            target_description = f"Discord User ID `{target_id}`"

        reason = result.get("reason") or "No reason provided"

        confirmed = await get_confirmation(
            message,
            f"Permanently ban {target_description}?\n"
            f"Reason: {reason}"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.ban_members:
            await message.reply("Your Ban Members permission is no longer available.")
            return

        if not bot_member.guild_permissions.ban_members:
            await message.reply("I no longer have Ban Members permission.")
            return

        # Recheck hierarchy for members still in the server.
        if member:
            try:
                member = await guild.fetch_member(member.id)
            except discord.NotFound:
                # The member left while confirmation was pending.
                ban_target = discord.Object(id=target_id or member.id)
            except discord.HTTPException:
                await message.reply("I couldn't recheck the target member.")
                return

            if isinstance(ban_target, discord.Member):
                error = check_member_hierarchy(
                    guild, member, staff_member, bot_member
                )

                if error:
                    await message.reply(error)
                    return

                ban_target = member

        try:
            await guild.ban(
                ban_target,
                reason=reason,
                delete_message_seconds=0
            )

            await message.channel.send(
                f"Successfully banned {target_description}."
            )

        except discord.Forbidden:
            await message.reply("Discord denied the ban.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # UNBAN USER BY DISCORD ID
    # =====================================================

    if action_type == "unban_member":

        if not staff_member.guild_permissions.ban_members:
            await message.reply(
                "You need the Ban Members permission to unban users."
            )
            return

        if not bot_member.guild_permissions.ban_members:
            await message.reply(
                "I need the Ban Members permission to unban users."
            )
            return

        user_id = get_user_id(result.get("user_id"))

        if not user_id:
            await message.reply(
                "I need a numeric Discord User ID to unban someone."
            )
            return

        reason = result.get("reason") or "No reason provided"
        user_object = discord.Object(id=user_id)

        try:
            ban_entry = await guild.fetch_ban(user_object)
        except discord.NotFound:
            await message.reply("That user is not currently banned.")
            return
        except discord.HTTPException as error:
            await message.reply(f"I couldn't check the ban: {error}")
            return

        username = str(ban_entry.user)

        confirmed = await get_confirmation(
            message,
            f"Unban **{username}** (User ID: `{user_id}`)?\n"
            f"Reason: {reason}"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.ban_members:
            await message.reply("Your Ban Members permission is no longer available.")
            return

        if not bot_member.guild_permissions.ban_members:
            await message.reply("I no longer have Ban Members permission.")
            return

        try:
            # Check that the user is still banned.
            await guild.fetch_ban(user_object)

            await guild.unban(
                user_object,
                reason=reason
            )

            await message.channel.send(
                f"Successfully unbanned **{username}** (`{user_id}`)."
            )

        except discord.NotFound:
            await message.reply("That user is no longer banned.")
        except discord.Forbidden:
            await message.reply("Discord denied the unban.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # TIMEOUT MEMBER
    # =====================================================

    if action_type == "timeout_member":

        if not staff_member.guild_permissions.moderate_members:
            await message.reply(
                "You need the Moderate Members permission to do that."
            )
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "I need the Moderate Members permission to do that."
            )
            return

        member = await find_member(guild, result.get("member_name"))

        if not member:
            await message.reply("I couldn't find that server member.")
            return

        duration = result.get("duration_minutes")

        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration > 40320
        ):
            await message.reply(
                "Please provide a timeout duration between 1 minute and 28 days."
            )
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        )

        if error:
            await message.reply(error)
            return

        if member.is_timed_out():
            await message.reply("That member is already timed out.")
            return

        reason = result.get("reason") or "No reason provided"

        confirmed = await get_confirmation(
            message,
            f"Place **{member.display_name}** in timeout for "
            f"**{duration} minutes**?\nReason: {reason}"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.moderate_members:
            await message.reply("Your Moderate Members permission is no longer available.")
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply("I no longer have Moderate Members permission.")
            return

        try:
            member = await guild.fetch_member(member.id)
        except discord.HTTPException:
            await message.reply("I couldn't recheck that member.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        )

        if error:
            await message.reply(error)
            return

        if member.is_timed_out():
            await message.reply("That member is already timed out.")
            return

        try:
            await member.timeout(
                timedelta(minutes=duration),
                reason=reason
            )

            await message.channel.send(
                f"Successfully timed out **{member.display_name}** "
                f"for **{duration} minutes**."
            )

        except discord.Forbidden:
            await message.reply("Discord denied the timeout.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # REMOVE TIMEOUT
    # =====================================================

    if action_type == "remove_timeout":

        if not staff_member.guild_permissions.moderate_members:
            await message.reply(
                "You need the Moderate Members permission to do that."
            )
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply(
                "I need the Moderate Members permission to do that."
            )
            return

        member = await find_member(guild, result.get("member_name"))

        if not member:
            await message.reply("I couldn't find that server member.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        )

        if error:
            await message.reply(error)
            return

        if not member.is_timed_out():
            await message.reply("That member is not currently timed out.")
            return

        reason = result.get("reason") or "No reason provided"

        confirmed = await get_confirmation(
            message,
            f"Remove the timeout from **{member.display_name}**?\n"
            f"Reason: {reason}"
        )

        if not confirmed:
            return

        if not staff_member.guild_permissions.moderate_members:
            await message.reply("Your Moderate Members permission is no longer available.")
            return

        if not bot_member.guild_permissions.moderate_members:
            await message.reply("I no longer have Moderate Members permission.")
            return

        try:
            member = await guild.fetch_member(member.id)
        except discord.HTTPException:
            await message.reply("I couldn't recheck that member.")
            return

        error = check_member_hierarchy(
            guild, member, staff_member, bot_member
        )

        if error:
            await message.reply(error)
            return

        if not member.is_timed_out():
            await message.reply("That member is no longer timed out.")
            return

        try:
            await member.timeout(
                None,
                reason=reason
            )

            await message.channel.send(
                f"Successfully removed the timeout from **{member.display_name}**."
            )

        except discord.Forbidden:
            await message.reply("Discord denied the timeout removal.")
        except discord.HTTPException as error:
            await message.reply(f"Discord returned an error: {error}")

        return

    # =====================================================
    # UNKNOWN ACTION
    # =====================================================

    await message.reply(
        "I understood your request, but I don't recognize the action returned by the AI."
    )


# =========================================================
# START BOT AND WEB SERVER
# =========================================================

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    bot.run(DISCORD_TOKEN)
