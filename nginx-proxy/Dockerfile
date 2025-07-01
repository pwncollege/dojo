# syntax=docker/dockerfile:1

ARG NGINX_PROXY_VERSION=1.5-alpine

FROM nginxproxy/nginx-proxy:${NGINX_PROXY_VERSION} AS builder

RUN apk add --no-cache build-base pcre-dev zlib-dev openssl-dev git wget

RUN <<EOF
set -e

NGINX_VERSION=$(nginx -v 2>&1 | sed -n 's/.*nginx version: nginx\/\([^ ]*\).*/\1/p')
NGINX_PREFIX=$(nginx -V 2>&1 | sed -n 's/.*--prefix=\([^ ]*\).*/\1/p')
NGINX_MODULES_PATH=$(nginx -V 2>&1 | sed -n 's/.*--modules-path=\([^ ]*\).*/\1/p')

cd /opt
git clone https://github.com/nginx-modules/ngx_http_hmac_secure_link_module.git
wget http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz
tar xzf nginx-${NGINX_VERSION}.tar.gz
cd nginx-${NGINX_VERSION}
./configure --with-compat \
      --add-dynamic-module=/opt/ngx_http_hmac_secure_link_module \
      --prefix="${NGINX_PREFIX}" \
      --modules-path="${NGINX_MODULES_PATH}"
make modules
mv objs/ngx_http_hmac_secure_link_module.so /
EOF

FROM nginxproxy/nginx-proxy:${NGINX_PROXY_VERSION}

COPY --from=builder /ngx_http_hmac_secure_link_module.so /usr/lib/nginx/modules/
COPY ./etc/nginx /etc/nginx

RUN <<EOF
set -e

cat <(echo 'load_module modules/ngx_http_hmac_secure_link_module.so;') \
    <(echo 'load_module modules/ngx_http_js_module.so;') \
    /etc/nginx/nginx.conf > /etc/nginx/nginx.conf.new
mv /etc/nginx/nginx.conf.new /etc/nginx/nginx.conf

echo 'map "" $workspace_secret { default {{ .Env.WORKSPACE_SECRET }}; }' >> /app/nginx.tmpl
echo 'map "" $default_host { default {{ .Env.DEFAULT_HOST }}; }' >> /app/nginx.tmpl
EOF

COPY ./entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["forego", "start", "-r"]
