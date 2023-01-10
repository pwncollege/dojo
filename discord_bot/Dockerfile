FROM python:3.8

RUN pip install discord-py

ADD bot.py /

ENTRYPOINT ["/usr/local/bin/python", "bot.py"]