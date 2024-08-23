FROM python:3.9-slim-buster

RUN pip install discord-py sqlalchemy pandas PyMySQL

ADD discord_bot.py /

ENTRYPOINT ["/usr/local/bin/python", "discord_bot.py"]
