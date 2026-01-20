import os
import re
import subprocess
import discord
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import html
import textwrap

# load env
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

CACHE_DIR = "man_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def sanitize_command(cmd: str) -> str:
    if not re.match(r"^[A-Za-z0-9._+\-]+$", cmd):
        raise ValueError("Invalid command name.")
    return cmd

def get_cache_path(cmd: str) -> str:
    return os.path.join(CACHE_DIR, f"{cmd}.txt")

CHEAT_SH_URL = "https://cheat.sh/{cmd}?Man"
MAN7_URL = "https://man7.org/linux/man-pages/man1/{cmd}.1.html"
MANPAGES_ORG = "https://manpages.org/{cmd}/1"

HEADERS = {"User-Agent": "pwn-college-man-bot/1.0"}

def fetch_from_cheatsh(cmd: str) -> str | None:
    """Fetch plain-text man-like page from cheat.sh, or None if unavailable."""
    try:
        url = CHEAT_SH_URL.format(cmd=cmd)
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200 or not r.text.strip():
            return None

        text = r.text.strip()

        if "<html" in text.lower():
            soup = BeautifulSoup(text, "html.parser")
            pre = soup.find("pre")
            if pre and pre.get_text(strip=False):
                text = pre.get_text()
            else:
                body = soup.body or soup
                for s in body(["script", "style", "nav", "header", "footer"]):
                    s.decompose()
                text = body.get_text("\n").strip()

        lower = text.lower()
        if (
            "unknown topic" in lower
            or "did you mean" in lower
            or "no such file or directory" in lower
            or not text.strip()
        ):
            return None  

        return text
    except Exception:
        return None



def fetch_from_man7(cmd: str) -> str | None:
    try:
        url = MAN7_URL.format(cmd=cmd)
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code == 200 and r.text:
            soup = BeautifulSoup(r.text, "html.parser")
            pre = soup.find("pre")
            if pre and pre.get_text(strip=False):
                return html.unescape(pre.get_text())
            article = soup.find("article") or soup.find("main")
            if article:
                for s in article(["script", "style", "nav", "header", "footer"]):
                    s.decompose()
                txt = article.get_text("\n")
                if txt and len(txt) > 50:
                    return txt
    except Exception:
        pass
    return None

def fetch_from_manpages_org(cmd: str) -> str | None:
    """Fetch plain-text man page from manpages.org, return None if not found."""
    try:
        url = MANPAGES_ORG.format(cmd=cmd)
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200 or not r.text:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        pre = soup.find("pre")
        if pre and pre.get_text(strip=False):
            text = pre.get_text()
        else:
            main = soup.find("main") or soup
            for s in main(["script", "style", "nav", "header", "footer"]):
                s.decompose()
            text = main.get_text("\n").strip()

        lower = text.lower()
        if (
            "couldn't found manual page" in lower
            or "no manual entry" in lower
            or "not found" in lower
            or "unknown topic" in lower
            or "searching for" in lower
            or len(text.strip()) < 40  
        ):
            return None

        return text
    except Exception:
        return None


def fetch_online_man(cmd: str) -> str:
    """Try multiple online sources and return plain-text man content or raise."""
    try_funcs = [fetch_from_cheatsh, fetch_from_man7, fetch_from_manpages_org]
    tried = []
    for fn in try_funcs:
        tried.append(fn.__name__)
        content = fn(cmd)
        if content and content.strip():
            footer = f"\n\n(Man page fetched from online source: {fn.__name__})"
            return content + footer
    raise RuntimeError(f"Online fetch failed. Tried: {', '.join(tried)}")

def get_man_page(cmd: str, refresh: bool = False) -> str:
    """
    Primary flow:
      1) sanitize command
      2) return cached file if exists (unless refresh)
      3) try local `man` invocation
      4) try online sources (cheat.sh, man7.org, manpages.org)
      5) cache and return result or raise
    """
    cmd = sanitize_command(cmd)
    cache_file = get_cache_path(cmd)

    if os.path.exists(cache_file) and not refresh:
        with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        result = subprocess.run(
            ["man", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PAGER": "cat", "LANG": "C"},
            timeout=8
        )
        output = (result.stdout or result.stderr).strip()
        if output and "No manual entry" not in output:
            output_with_footer = output + "\n\n(Man page rendered by local `man` command)"
            clean_text = normalize_man_text(output_with_footer)
            with open(cache_file, "w", encoding="utf-8", errors="replace") as f:
                f.write(clean_text)
                return clean_text
        
        else:
            try:
                online_text = fetch_online_man(cmd)
                clean_text = normalize_man_text(online_text)
                with open(cache_file, "w", encoding="utf-8", errors="replace") as f:
                    f.write(clean_text)
                return clean_text
            except Exception as e:
                raise RuntimeError(f"No local or online man page found: {e}")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    try:
        online_text = fetch_online_man(cmd)
        with open(cache_file, "w", encoding="utf-8", errors="replace") as f:
            f.write(online_text)
        return online_text
    except Exception as e:
        raise RuntimeError(f"Could not find man page locally or online: {e}")

def extract_sections(man_text: str) -> dict:
    sections = {}
    lines = man_text.split('\n')
    current_section = "HEADER"
    current_content = []

    for line in lines:
        if line.strip() and line.strip().isupper() and len(line.strip()) > 2:
            if current_content:
                sections[current_section] = '\n'.join(current_content)
            current_section = line.strip()
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_section] = '\n'.join(current_content)

    return sections

