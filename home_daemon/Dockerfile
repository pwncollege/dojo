FROM python:3

RUN pip install flask

RUN mkdir /app
WORKDIR /app
COPY app.py .

ENTRYPOINT ["flask", "run", "--host=0.0.0.0", "--port=80"]