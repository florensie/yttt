import math
import os

import discord
import openai
import requests
from discord import Interaction
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
@tree.command()
@app_commands.describe(url="The URL or identifier of the Youtube video")
async def summarize(interaction: Interaction, url: str):
    """Summarize a Youtube video"""
    await interaction.response.defer()

    with YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False)
        title = info['title']
        subtitles = _get_subtitles(info)

    if not subtitles:
        await interaction.followup.send("There is not enough information on this video.", ephemeral=True)
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
        await interaction.followup.send(f"Failed to create summary for video", ephemeral=True, wait=True)
        return

    # Return the first response of the both as the interaction response, and create a thread for followup questions
    print('Responding to interaction')
    await interaction.followup.send(f"> ***{title}***\n\n{summary}", wait=True)
    msg = await interaction.original_response()
    await msg.create_thread(name=title)


def _get_subtitles(info):
    # Prefer standard subtitles
    if len(info['subtitles']) > 0:
        for sub in list(info['subtitles'].values())[0]:  # TODO: prefer english/nl
            if sub['ext'] == 'json3':
                return _dl_subtitle(sub['url'])

    # Fall back to automatic captions
    for lang_key, subs in info['automatic_captions'].items():
        if lang_key.endswith('-orig'):
            for sub in subs:
                if sub['ext'] == 'json3':
                    return _dl_subtitle(sub['url'])

    return None


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
