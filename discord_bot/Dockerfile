FROM python:3.8

RUN pip install docker-py

ADD bot.py /

ENTRYPOINT ["/usr/bin/python", "bot.py"]