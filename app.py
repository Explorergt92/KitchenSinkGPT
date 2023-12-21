# !/usr/bin/env python
# coding: utf-8
# Filename: app.py
# Run command: python -m app
# Last modified by: ExplorerGT92
# Last modified on: 2023/12/21
# branch: opening_video

"""
This is the main part of the script
"""

import os
import sys
from datetime import datetime
from pathlib import Path
import json
import asyncio
import argparse
import threading
import importlib.util
import inspect
from moviepy.editor import VideoFileClip
from openai import AsyncOpenAI
import pytz
import spacy
import tzlocal
import tiktoken

from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from output_methods.audio_pyttsx3 import tts_output
from plugins.plugin_base import PluginBase

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TEMP,
    OPENAI_TOP_P,
    live_spinner,
)

sys.path.append(str(Path(__file__).parent))

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

# Define the open_ai model
openai_model = OPENAI_MODEL
base_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
gpt4_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
openai_defaults = {
    "model": OPENAI_MODEL,
    "temperature": OPENAI_TEMP,
    "top_p": OPENAI_TOP_P,
    "max_tokens": 1500,
    "frequency_penalty": 0.5,
    "presence_penalty": 0.5,

}

# Define the spacy model
nlp = spacy.load("en_core_web_sm")

# Define the rich console
console = Console()


def play_video(video_path):
    """
    This function plays a local video file in a separate thread.
    """
    def video_player(path):
        clip = VideoFileClip(path)
        clip.preview()
        clip.close()

    # Create a thread to play the video
    video_thread = threading.Thread(target=video_player, args=(video_path,))
    video_thread.start()


# Define the base functions and tools
async def get_current_date_time() -> str:
    """
    Get the current UTC date and time.

    Returns:
        str: The current UTC date and time.
    """
    local_timezone = tzlocal.get_localzone()
    now = datetime.now(local_timezone)
    now_est = now.astimezone(pytz.timezone("US/Eastern"))
    return now_est.strftime(
        "The current date and time is %B %d, %Y, %I:%M %p EST."
    )


# Define the ask_chat_gpt function
async def ask_chat_gpt_4_0314(**kwargs) -> str:
    """
    Ask ChatGPT a question and return the response.

    Args:
        kwargs (dict): The keyword arguments to pass to the function.
    Returns:
        str: The response from ChatGPT.
    """

    question = kwargs.get("question", "")
    text = kwargs.get("text", "")

    messages = [
        {"role": "system", "content": "You are the brains of the operation. You are built using a more advanced version of Generative AI that is called on by users and less sophisticated AIs' to answer more difficult questions, verify and correct responses before they are sent as final responses. You are able to understand more complex concepts and perform complex tasks using tools available to you.", },
        {"role": "user", "content": question},
        {"role": "assistant", "content": text},
    ]

    with live_spinner:
        response = await gpt4_client.chat.completions.create(
            model="gpt-4-0314",
            messages=messages,
            temperature=0,
            max_tokens=1500,
            top_p=0.3,
            frequency_penalty=0,
            presence_penalty=0,
        )

    # Check if the response has the expected structure and content
    if (response.choices and
            response.choices[0].message and
            response.choices[0].message.content):
        return response.choices[0].message.content
    else:
        # Handle the case where the expected content is not available
        return "An error occurred or no content was returned."


# Define a function to load plugins and get their tools
async def load_plugins_and_get_tools(available_functions, tools):
    """
    Load plugins and get their tools.
    """
    # Define the plugins folder
    plugins_folder = "plugins"

    # Iterate through the files and subdirectories in the plugins folder
    for file_path in Path(plugins_folder).rglob("*.py"):
        file = file_path.name
        if not file.startswith("_"):

            # Import the module dynamically
            spec = importlib.util.spec_from_file_location(file[:-3], file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the plugin class
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, PluginBase) and cls is not PluginBase:
                    # Check if the plugin is enabled
                    env_var_name = f"ENABLE_{cls.__name__.upper()}"
                    if os.getenv(env_var_name, "false").lower() == "true":
                        # Instantiate the plugin
                        plugin = cls()
                        # Initialize the plugin
                        await plugin.initialize()
                        # Get the tools from the plugin
                        plugin_available_functions, \
                            plugin_tools = plugin.get_tools()
                        # Add the plugin's functions and tools
                        available_functions.update(plugin_available_functions)
                        tools.extend(plugin_tools)

    return available_functions, tools


