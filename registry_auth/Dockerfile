FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install Flask PyJWT cryptography requests gunicorn pyOpenSSL SQLAlchemy pymysql psycopg2-binary


CMD ["gunicorn", "-b", "0.0.0.0:8080", "auth:app", "--log-level", "debug", "--access-logfile", "-"]
