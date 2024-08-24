import asyncio
import collections
import datetime
import os
import sys

import aiohttp
import discord


DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
DOJO_HOST = os.environ["DOJO_HOST"]

for required in [DISCORD_BOT_TOKEN, DISCORD_CLIENT_SECRET, DISCORD_GUILD_ID, DOJO_HOST]:
    if not required:
        print(f"No `{required}` specified in environment, quitting.", file=sys.stderr)
        exit(0)  # Exit with success code to avoid restarting the container


class PwnCollegeClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=DISCORD_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


intents = discord.Intents.default()
intents.members = True
client = PwnCollegeClient(intents=intents)


def describe(user):
    return f"{user.mention} ({user})"


async def send_logged_embed(log_channel, title, logged_text, button_text, ephemeral_text=None, emoji=None, *, interaction=None, message=None):
    print(logged_text, flush=True)

    now = datetime.datetime.utcnow()

    logged_embed = discord.Embed(title=title)
    logged_embed.description = logged_text

    if message:
        logged_embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    logged_embed.timestamp = now

    logged_url_view = discord.ui.View()
    logged_url_view.add_item(discord.ui.Button(label=button_text, style=discord.ButtonStyle.url, url=message.jump_url))

    logged_message = await log_channel.send(embed=logged_embed, view=logged_url_view)

    if ephemeral_text and interaction:
        ephemeral_embed = discord.Embed(title=title)
        ephemeral_embed.description = ephemeral_text

        ephemeral_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        ephemeral_embed.timestamp = now

        ephemeral_url_view = discord.ui.View()
        ephemeral_url_view.add_item(discord.ui.Button(label=button_text, style=discord.ButtonStyle.url, url=logged_message.jump_url))

        await interaction.response.send_message(embed=ephemeral_embed, view=ephemeral_url_view, ephemeral=True)

    if emoji and message:
        await message.add_reaction(emoji)


@client.event
async def on_ready():
    client.guild = client.get_guild(DISCORD_GUILD_ID)
    client.thanks_log_channel = next(channel for channel in client.guild.channels
                                     if channel.category and channel.category.name.lower() == "logs" and channel.name == "thanks")
    client.liked_memes_log_channel = next(channel for channel in client.guild.channels
                                          if channel.category and channel.category.name.lower() == "logs" and channel.name == "liked-memes")
    client.emoji = collections.defaultdict()
    for emoji in client.emojis:
        client.emoji[emoji.name] = emoji


@client.event
async def on_reaction_add(reaction, user):
    if isinstance(reaction.emoji, str):
        return

    if user == client.guild.me:
        return

    if reaction.emoji.name == "upvote":
        if reaction.message.channel.name == "memes":
            meme_judge = next(role for role in reaction.message.guild.roles if role.name == "Meme Judge")
            if meme_judge not in user.roles:
                await reaction.remove(user)
                return

            await send_logged_embed(client.liked_memes_log_channel,
                                    title="Liked Meme",
                                    logged_text=f"{user.mention} liked {reaction.message.author.mention}'s meme",
                                    button_text="Liked Meme",
                                    emoji=client.emoji["upvote"],
                                    message=reaction.message)

        else:
            if user == reaction.message.author:
                await reaction.remove(user)
                return

            await send_logged_embed(client.thanks_log_channel,
                                    title="Thanks",
                                    logged_text=f"{user.mention} thanked {reaction.message.author.mention}",
                                    button_text="Thanks Message",
                                    emoji=client.emoji["upvote"],
                                    message=reaction.message)


@client.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hi, {interaction.user.mention}", ephemeral=True)


@client.tree.command()
async def help(interaction: discord.Interaction):
    url = f"{DOJO_HOST}/pwncollege_api/v1/discord/activity/{interaction.user.id}"
    headers = {"Authorization": f"Bearer"}
    response = await aiohttp.request("GET", url, headers=headers)
    data = await response.json()

    if response.status_code == 404:
        await interaction.response.send_message(
            (f"Your discord account is not linked to the dojo: "
                f"[https://{DOJO_HOST}/discord/connect](https://{DOJO_HOST}/discord/connect)"),
            ephemeral=True)
        return

    if not data.get("activity"):
        await interaction.response.send_message("You have not currently working on a challenge!", ephemeral=True)
        return

    current_challenge = data["activity"]["challenge"]["reference_id"]
    await interaction.response.send_message(f"You are currently working on `{current_challenge}`", ephemeral=True)


@client.tree.context_menu(name="Show Join Date")
async def show_join_date(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message(f"{member.mention} joined at {discord.utils.format_dt(member.joined_at)}", ephemeral=True)


@client.tree.context_menu(name="Thanks")
async def thank_message(interaction: discord.Interaction, message: discord.Message):
    if interaction.user == message.author:
        await interaction.response.send_message("You cannot thank yourself!", ephemeral=True)
        return

    if interaction.channel.name == "memes":
        await interaction.response.send_message("You cannot thank a meme!", ephemeral=True)
        return

    await send_logged_embed(client.thanks_log_channel,
                            title="Thanks",
                            logged_text=f"{interaction.user.mention} thanked {message.author.mention}",
                            ephemeral_text=f"You thanked {message.author.mention}",
                            button_text="Thanks Message",
                            emoji=client.emoji["thanks"],
                            interaction=interaction,
                            message=message)


@client.tree.context_menu(name="Like Meme")
async def like_meme(interaction: discord.Interaction, message: discord.Message):
    meme_judge = next(role for role in interaction.guild.roles if role.name == "Meme Judge")

    if interaction.user not in meme_judge.members:
        await interaction.response.send_message("You are not a qualified meme judge!", ephemeral=True)
        return

    await send_logged_embed(client.liked_memes_log_channel,
                            title="Liked Meme",
                            logged_text=f"{interaction.user.mention} liked {message.author.mention}'s meme",
                            ephemeral_text=f"You liked {message.author.mention}'s meme",
                            button_text="Liked Meme",
                            emoji=client.emoji["upvote"],
                            interaction=interaction,
                            message=message)


client.run(DISCORD_BOT_TOKEN)
