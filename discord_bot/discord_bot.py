import asyncio
import collections
import datetime
import os
import sys

import discord


DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
if not DISCORD_BOT_TOKEN:
    print("No `DISCORD_BOT_TOKEN` specified in environment, quitting.", file=sys.stderr)
    exit(0)

DISCORD_GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])


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


async def send_logged_embed(interaction, message, log_channel, title, logged_text, ephemeral_text, button_text, emoji="\N{Upwards Black Arrow}"):
    emoji = "\N{Upwards Black Arrow}" if emoji is None else emoji
    now = datetime.datetime.utcnow()

    logged_embed = discord.Embed(title=title)
    logged_embed.description = logged_text

    logged_embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    logged_embed.timestamp = now

    logged_url_view = discord.ui.View()
    logged_url_view.add_item(discord.ui.Button(label=button_text, style=discord.ButtonStyle.url, url=message.jump_url))

    logged_message = await log_channel.send(embed=logged_embed, view=logged_url_view)

    ephemeral_embed = discord.Embed(title=title)
    ephemeral_embed.description = ephemeral_text

    ephemeral_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    ephemeral_embed.timestamp = now

    ephemeral_url_view = discord.ui.View()
    ephemeral_url_view.add_item(discord.ui.Button(label=button_text, style=discord.ButtonStyle.url, url=logged_message.jump_url))

    await interaction.response.send_message(embed=ephemeral_embed, view=ephemeral_url_view, ephemeral=True)

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

    if not any(user == client.guild.me async for user in reaction.users()):
        if reaction.emoji.name == "thanks":
            await reaction.remove(user)
        if reaction.emoji.name == "good_meme" and reaction.message.channel.name == "memes":
            await reaction.remove(user)


@client.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hi, {interaction.user.mention}", ephemeral=True)


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

    await send_logged_embed(interaction,
                            message,
                            client.thanks_log_channel,
                            title="Thanks",
                            logged_text=f"{interaction.user.mention} thanked {message.author.mention}",
                            ephemeral_text=f"You thanked {message.author.mention}",
                            button_text="Thanks Message",
                            emoji=client.emoji["thanks"])

    print(f"{describe(interaction.user)} thanked {describe(message.author)}", flush=True)


@client.tree.context_menu(name="Like Meme")
async def like_meme(interaction: discord.Interaction, message: discord.Message):
    meme_judge = next(role for role in interaction.guild.roles if role.name == "Meme Judge")

    if interaction.user not in meme_judge.members:
        await interaction.response.send_message("You are not a qualified meme judge!", ephemeral=True)
        return

    await send_logged_embed(interaction,
                            message,
                            client.liked_memes_log_channel,
                            title="Liked Meme",
                            logged_text=f"{interaction.user.mention} liked {message.author.mention}'s meme",
                            ephemeral_text=f"You liked {message.author.mention}'s meme",
                            button_text="Liked Meme",
                            emoji=client.emoji["good_meme"])

    print(f"{describe(interaction.user)} liked {describe(message.author)}'s meme")


client.run(DISCORD_BOT_TOKEN)