# Define the assistant prompt
ASSISTANT_PROMPT = "You are Voltron. You are an advanced AI system designed to assist users with complex tasks, answer questions and perform complex tasks using the available tools and by asking available experts questions. You are designed to assist users by using the tools available to you to gather data and complete actions required to best complete the users' request. Before providing a final response, take the time to reason and work out the best possible response for the given user request."


# Define the function to join messages
def join_messages(memory: list[dict]):
    """
    This function joins messages.
    """
    text = ""
    for m in memory:
        content = m.get("content")
        if content is not None:
            text += content + "\n"
    return text


# Define the function to check if the context is under the token limit
def check_under_context_limit(text: str, limit: int, model: str):
    """
    This function checks if the context is under the token limit.
    """
    enc = tiktoken.encoding_for_model(model)
    numtokens = len(enc.encode(text))
    return numtokens <= limit


# Define the function to follow the conversation
async def follow_conversation(
        user_text: str,
        memory: list[dict],
        mem_size: int,
        model: str
):
    """
    This function follows the conversation.
    """
    ind = min(mem_size, len(memory))
    if ind == 0:
        memory = [{"role": "system", "content": ASSISTANT_PROMPT}]
    memory.append({"role": "user", "content": user_text})
    while not check_under_context_limit(
        join_messages(memory),
        128000,
        model
    ) and ind > 1:
        ind -= 1
        memory.pop(0)  # Remove the oldest messages if the limit is exceeded
    response = await base_client.chat.completions.create(
        model=model,
        messages=memory[-ind:]
    )
    # Check if the response has the expected structure and content
    if (response.choices and
            response.choices[0].message and
            response.choices[0].message.content is not None):
        tr = response.choices[0].message.content
        memory.append(
            {
                "role": "assistant",
                "content": tr
            }
        )
    else:
        # Handle the case where the expected content is not available
        memory.append(
            {
                "role": "assistant",
                "content": "I'm not sure how to respond to that."
            }
        )

    return memory


# Define the display_help function
def display_help(tools):
    """
    Display the available tools.
    """
    console.print("\n[bold]Available Tools:[/bold]\n", style="bold blue")
    for tool in tools:
        function_info = tool.get("function", {})
        name = function_info.get("name", "Unnamed")
        description = function_info.get(
            "description",
            "No description available."
        )
        console.print(f"[bold]{name}[/bold]: {description}")
    console.print()


# Define the run_conversation function with memory
async def run_conversation(
    messages,
    tools,
    available_functions,
    original_user_input,
    memory,
    mem_size,
    **kwargs
):
    """
    Run the conversation.
    """
    memory = await follow_conversation(
        user_text=original_user_input,
        memory=memory,
        mem_size=mem_size,
        model=openai_defaults["model"]
    )
    memory.append({"role": "user", "content": original_user_input})

    while len(json.dumps(memory)) > 128000:
        memory.pop(0)

    response = await base_client.chat.completions.create(
        model=openai_defaults["model"],
        messages=memory[-mem_size:],
        tools=tools,
        tool_choice="auto",
        temperature=openai_defaults["temperature"],
        top_p=openai_defaults["top_p"],
        max_tokens=openai_defaults["max_tokens"],
        frequency_penalty=openai_defaults["frequency_penalty"],
        presence_penalty=openai_defaults["presence_penalty"],
    )
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls if hasattr(
        response_message,
        'tool_calls'
    ) else []

    if response_message.content is not None:
        memory.append(
            {
                "role": "assistant",
                "content": response_message.content
            }
        )

    if tool_calls:
        messages.append(response_message)
        executed_tool_call_ids = []

        for tool_call in tool_calls:
            function_name = tool_call.function.name

            if function_name not in available_functions:
                console.print(
                    f"Function {function_name} is not available.",
                    style="red"
                )
                continue

            function_to_call = available_functions[function_name]
            function_args = json.loads(tool_call.function.arguments)

            console.print(
                f"Calling function: {function_name} args: {function_args}",
                style="yellow",
            )
            function_response = await function_to_call(**function_args)
            console.print(
                f"Function {function_name} returned: {function_response}\n",
                style="yellow",
            )

            if function_response is None:
                function_response = "No response received from the function."
            elif not isinstance(function_response, str):
                function_response = json.dumps(function_response)

            function_response_message = {
                "role": "tool",
                "name": function_name,
                "content": function_response,
                "tool_call_id": tool_call.id,
            }

            messages.append(function_response_message)
            executed_tool_call_ids.append(tool_call.id)

        # Ensure the next message prompts the assistant to use tool responses
        messages.append(
            {
                "role": "user",
                "content": f"With the returns from the tool calls in mind, create the best response to the user's original request that was: {original_user_input}",
            }
        )

        # Create next completion ensuring to pass the updated messages array
        second_response = await base_client.chat.completions.create(
            model=openai_defaults["model"],
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=openai_defaults["temperature"],
            top_p=openai_defaults["top_p"],
            max_tokens=openai_defaults["max_tokens"],
            frequency_penalty=openai_defaults["frequency_penalty"],
            presence_penalty=openai_defaults["presence_penalty"],
        )
        return second_response, memory
    else:
        return response, memory


