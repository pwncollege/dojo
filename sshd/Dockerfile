# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS sshpiper-build
WORKDIR /build
RUN apk add --no-cache git
RUN git clone --depth 1 --branch v1.5.3 --recurse-submodules https://github.com/tg123/sshpiper.git /tmp/sshpiper && \
    cd /tmp/sshpiper && \
    go build -tags full -o /out/sshpiperd ./cmd/sshpiperd
COPY sshpiper_plugin/go.mod sshpiper_plugin/go.mod
COPY sshpiper_plugin/main.go sshpiper_plugin/main.go
RUN cd sshpiper_plugin && go mod edit -replace github.com/tg123/sshpiper=/tmp/sshpiper && go mod tidy
RUN cd sshpiper_plugin && CGO_ENABLED=0 go build -o /out/dojo-sshpiper-plugin .

FROM alpine:3.20.3

RUN apk add --no-cache \
    python3 \
    py3-pip \
    openssh-server-pam \
    openssh-client \
    docker-cli

RUN pip3 install --break-system-packages \
    requests \
    docker \
    redis \
    psycopg2-binary

RUN adduser -D hacker && \
    addgroup -g 995 docker && \
    addgroup hacker docker && \
    mkdir -p /home/hacker/.docker /home/hacker/.ssh && \
    chown -R hacker:hacker /home/hacker

RUN mkdir -p /run/sshd

WORKDIR /opt/sshd
COPY . .
COPY --from=sshpiper-build /out/sshpiperd /usr/local/bin/sshpiperd
COPY --from=sshpiper-build /out/dojo-sshpiper-plugin /usr/local/bin/dojo-sshpiper-plugin
RUN chmod 700 /opt/sshd/auth.py

EXPOSE 22

COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
