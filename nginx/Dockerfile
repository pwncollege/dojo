# syntax=docker/dockerfile:1

FROM rust:slim AS nginx-mod

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
ADD https://github.com/nginx-modules/ngx_http_hmac_secure_link_module.git#dc641de /ngx_http_hmac_secure_link_module

WORKDIR /nginx
RUN auto/configure \
    --with-compat \
    --with-http_ssl_module \
    --add-dynamic-module=/nginx-acme \
    --add-dynamic-module=/ngx_http_hmac_secure_link_module \
    && make modules

FROM nginx:bookworm

COPY --from=nginx-mod /nginx/objs/ngx_http_acme_module.so /usr/lib/nginx/modules/
COPY --from=nginx-mod /nginx/objs/ngx_http_hmac_secure_link_module.so /usr/lib/nginx/modules/
COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d /etc/nginx/conf.d
COPY templates /etc/nginx/templates
COPY 00-dojo-env.sh /docker-entrypoint.d/00-dojo-env.sh

VOLUME ["/var/cache/nginx/acme-letsencrypt"]

EXPOSE 80
EXPOSE 443

CMD ["nginx", "-g", "daemon off;"]
