import asyncio
import collections
import datetime
import os
import sys
from enum import Enum, auto

import discord
import pandas as pd
from sqlalchemy import create_engine


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
    client.belting_ceremony_channel = next(channel for channel in client.guild.channels
                                         if channel.category and channel.category.name.lower() == "the dojo" and channel.name == "belting-ceremony")
    client.voice_state_history = collections.defaultdict(list)
    run_daily(daily_attendance, "17:20:00-07:00")
    run_daily(check_belts, "18:00:00-07:00")

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

    await message.add_reaction("\N{Upwards Black Arrow}")


@client.tree.context_menu(name="Thanks")
async def thank_message(interaction: discord.Interaction, message: discord.Message):
    if interaction.user == message.author:
        await interaction.response.send_message("You cannot thank yourself!", ephemeral=True)
        return

    channel = message.channel
    if channel.category and channel.category.name.lower() == "break room" and channel.name == "memes":
        await interaction.response.send_message("You cannot thank a meme!", ephemeral=True)
        return

    await send_logged_embed(interaction,
                            message,
                            client.thanks_log_channel,
                            title="Thanks",
                            logged_text=f"{interaction.user.mention} thanked {message.author.mention}",
                            ephemeral_text=f"You thanked {message.author.mention}",
                            button_text="Thanks Message")

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
                            button_text="Liked Meme")

    print(f"{describe(interaction.user)} liked {describe(message.author)}'s meme")


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
    senseis = list(role for role in interaction.guild.roles if "sensei" in role.name.lower())

    if not any(interaction.user in sensei.members for sensei in senseis):
        await interaction.response.send_message("You are not a sensei!", ephemeral=True)
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

class Belt(Enum):
    ORANGE_23S  = auto()
    ORANGE      = auto()
    YELLOW_22   = auto()
    YELLOW      = auto()
    BLUE        = auto()
    ERROR       = auto()

    def get_role(self):
        match self:
            case Belt.ORANGE_23S | Belt.ORANGE:
                return "Orange Belt"
            case Belt.YELLOW_22 | Belt.YELLOW:
                return "Yellow Belt"
            case Belt.BLUE:
                return "Blue Belt"
            case _:
                return "Error"

    def get_req_belt(self):
        match self:
            case Belt.ORANGE_23S | Belt.ORANGE:
                return None
            case Belt.YELLOW_22 | Belt.YELLOW:
                return Belt.ORANGE
            case Belt.BLUE:
                return Belt.YELLOW
            case _:
                return Belt.ERROR

    def get_course(self):
        match self:
            case Belt.ORANGE_23S:
                return 62725971    # CSE 365 - Spring 2023
            case Belt.YELLOW_22:
                return -2037203363 # CSE 466 - Fall 2022
            case Belt.ORANGE:
                return 1520512338  # CSE 365 - Fall 2023
            case Belt.YELLOW:
                return -43038396   # CSE 466 - Fall 2023
            case Belt.BLUE:
                return -695929874  # CSE 494 - Spring 2023
            case _:
                return 0

async def announce_belting(member, belt: Belt, append_text=""):
    belt_message = await client.belting_ceremony_channel.send(content=f"{member.mention} earned their {belt.get_role()} {append_text}! :tada:")
    return belt_message

async def _check_belts():
    now = datetime.datetime.now()
    print(f"Checking belts @ {now}")

    engine = create_engine('mariadb+pymysql://ctfd:ctfd@db/ctfd?charset=utf8mb4')

    async def check_belt(belt: Belt):
        role = next(role for role in client.guild.roles if role.name == belt.get_role())
        course = belt.get_course()
        req_role = next(role for role in client.guild.roles if role.name == belt.get_req_belt().get_role()) if belt.get_req_belt() else None

        completion = pd.read_sql(f'''
            select count(*) from dojo_challenges where dojo_id={course};
                                 ''', engine).values[0][0]

        belted = pd.read_sql(f'''
             select u.name, dis.discord_id, max(sub.date), count(sub.date)
             FROM users as u
              JOIN submissions as sub
               ON u.id=.sub.user_id
              JOIN dojo_challenges as d
               ON d.challenge_id=sub.challenge_id
              JOIN discord_users as dis
               ON dis.user_id=u.id
             WHERE d.dojo_id={belt.get_course()}
               AND sub.type='correct'
             GROUP BY u.name
             HAVING count(sub.date)={completion}
             ORDER BY max(sub.date)
          ''', engine)

        for _, row in belted.iterrows():
            try:
                member = await client.guild.fetch_member(row['discord_id'])
            except:
                continue
            if role not in member.roles and (req_role in member.roles or not req_role):
                now = datetime.datetime.now()
                print(f"Awarding {belt.get_role()} to {member.display_name} @ {now}")
                await member.add_roles(role)
                await announce_belting(member, belt, append_text=f" {discord.utils.format_dt(row['max(sub.date)'])}")


    # TODO: remove the  previous course
    await check_belt(Belt.ORANGE_23S)
    await check_belt(Belt.YELLOW_22)

    await check_belt(Belt.ORANGE)
    await check_belt(Belt.YELLOW)
    await check_belt(Belt.BLUE)


@client.tree.command()
async def check_belts(interaction: discord.Interaction):
    senseis = list(role for role in interaction.guild.roles if "sensei" in role.name.lower())

    if not any(interaction.user in sensei.members for sensei in senseis):
        await interaction.response.send_message("You are not a sensei!", ephemeral=True)
        return
    await _check_belts()

client.run(DISCORD_BOT_TOKEN)
