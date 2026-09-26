FROM python:3.13.4-slim AS build
WORKDIR /opt/pwn.college

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /opt/pwn.college/
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13.4-slim AS release
WORKDIR /opt/pwn.college

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libffi8 \
        libssl3 \
        git \
        openssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

COPY entrypoint.sh /opt/pwn.college/entrypoint.sh
COPY .coveragerc /opt/pwn.college/.coveragerc
RUN chmod +x /opt/pwn.college/entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH" \
    FLASK_APP=dojo_plugin \
    PYTHONPATH=/opt/pwn.college

EXPOSE 8000
ENTRYPOINT ["/opt/pwn.college/entrypoint.sh"]
