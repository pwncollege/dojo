import os
import datetime

import discord


DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID = os.environ["DISCORD_GUILD_ID"]


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


@client.event
async def on_ready():
    client.guild = client.get_guild(DISCORD_GUILD_ID)
    client.thanks_log_channel = next(channel for channel in client.guild.channels if channel.name == "memes")
    client.memes_log_channel = next(channel for channel in client.guild.channels if channel.name == "memes")

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")


@client.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hi, {interaction.user.mention}", ephemeral=True)


@client.tree.context_menu(name="Show Join Date")
async def show_join_date(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message(f"{member.mention} joined at {discord.utils.format_dt(member.joined_at)}", ephemeral=True)


async def send_logged_embed(interaction, message, log_channel, title, logged_text, ephemeral_text, button_text):
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


@client.tree.context_menu(name="Thanks")
async def thank_message(interaction: discord.Interaction, message: discord.Message):
    if interaction.user == message.author:
        await interaction.response.send_message("You cannot thank yourself!", ephemeral=True)
        return

    thanks_log_channel = interaction.guild.get_channel_or_thread(THANKS_LOG_CHANNEL_ID)

    await send_logged_embed(interaction,
                            message,
                            thanks_log_channel,
                            title="Thanks",
                            logged_text=f"{interaction.user.mention} thanked {message.author.mention}",
                            ephemeral_text=f"You thanked {message.author.mention}",
                            button_text="Thanks Message")


@client.tree.context_menu(name="Like Meme")
async def good_meme(interaction: discord.Interaction, message: discord.Message):
    meme_judge = next(role for role in interaction.guild.roles if role.name == "Meme Judge")

    if interaction.user not in meme_judge.members:
        await interaction.response.send_message("You are not a qualified meme judge!", ephemeral=True)
        return

    await send_logged_embed(interaction,
                            message,
                            client.memes_log_channel,
                            title="Liked Meme",
                            logged_text=f"{interaction.user.mention} liked {message.author.mention}'s meme",
                            ephemeral_text=f"You liked {message.author.mention}'s meme",
                            button_text="Liked Meme")


client.run(DISCORD_BOT_TOKEN)
