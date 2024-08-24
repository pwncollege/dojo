FROM python:3.9-slim-buster

RUN pip install \
    aiohttp \
    discord-py

ADD discord_bot.py /

ENTRYPOINT ["/usr/local/bin/python", "discord_bot.py"]
