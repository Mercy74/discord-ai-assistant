
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_role_assignment",
            "description": "Prepare a request to give an existing member a role. Does not execute it.",
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
            "description": "Prepare a request to remove a role from an existing member. Does not execute it.",
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
            "description": "Prepare a request to send a message to a Discord text channel. Does not send it.",
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
            "description": "Prepare a permanent ban request. The target can be an existing member identified by username or mention, or any Discord account identified by its numeric User ID, even if that account has left the server. Never guess an ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {
                        "type": "string",
                        "description": "The exact numeric Discord User ID, username, or Discord mention. Preserve numeric IDs exactly."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the ban. Use 'No reason provided' if none was specified."
                    }
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
            "description": "Prepare a request to lift a Discord server ban. Requires the target's numeric Discord User ID. Does not execute the unban.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The exact numeric Discord User ID of the banned account."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for removing the ban. Use 'No reason provided' if none was specified."
                    }
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
            "description": "Prepare a timeout request for an existing server member. Duration is required, from 1 to 40320 minutes. Does not execute the timeout.",
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
                "required": ["member_name", "duration_minutes", "reason"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_timeout_removal",
            "description": "Prepare a request to remove an active timeout from an existing server member. Does not execute the change.",
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


async def ask_groq(message: str) -> dict:
    """Ask Groq to respond or identify a requested Discord action."""

    try:
        print("DEBUG: Sending request to Groq API...")

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intelligent Discord server assistant. "
                        "Understand staff instructions carefully. "
                        "Be helpful, conversational, and concise. "

                        "Use request_role_assignment when staff clearly "
                        "ask to give a member a role. "

                        "Use request_role_removal when staff clearly "
                        "ask to remove a role from a member. "

                        "Use request_channel_message when staff clearly "
                        "ask to send a message to a channel. "

                        "Understand Discord channel mentions such as "
                        "<#123456789>. Preserve the mention exactly. "
                        "If staff say 'here', 'this channel', or "
                        "'current channel', use the current channel "
                        "information supplied in the context. "

                        "Use request_member_ban when staff clearly ask "
                        "to permanently ban an account. "
                        "The target may be an existing member or someone "
                        "who has left the server. "
                        "For a numeric Discord User ID, preserve every "
                        "digit exactly in member_name. "
                        "Never invent or modify a User ID. "
                        "A username alone cannot reliably identify "
                        "someone who is outside the server. "

                        "Use request_member_unban when staff clearly ask "
                        "to lift or remove a server ban. "
                        "A numeric Discord User ID is required. "
                        "Preserve the ID exactly. "
                        "Never confuse unbanning with timeout removal. "

                        "Use request_member_timeout when staff clearly "
                        "ask to timeout, mute, or temporarily restrict "
                        "a member. A duration is mandatory. "

                        "Convert timeout durations into minutes. "
                        "Examples: 10 minutes = 10, 2 hours = 120, "
                        "1 day = 1440, 7 days = 10080. "
                        "The maximum is 40320 minutes (28 days). "

                        "If a timeout duration is missing or unclear, "
                        "ask the staff member instead of guessing. "

                        "Use request_timeout_removal when staff clearly "
                        "ask to remove or lift an existing timeout. "

                        "If the member or target is unclear, ask "
                        "for clarification. Never invent member names, "
                        "roles, channels, IDs, or durations. "

                        "If no moderation reason is provided, use "
                        "'No reason provided'. "

                        "Never claim an action has been completed. "
                        "The application must check permissions and "
                        "request confirmation before executing actions."
                    )
                },
                {
                    "role": "user",
                    "content": message
                }
            ],
            tools=TOOLS,
            tool_choice="auto",
            max_completion_tokens=1000
        )

        print("DEBUG: Groq returned a response.")

        ai_message = response.choices[0].message

        if ai_message.tool_calls:
            tool_call = ai_message.tool_calls[0]
            function_name = tool_call.function.name

            arguments = json.loads(
                tool_call.function.arguments
            )

            if function_name == "request_role_assignment":
                return {
                    "type": "assign_role",
                    "member_name": arguments["member_name"],
                    "role_name": arguments["role_name"]
                }

            if function_name == "request_role_removal":
                return {
                    "type": "remove_role",
                    "member_name": arguments["member_name"],
                    "role_name": arguments["role_name"]
                }

            if function_name == "request_channel_message":
                return {
                    "type": "send_message",
                    "channel_name": arguments["channel_name"],
                    "message_content": arguments["message_content"]
                }

            if function_name == "request_member_ban":
                return {
                    "type": "ban_member",
                    "member_name": arguments["member_name"],
                    "reason": arguments["reason"]
                }

            if function_name == "request_member_unban":
                return {
                    "type": "unban_member",
                    "user_id": arguments["user_id"],
                    "reason": arguments["reason"]
                }

            if function_name == "request_member_timeout":
                return {
                    "type": "timeout_member",
                    "member_name": arguments["member_name"],
                    "duration_minutes": arguments["duration_minutes"],
                    "reason": arguments["reason"]
                }

            if function_name == "request_timeout_removal":
                return {
                    "type": "remove_timeout",
                    "member_name": arguments["member_name"],
                    "reason": arguments["reason"]
                }

        return {
            "type": "message",
            "content": ai_message.content or "I couldn't generate a response."
        }

    except Exception as error:
        print(f"GROQ ERROR TYPE: {type(error).__name__}")
        print(f"GROQ ERROR DETAILS: {repr(error)}")
        raise