# Define the main function
async def main():
    """
    Main function.
    """

    # Clear the console screen before displaying the welcome message
    os.system("cls" if os.name == "nt" else "clear")

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Voltron: Defender of the Universe'
    )
    parser.add_argument(
        '--talk', action='store_true', help='Use TTS for the final response'
    )
    parser.add_argument(
        '--intro', action='store_true', help='Play the intro video at startup'
    )
    args = parser.parse_args()

    # Set a flag to determine if TTS should be used
    use_tts = args.talk

    # Play the intro video if the --intro argument is provided
    if args.intro:
        play_video('voltron_assemble.mp4')

    # Display the welcome message
    console.print(
        Markdown(
            "# 👋  Voltron: Defender of the Universe. 👋"
        ),
        style="bold blue"
    )

    # Initialize available base functions and tools
    available_functions = {
        "get_current_date_time": get_current_date_time,
        "ask_chat_gpt_4_0314": ask_chat_gpt_4_0314,
        # ... (other default functions)
    }

    # Define the available base tools
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_date_time",
                "description": "Get the current date and time.",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_chat_gpt_4_0314",
                "description": "Ask a smarter AI LLM that is able to understand more complex concepts and perform complex tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "temperature": {
                            "type": "integer",
                            "description": "The temperature associated with request: 0 for factual, 2 for creative.",
                        },
                        "question": {
                            "type": "string",
                            "description": "What's requested to be done with the text.",
                        },
                        "text": {
                            "type": "string",
                            "description": "The text to be analyzed",
                        },
                    },
                    "required": ["question", "text"],
                },
            },
        },
    ]

    # Use the load_plugins_and_get_tools function to conditionally add tools
    available_functions, tools = await load_plugins_and_get_tools(
        available_functions,
        tools
    )

    # Initialize the conversation memory
    memory = []

    # Main Loop
    while True:

        # Ask the user for input
        user_input = Prompt.ask(
            "\nHow can I be of assistance? ([yellow]/tools[/yellow] or [bold yellow]exit or quit[/bold yellow])",
        )

        # Check if the user wants to exit the program
        if user_input.lower() == "exit":
            console.print("\nExiting the program.", style="bold red")
            break

        # Check if the user wants to see the available tools
        elif user_input.lower() == "/tools":
            display_help(tools)
            continue

        # Prepare the conversation messages
        messages = [
            {
                "role": "system",
                "content": ASSISTANT_PROMPT,
            },
            {"role": "user", "content": f"{user_input}"},
        ]

        # Start the spinner
        with live_spinner:

            # Start the spinner
            live_spinner.start()

            # Pass the user input and memory to the run_conversation function
            final_response, memory = await run_conversation(
                messages=messages,
                tools=tools,
                available_functions=available_functions,
                original_user_input=user_input,
                mem_size=10,
                memory=memory,  # Pass the memory variable correctly
            )

            # Stop the spinner
            live_spinner.stop()

        # Print the final response from the model or use TTS
        if final_response:
            final_text = final_response.choices[0].message.content
            if use_tts:
                # Use TTS to output the final response
                console.print("\n" + final_text, style="green")
                tts_output(final_text)
            else:
                # Print the final response to the console
                console.print("\n" + final_text, style="green")
        else:
            # Print an error message if the model did not return a response
            console.print(
                "\nI'm not sure how to help with that.",
                style="red"
            )

        # Remove tools from the tools list after processing
        tools[:] = [
            tool for tool in tools
            if not tool.get("function", {}).get("name", "").lower()
            in user_input.lower()
        ]


# Run the main function
if __name__ == "__main__":
    asyncio.run(
        main()
    )
