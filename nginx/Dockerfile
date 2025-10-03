# syntax=docker/dockerfile:1

FROM rust:slim AS nginx-http-acme-mod

RUN apt-get update && apt-get install --yes --no-install-recommends --no-install-suggests \
        libclang-dev \
        libpcre2-dev \
        libssl-dev \
        zlib1g-dev \
        pkg-config \
        make \
 && rm -rf /var/lib/apt/lists/*

ADD https://github.com/nginx/nginx.git#release-1.29.1 /nginx
ADD https://github.com/nginx/nginx-acme.git#v0.1.1 /nginx-acme

WORKDIR /nginx
RUN auto/configure \
    --with-compat \
    --with-http_ssl_module \
    --add-dynamic-module=/nginx-acme \
    && make modules

FROM nginx:bookworm

COPY --from=nginx-http-acme-mod /nginx/objs/ngx_http_acme_module.so /usr/lib/nginx/modules/
COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d /etc/nginx/conf.d
COPY templates /etc/nginx/templates
COPY 00-dojo-env.sh /docker-entrypoint.d/00-dojo-env.sh

VOLUME ["/var/cache/nginx/acme-letsencrypt"]

EXPOSE 80
EXPOSE 443

CMD ["nginx", "-g", "daemon off;"]