def normalize_man_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r".\x08", "", text)
    text = re.sub(r"\x1B\[[0-9;]*[A-Za-z]", "", text)
    text = html.unescape(text)
    text = BeautifulSoup(text, "html.parser").get_text()
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [re.sub(r"^\s+", "", line) for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n([A-Z][A-Z0-9 \-]{2,})\n[-=]{3,}\n", r"\n\1\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    wrapped = [textwrap.fill(p, width=80) for p in paragraphs]
    text = "\n\n".join(wrapped)

    return text.strip()



class ManPageView(ui.View):
    def __init__(self, command: str, man_text: str, sections: dict):
        super().__init__(timeout=300)
        self.command = command
        self.man_text = man_text
        self.sections = sections
        self.current_page = 0
        self.page_size = 1800
        self.chunks = [man_text[i:i+self.page_size] for i in range(0, len(man_text), self.page_size)]
        self.current_section = "FULL"
        self.message = None
        self.colors = [0xFF0000, 0xFF6600, 0xFFFF00, 0x00FF00, 0x00FFFF, 0x0066FF, 0x9900FF, 0xFF00FF]
        if len(sections) > 1:
            self.add_item(SectionSelect(list(sections.keys())[:25]))

    def get_embed(self) -> discord.Embed:
        if self.current_section == "FULL":
            content = self.chunks[self.current_page]
            total = len(self.chunks)
            current = self.current_page + 1
        else:
            content = self.sections.get(self.current_section, "Section not found")[:self.page_size]
            total = 1
            current = 1

        color = self.colors[self.current_page % len(self.colors)]
        progress = "█" * (current * 20 // total) + "░" * (20 - (current * 20 // total))

        embed = discord.Embed(
            title=f"man {self.command}",
            description=f"```\n{content}\n```",
            color=color
        )

        if self.current_section != "FULL":
            embed.add_field(
                name="Current Section",
                value=f"`{self.current_section}`",
                inline=True
            )

        embed.add_field(
            name="Progress",
            value=f"`[{progress}]` {current}/{total}",
            inline=True
        )

        embed.set_footer(text=f"pwn.college :: Page {current}/{total}")
        embed.timestamp = discord.utils.utcnow()

        return embed

    @ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_section == "FULL" and self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.send_message("Already at first page", ephemeral=True)

    @ui.button(label="▶️ Next", style=discord.ButtonStyle.primary, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.current_section == "FULL" and self.current_page < len(self.chunks) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.send_message("Already at last page", ephemeral=True)

    @ui.button(label="🔍 Search", style=discord.ButtonStyle.secondary, custom_id="search")
    async def search_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @ui.button(label="🏠 Full View", style=discord.ButtonStyle.success, custom_id="full")
    async def full_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_section = "FULL"
        self.current_page = 0
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="❌ Close", style=discord.ButtonStyle.danger, custom_id="close")
    async def close_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Session terminated - Man page closed", embed=None, view=None)
        self.stop()

class SectionSelect(ui.Select):
    def __init__(self, sections: list):
        options = [
            discord.SelectOption(
                label=section[:100] if len(section) <= 100 else section[:97] + "...",
                value=section,
                emoji="📖"
            )
            for section in sections
        ]
        super().__init__(
            placeholder="Jump to section...",
            options=options[:25],
            custom_id="section_select"
        )

    async def callback(self, interaction: discord.Interaction):
        view: ManPageView = self.view
        view.current_section = self.values[0]
        view.current_page = 0
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

class SearchModal(ui.Modal, title="Search Man Page"):
    search_term = ui.TextInput(
        label="Search Query",
        placeholder="Enter text to search...",
        required=True,
        max_length=100
    )

    def __init__(self, view: ManPageView):
        super().__init__()
        self.man_view = view

    async def on_submit(self, interaction: discord.Interaction):
        query = self.search_term.value.lower()
        results = []

        for i, chunk in enumerate(self.man_view.chunks):
            if query in chunk.lower():
                results.append(i)

        if results:
            self.man_view.current_page = results[0]
            self.man_view.current_section = "FULL"
            await interaction.response.edit_message(
                embed=self.man_view.get_embed(),
                view=self.man_view
            )
            await interaction.followup.send(
                f"Found {len(results)} match(es). Jumped to first occurrence.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"No results found for: `{query}`",
                ephemeral=True
            )

@bot.event
async def on_ready():
    print("[+] Ready")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for !man commands | pwn.college"
        )
    )

@bot.command()
async def man(ctx, *, command: str):
    """Interactive man page viewer with buttons and search"""
    loading = await ctx.send("Loading manual...")
    try:
        output = get_man_page(command)
        if not output or "No manual entry" in output:
            await loading.edit(content=f"No manual entry for `{command}`")
            return

        header = (
            "```\n"
            "╔═══════════════════════════════════════════════╗\n"
            "║  pwn.college :: MANUAL EXPLOITATION FRAMEWORK ║\n"
            f"║  Target: {command.ljust(40)}              ║\n"
            "╚═══════════════════════════════════════════════╝\n"
            "```\n"
        )

        full_text = header + output
        sections = extract_sections(output)
        view = ManPageView(command, full_text, sections)
        await loading.edit(content=None, embed=view.get_embed(), view=view)
        view.message = loading

    except Exception as e:
        await loading.edit(content="Invalid command, try again.")

@bot.command()
async def manrefresh(ctx, *, command: str):
    try:
        _ = get_man_page(command, refresh=True)
        await ctx.send(f"Cache refreshed for `{command}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command()
async def manclear(ctx, *, command: str):
    try:
        path = get_cache_path(command)
        if os.path.exists(path):
            os.remove(path)
            await ctx.send(f"Cache wiped for `{command}`")
        else:
            await ctx.send(f"No cache found for `{command}`")
    except Exception as e:
        await ctx.send(f"Error: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)
