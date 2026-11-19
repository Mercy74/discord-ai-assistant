
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
            "description": "Prepare a permanent ban request. Target can be an existing member or an account identified by numeric Discord User ID, even if outside the server.",
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
            "description": "Prepare a request to lift a Discord server ban. Requires numeric Discord User ID.",
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
            "description": "Prepare a timeout request for an existing server member. Duration is required, from 1 to 40320 minutes.",
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
            "description": "Prepare a request to remove an active timeout from an existing server member.",
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


async def ask_groq(message: str) -> dict:
    """Ask Groq to respond or prepare a Discord action."""

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

                        "CRITICAL TOOL RULES: "
                        "When the staff clearly requests a Discord action, "
                        "you MUST call the matching function tool. "
                        "Never write a conversational confirmation instead "
                        "of calling a tool. The application handles all "
                        "confirmation prompts and execution. "

                        "Use request_role_assignment to give a member a role. "
                        "Use request_role_removal to remove a member role. "
                        "Use request_channel_message to send a channel message. "

                        "Use request_member_ban for permanent bans. "
                        "The target can be an existing member or an account "
                        "outside the server identified by numeric User ID. "
                        "Preserve every digit of numeric IDs exactly. "
                        "Never invent or modify IDs. "

                        "Use request_member_unban to lift a server ban. "
                        "A numeric Discord User ID is required. "
                        "Never confuse unbanning with timeout removal. "

                        "Use request_member_timeout for timeouts. "
                        "A duration is mandatory. "
                        "Convert durations into minutes: "
                        "10 minutes = 10, 2 hours = 120, "
                        "1 day = 1440, 7 days = 10080. "
                        "Maximum duration is 40320 minutes (28 days). "
                        "If duration is missing or unclear, ask a question "
                        "instead of guessing. "

                        "Use request_timeout_removal to remove an active timeout. "

                        "Understand channel mentions such as <#123456789>. "
                        "Preserve channel IDs exactly. "
                        "For 'here' or 'this channel', use the current "
                        "channel information in the context. "

                        "If a member, role, channel, ID, or other required "
                        "detail is unclear, ask for clarification. "
                        "Never invent missing information. "

                        "If no moderation reason is given, use "
                        "'No reason provided'. "

                        "Never claim an action has been completed. "
                        "You only prepare the action. "
                        "The application checks permissions, asks for "
                        "confirmation, and executes the action."
                    )
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

            arguments = json.loads(tool_call.function.arguments)

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

        return {
            "type": "message",
            "content": ai_message.content or "I couldn't generate a response."
        }

    except Exception as error:
        print(f"GROQ ERROR TYPE: {type(error).__name__}")
        print(f"GROQ ERROR DETAILS: {repr(error)}")
        raise
