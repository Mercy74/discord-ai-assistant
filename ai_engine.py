
import os
import json

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL_NAME = "openai/gpt-oss-120b"

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY environment variable")

client = AsyncGroq(
    api_key=GROQ_API_KEY
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_role_assignment",
            "description": (
                "Request a role assignment when a staff member "
                "clearly asks to give an existing Discord member "
                "an existing server role. This only prepares a "
                "request for confirmation. It does not assign "
                "the role."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {
                        "type": "string",
                        "description": "The member's name or Discord mention."
                    },
                    "role_name": {
                        "type": "string",
                        "description": "The exact requested server role."
                    }
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
                "Request removal of an existing server role "
                "from an existing Discord member when a staff "
                "member clearly asks for it. This only prepares "
                "a request for confirmation. It does not remove "
                "the role."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "member_name": {
                        "type": "string",
                        "description": "The member's name or Discord mention."
                    },
                    "role_name": {
                        "type": "string",
                        "description": "The exact server role to remove."
                    }
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
                "Prepare a request to send a message to an existing "
                "Discord text channel. Use this when staff clearly "
                "ask you to post, announce, or send a message in a "
                "specific channel. This does not send the message. "
                "The application must obtain staff confirmation first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "The name of the Discord text channel."
                    },
                    "message_content": {
                        "type": "string",
                        "description": "The complete message to send."
                    }
                },
                "required": ["channel_name", "message_content"],
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

                        "Use request_role_assignment only when staff clearly "
                        "ask to give a member a role. "

                        "Use request_role_removal only when staff clearly "
                        "ask to remove a role from a member. "

                        "Use request_channel_message only when staff clearly "
                        "ask you to send a message to a specific channel. "
                        "Write the complete requested message in "
                        "message_content. Do not invent announcements, "
                        "events, dates, or information that staff did not "
                        "provide. If the message content is unclear, ask "
                        "a clarifying question. "

                        "Never invent member names, role names, or channel "
                        "names. If information is missing or ambiguous, "
                        "ask a clarifying question. "

                        "Never claim an action has been completed. "
                        "The application must confirm and execute all "
                        "Discord actions."
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

        return {
            "type": "message",
            "content": ai_message.content or "I couldn't generate a response."
        }

    except Exception as error:
        print(f"GROQ ERROR TYPE: {type(error).__name__}")
        print(f"GROQ ERROR DETAILS: {repr(error)}")
        raise
