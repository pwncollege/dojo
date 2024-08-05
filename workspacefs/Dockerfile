FROM alpine:latest

RUN apk add --no-cache \
    fuse \
    fuse-dev \
    gcc \
    musl-dev

COPY workspacefs.c /tmp/workspacefs.c
RUN gcc -Wall /tmp/workspacefs.c `pkg-config fuse --cflags --libs` -o /bin/workspacefs && \
    rm /tmp/workspacefs.c

CMD ["/bin/workspacefs", "-f", "-o", "allow_other", "/run/workspace"]
