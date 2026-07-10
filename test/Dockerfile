FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    curl \
    git \
    wget \
    jq \
    ca-certificates \
    python3 \
    python3-pip \
    gnupg \
    xz-utils \
    libgtk-3-0 \
    libasound2t64 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04's apt "firefox" is a snap shim that cannot run in a container;
# install a real Firefox so Selenium Manager never downloads one at runtime.
RUN wget -q -O /tmp/firefox.tar.xz "https://download.mozilla.org/?product=firefox-esr-latest-ssl&os=linux64&lang=en-US" \
    && tar -xJf /tmp/firefox.tar.xz -C /opt \
    && rm /tmp/firefox.tar.xz \
    && ln -s /opt/firefox/firefox /usr/local/bin/firefox

RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.36.0/geckodriver-v0.36.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.36.0-linux64.tar.gz -C /usr/local/bin \
    && rm geckodriver-v0.36.0-linux64.tar.gz \
    && chmod +x /usr/local/bin/geckodriver

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --break-system-packages --no-cache-dir -r /tmp/requirements.txt

RUN npm install -g @playwright/mcp@0.0.32
RUN npx --yes @playwright/mcp@0.0.32 --help 2>/dev/null || true
RUN cd $(npm root -g)/@playwright/mcp && npx playwright install --with-deps

WORKDIR /opt/pwn.college/test
ADD . .

CMD ["pytest"]
