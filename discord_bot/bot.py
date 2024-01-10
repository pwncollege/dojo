import asyncio
import collections
import datetime
import os
import sys
from enum import Enum

import discord

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
if not DISCORD_BOT_TOKEN:
    print("No `DISCORD_BOT_TOKEN` specified in environment, quitting.", file=sys.stderr)
    exit(0)

DISCORD_GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])


# TODO: figure out how to apply correct command permissions automatically


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
intents.voice_states = True

client = PwnCollegeClient(intents=intents)


daily_tasks = set()


def run_daily(task, daily_time):
    time = datetime.time.fromisoformat(daily_time)
    now = datetime.datetime.now(tz=time.tzinfo)
    wait = ((now.replace(hour=time.hour,
                         minute=time.minute,
                         second=time.second,
                         microsecond=time.microsecond,
                         tzinfo=time.tzinfo) - now).total_seconds()
            % datetime.timedelta(days=1).total_seconds())

    async def daily_task():
        await asyncio.sleep(wait)
        await task()
        await asyncio.sleep(1)
        return run_daily(task, daily_time)

    scheduled_task = asyncio.create_task(daily_task())
    daily_tasks.add(scheduled_task)
    scheduled_task.add_done_callback(lambda task: daily_tasks.remove(task))


def describe(user):
    return f"{user.mention} ({user})"


@client.event
async def on_ready():
    client.guild = client.get_guild(DISCORD_GUILD_ID)
    client.thanks_log_channel = next(channel for channel in client.guild.channels
                                     if channel.category and channel.category.name.lower() == "logs" and channel.name == "thanks")
    client.liked_memes_log_channel = next(channel for channel in client.guild.channels
                                          if channel.category and channel.category.name.lower() == "logs" and channel.name == "liked-memes")
    client.attendance_log_channel = next(channel for channel in client.guild.channels
                                         if channel.category and channel.category.name.lower() == "logs" and channel.name == "attendance")
    client.voice_state_history = collections.defaultdict(list)
    run_daily(daily_attendance, "17:20:00-07:00")

    client.emoji = collections.defaultdict()
    for emo in client.emojis:
        client.emoji[emo.name] = emo


@client.event
async def on_voice_state_update(member, before, after):
    print(f"{describe(member)} - {before.channel} -> {after.channel}", flush=True)

    now = datetime.datetime.now()
    client.voice_state_history[member].append((after.channel, now))


@client.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hi, {interaction.user.mention}", ephemeral=True)


@client.tree.context_menu(name="Show Join Date")
async def show_join_date(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.send_message(f"{member.mention} joined at {discord.utils.format_dt(member.joined_at)}", ephemeral=True)


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


async def thread_forum_checkwarn(interaction, message):
    thread = message.channel
    if not isinstance(thread, discord.Thread):
        await interaction.response.send_message("Only forum threads can be tagged!", ephemeral=True)
        return (None, None)

    forum = thread.parent
    if not isinstance(forum, discord.ForumChannel):
        await interaction.response.send_message("Only forum threads can be tagged!", ephemeral=True)
        return (None, None)

    return (thread, forum)


async def is_any_sensei_checkwarn(interaction):
    senseis = list(role for role in interaction.guild.roles if "sensei" in role.name.lower())

    if any(interaction.user in sensei.members for sensei in senseis):
        return True

    await interaction.response.send_message("You are not a sensei!", ephemeral=True)
    return False


@client.tree.context_menu(name="Tag: Good Question")
async def good_question(interaction: discord.Interaction, message: discord.Message):
    if not await is_any_sensei_checkwarn(interaction):
        return

    thread, forum = await thread_forum_checkwarn(interaction, message)

    if thread is None or forum is None:
        return

    good_q_tag = next(tag for tag in forum.available_tags if tag.name=="Good Question")

    await thread.add_tags(good_q_tag)
    await interaction.response.send_message("Tagged: Good Question", ephemeral=True)


async def mark_attendance(member):
    now = datetime.datetime.utcnow()

    logged_embed = discord.Embed(title="Attendance")
    logged_embed.description = f"{member.mention} attended"

    logged_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    logged_embed.timestamp = now

    logged_message = await client.attendance_log_channel.send(embed=logged_embed)
    return logged_message


@client.tree.command()
async def attend(interaction: discord.Interaction, member: discord.Member):
    if not await is_any_sensei_checkwarn(interaction):
        return

    now = datetime.datetime.utcnow()

    logged_message = await mark_attendance(member)

    ephemeral_embed = discord.Embed(title="Attendance")
    ephemeral_embed.description = f"{member.mention} attended"

    ephemeral_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    ephemeral_embed.timestamp = now

    ephemeral_url_view = discord.ui.View()
    ephemeral_url_view.add_item(discord.ui.Button(label="Attendance", style=discord.ButtonStyle.url, url=logged_message.jump_url))

    await interaction.response.send_message(embed=ephemeral_embed, view=ephemeral_url_view, ephemeral=True)
    print(f"{describe(interaction.user)} attended {member}")


async def daily_attendance():
    now = datetime.datetime.now()
    start = now - datetime.timedelta(hours=1)
    required = datetime.timedelta(minutes=30)

    print(f"daily attendance @ {now}")

    for member, history in list(client.voice_state_history.items()):
        history = ([(None, start)] +
                   [(channel, max(time, start)) for channel, time in history] +
                   [(None, now)])

        total_time = datetime.timedelta()
        for (prev_channel, prev_time), (channel, time) in zip(history, history[1:]):
            if prev_channel:
                total_time += time - prev_time

        print(f"attendance - {member} - {total_time}")

        if total_time >= required:
            print(f"Automatically attended {member}")
            await mark_attendance(member)

    client.voice_state_history.clear()


@client.tree.command()
async def help(interaction: discord.Interaction):
    channel = interaction.channel
    user = interaction.user

    if not (isinstance(channel, discord.TextChannel) and channel.name.startswith("help-")):
        await interaction.response.send_message(f"You can only create a private help thread from a help channel!", ephemeral=True)
        return

    thread = await channel.create_thread(name=f"private-help-{user.name}", auto_archive_duration=1440)
    await thread.send("\n".join(["Remember that the goal is to be helpful, and not just answer-giving!",
                                 "If this help session does not need to be private, please move the discussion to a public channel so that others may benefit."
                                 "Add people to this private thread by @mentioning them.",
                                 "This thread will automatically archive after no activity for 1 day."]))
    await thread.add_user(user)

    ephemeral_url_view = discord.ui.View()
    ephemeral_url_view.add_item(discord.ui.Button(label="Private Help Thread", style=discord.ButtonStyle.url, url=thread.jump_url))
    await interaction.response.send_message(view=ephemeral_url_view, ephemeral=True)


@client.event
async def on_reaction_add(reaction, user):
    if isinstance(reaction.emoji, str):
        return

    # Bot must thank first or else emoji is removed
    bot_thanked = [u async for u in reaction.users() if u == client.guild.me]
    if reaction.emoji.name == "thanks" and not bot_thanked:
        await reaction.remove(user)

    # Bot must meme first or else emoji is removed
    bot_memed = [u async for u in reaction.users() if u == client.guild.me]
    meme_chan = reaction.message.channel.name == "memes"
    if reaction.emoji.name == "good_meme" and meme_chan and not bot_memed:
        await reaction.remove(user)

client.run(DISCORD_BOT_TOKEN)
