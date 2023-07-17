FROM python:3.9-slim-buster

RUN pip install discord-py sqlalchemy pandas PyMySQL

ADD bot.py /

ENTRYPOINT ["/usr/local/bin/python", "bot.py"]
