FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    curl \
    git \
    wget \
    jq \
    firefox \
    ca-certificates \
    python3 \
    python3-pip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install geckodriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.36.0/geckodriver-v0.36.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.36.0-linux64.tar.gz -C /usr/local/bin \
    && rm geckodriver-v0.36.0-linux64.tar.gz \
    && chmod +x /usr/local/bin/geckodriver

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --break-system-packages --no-cache-dir -r /tmp/requirements.txt

# Install Playwright and browsers WITH dependencies
RUN pip install --break-system-packages playwright && playwright install --with-deps

# Install the official Playwright MCP server globally
RUN npm install -g @playwright/mcp@0.0.32

# Pre-download and cache the MCP server with its dependencies
RUN npx --yes @playwright/mcp@0.0.32 --help 2>/dev/null || true

# Install browsers for the global MCP installation
RUN cd $(npm root -g)/@playwright/mcp && npx playwright install --with-deps

WORKDIR /opt/pwn.college/test
ADD . .

CMD ["pytest"]
