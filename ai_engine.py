
import os
import json

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = "openai/gpt-oss-120b"

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY environment variable")

client = AsyncGroq(api_key=GROQ_API_KEY)


# =========================================================
# DISCORD ACTION TOOLS
# =========================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_role_assignment",
            "description": (
                "Prepare a request to give an existing member a role. "
                "The member can be identified by numeric Discord ID, "
                "@mention, username, or server nickname."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string"},
                    "role_name": {"type": "string"}
                },
                "required": ["member_name", "role_name"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_role_removal",
            "description": (
                "Prepare a request to remove a role from an existing member. "
                "The member can be identified by numeric Discord ID, "
                "@mention, username, or server nickname."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string"},
                    "role_name": {"type": "string"}
                },
                "required": ["member_name", "role_name"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_channel_message",
            "description": (
                "Prepare a request to send a message to a Discord text channel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_name": {"type": "string"},
                    "message_content": {"type": "string"}
                },
                "required": ["channel_name", "message_content"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_member_ban",
            "description": (
                "Prepare a permanent ban request. The target can be an "
                "existing member or an account outside the server identified "
                "by numeric Discord User ID. Preserve the exact ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["member_name", "reason"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_member_unban",
            "description": (
                "Prepare a request to lift a Discord server ban. "
                "Requires the numeric Discord User ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["user_id", "reason"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_member_timeout",
            "description": (
                "Prepare a timeout request for an existing server member. "
                "The member_name field accepts a numeric Discord User ID, "
                "Discord @mention, username, or server nickname. "
                "If a numeric ID is supplied, pass that exact ID as member_name. "
                "Never ask for a username when a numeric ID is already provided. "
                "Duration is required, from 1 to 40320 minutes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string"},
                    "duration_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 40320
                    },
                    "reason": {"type": "string"}
                },
                "required": [
                    "member_name",
                    "duration_minutes",
                    "reason"
                ],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_timeout_removal",
            "description": (
                "Prepare a request to remove an active timeout from an "
                "existing server member. The member can be identified by "
                "numeric Discord ID, @mention, username, or nickname."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["member_name", "reason"],
                "additionalProperties": False
            }
        }
    }
]


ACTION_TOOLS = {
    "request_role_assignment": "assign_role",
    "request_role_removal": "remove_role",
    "request_channel_message": "send_message",
    "request_member_ban": "ban_member",
    "request_member_unban": "unban_member",
    "request_member_timeout": "timeout_member",
    "request_timeout_removal": "remove_timeout"
}


# =========================================================
# AI SYSTEM INSTRUCTIONS
# =========================================================

SYSTEM_PROMPT = """
You are an intelligent Discord server assistant.

You help authorized staff manage their Discord server.

You are conversational, helpful, and concise.

IMPORTANT ACTION RULES:

When staff clearly requests a Discord action, you MUST call
the matching function tool.

Do not respond with a conversational confirmation instead
of calling the function tool.

The application handles permission checks, confirmation,
and execution. You only prepare the requested action.

MEMBER IDENTIFICATION:

The member_name field accepts:
- Numeric Discord User IDs
- Discord @mentions
- Usernames
- Server nicknames

If staff supplies a numeric Discord User ID, pass that
exact ID into member_name.

Never ask for a username or nickname when a numeric ID
has already been supplied.

Never shorten, alter, or invent a Discord ID.

Never assume that two different members are the same person.

ROLE ACTIONS:

Use request_role_assignment to give a member a role.

Use request_role_removal to remove a member role.

TIMEOUT ACTIONS:

Use request_member_timeout to apply a timeout.

A timeout duration is mandatory.

Convert durations into minutes:
10 minutes = 10
2 hours = 120
1 day = 1440
7 days = 10080

Maximum duration is 40320 minutes (28 days).

If duration is missing or unclear, ask a question
instead of guessing.

Use request_timeout_removal to remove an active timeout.

BAN ACTIONS:

Use request_member_ban for permanent bans.

A ban target can be an existing member or an account
outside the server identified by numeric Discord User ID.

Preserve every digit of numeric IDs exactly.

UNBAN ACTIONS:

Use request_member_unban to lift a server ban.

A numeric Discord User ID is required.

Do not confuse unbanning with timeout removal.

CHANNEL MESSAGES:

Use request_channel_message to send a channel message.

Understand channel mentions such as <#123456789>.

For "here" or "this channel", use the current channel
information supplied in the conversation.

REASONS:

If no moderation reason is provided, use
"No reason provided".

CLARIFICATION:

If a required detail is genuinely missing or unclear,
ask a concise clarification question.

Do not ask for information already supplied.

SAFETY:

Never claim that an action has been completed.

Never claim that you executed an action.

The application checks permissions, asks for confirmation,
and executes the action.
"""


# =========================================================
# GROQ REQUEST
# =========================================================

async def ask_groq(message: str) -> dict:
    """Ask Groq to respond or prepare a Discord action."""

    try:
        print("DEBUG: Sending request to Groq API...")

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": message
                }
            ],
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
            max_completion_tokens=1000
        )

        print("DEBUG: Groq returned a response.")

        ai_message = response.choices[0].message

        if ai_message.tool_calls:

            if len(ai_message.tool_calls) != 1:
                return {
                    "type": "message",
                    "content": "Please request one server action at a time."
                }

            tool_call = ai_message.tool_calls[0]
            function_name = tool_call.function.name

            if function_name not in ACTION_TOOLS:
                return {
                    "type": "message",
                    "content": "I couldn't identify that server action."
                }

            arguments = json.loads(
                tool_call.function.arguments
            )

            action_type = ACTION_TOOLS[function_name]

            print(f"DEBUG: AI prepared action: {action_type}")
            print(f"DEBUG: Action arguments: {arguments}")

            if action_type == "assign_role":
                return {
                    "type": action_type,
                    "member_name": arguments["member_name"],
                    "role_name": arguments["role_name"]
                }

            if action_type == "remove_role":
                return {
                    "type": action_type,
                    "member_name": arguments["member_name"],
                    "role_name": arguments["role_name"]
                }

            if action_type == "send_message":
                return {
                    "type": action_type,
                    "channel_name": arguments["channel_name"],
                    "message_content": arguments["message_content"]
                }

            if action_type == "ban_member":
                return {
                    "type": action_type,
                    "member_name": arguments["member_name"],
                    "reason": arguments["reason"]
                }

            if action_type == "unban_member":
                return {
                    "type": action_type,
                    "user_id": arguments["user_id"],
                    "reason": arguments["reason"]
                }

            if action_type == "timeout_member":
                return {
                    "type": action_type,
                    "member_name": arguments["member_name"],
                    "duration_minutes": arguments["duration_minutes"],
                    "reason": arguments["reason"]
                }

            if action_type == "remove_timeout":
                return {
                    "type": action_type,
                    "member_name": arguments["member_name"],
                    "reason": arguments["reason"]
                }

        print("DEBUG: Groq did not call an action tool.")

        return {
            "type": "message",
            "content": (
                ai_message.content
                or "I couldn't generate a response."
            )
        }

    except Exception as error:
        print(f"GROQ ERROR TYPE: {type(error).__name__}")
        print(f"GROQ ERROR DETAILS: {repr(error)}")
        raise
