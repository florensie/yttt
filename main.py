import math
import os
import time

import discord
import openai
import requests
from discord import Interaction, Message, Thread
from discord import app_commands
from dotenv import load_dotenv
from openai import InvalidRequestError
from yt_dlp import YoutubeDL

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

MODEL = os.getenv('OPENAI_MODEL') or 'gpt-3.5-turbo'
openai.api_key = os.getenv('OPENAI_API_KEY')

# Set up Discord bot
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    await tree.sync()
    print(f"{client.user} is connected and slash commands are synced.")  # TODO: use logger


# TODO: automatic mode (respond to any youtube link)
# TODO: private option (ephemeral responses and private threads)
@tree.command()
@app_commands.describe(url="The URL or identifier of the Youtube video")
async def summarize(interaction: Interaction, url: str):
    """Summarize a Youtube video"""
    await interaction.response.defer()  # TODO: proper error handling so we always followup

    with YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False)
        title = info['title']
        subtitles = _get_subtitles(info)

    if not subtitles:
        await _error_deferred_repsonse(interaction, "There is not enough information on this video.")
        return

    # TODO: count tokens and fail fast

    # Request a summary from ChatGPT
    print('Sending subs to ChatGPT')
    try:
        completion = await openai.ChatCompletion.acreate(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates summaries of YouTube videos based on their "
                               "captions."
                },
                {
                    "role": "user",
                    "content": f"Summarize the following YouTube video: \"{title}\". Here are the captions:\n\n{subtitles}"
                },
            ],
            temperature=0.7,
            user=str(interaction.user.id)
            # TODO: max response tokens to match discord message limit (minus length of the title)
        )
        summary = completion['choices'][0]['message']['content']
    except InvalidRequestError as e:
        # FIXME: ephemeral doesn't work?
        print(f"Failed to create chat completion:", e)
        await _error_deferred_repsonse(interaction, "Failed to create summary for video")
        return

    # Return the first response of the both as the interaction response
    print('Responding to interaction')
    await interaction.followup.send(f"> ***{title}***\n\n{summary}", wait=True)

    # Create the thread for followup questions
    msg = await interaction.original_response()
    await msg.create_thread(name=title, auto_archive_duration=60)


@client.event
async def on_message(message: Message):
    if message.author != client.user and isinstance(message.channel, Thread) and message.channel.owner == client.user:
        await message.channel.edit(locked=True)  # TODO: ephemeral error reply where locking doesn't work (moderator/permissions)?
        time.sleep(5)  # TODO: unimplemented
        await message.channel.edit(locked=False)  # FIXME: discord.errors.Forbidden: 403 Forbidden (error code: 50001): Missing Access
        await message.channel.send("TEST")


async def _error_deferred_repsonse(interaction: Interaction, message: str):
    """Send an ephemeral error message as followup to a non-ephemeral deferred response"""
    # Remove the original response, so we can send ephemerally
    msg = await interaction.original_response()
    await msg.delete()
    await interaction.followup.send(message, ephemeral=True)


def _get_subtitles(info):
    # Prefer standard subtitles
    sub_formats = _choose_subtitle_language(info)
    if sub_formats:
        for sub in sub_formats:
            if sub['ext'] == 'json3':
                return _dl_subtitle(sub['url'])
        print("Subtitles found but json format not available!")

    return None


def _choose_subtitle_language(info):
    if len(info['subtitles']) > 0:
        for sub_formats in list(info['subtitles'].values())[0]:  # TODO: prefer english/nl
            return sub_formats

    # Fall back to automatic captions
    for lang_key, sub_formats in info['automatic_captions'].items():
        if lang_key.endswith('-orig'):
            return sub_formats


def _dl_subtitle(url):
    json_subs = requests.get(url).json()

    formatted_output = []
    for event in json_subs['events']:
        if 'segs' in event:
            # TODO: don't include sponsored segments
            text = ' '.join([seg['utf8'] for seg in event['segs'] if 'utf8' in seg]).strip()

            if text:
                time = _format_time(event['tStartMs'])
                formatted_output.append(f"{time} {text}")

    return "\n".join(formatted_output)


def _format_time(milliseconds):
    seconds = milliseconds / 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{math.floor(minutes):02d}:{math.floor(seconds):02d}"


client.run(TOKEN)
