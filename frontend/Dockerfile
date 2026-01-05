# -----------------------------------------------------------------------------
# This Dockerfile.bun is specifically configured for projects using Bun
# For npm/pnpm or yarn, refer to the Dockerfile instead
# -----------------------------------------------------------------------------

# Use Bun's official image
FROM oven/bun:1 AS base

WORKDIR /opt/frontend
ENV BUN_INSTALL_CACHE_DIR=/opt/bun-cache

# Install dependencies with bun
FROM base AS deps
COPY package.json bun.lock* ./
RUN bun install --no-save --frozen-lockfile

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /opt/frontend
COPY --from=deps /opt/frontend/node_modules ./node_modules
COPY . .

# Accept build arguments for environment variables
ARG NEXT_PUBLIC_DOJO_HOST
ARG NEXT_PUBLIC_DOJO_ENV

# Set environment variables from build args
ENV NEXT_PUBLIC_DOJO_HOST=${NEXT_PUBLIC_DOJO_HOST}
ENV NEXT_PUBLIC_DOJO_ENV=${NEXT_PUBLIC_DOJO_ENV}

# Next.js collects completely anonymous telemetry data about general usage.
# Learn more here: https://nextjs.org/telemetry
# Uncomment the following line in case you want to disable telemetry during the build.
# ENV NEXT_TELEMETRY_DISABLED=1

RUN bun run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /opt/frontend
COPY --from=deps /opt/bun-cache /opt/bun-cache

# Uncomment the following line in case you want to disable telemetry during runtime.
# ENV NEXT_TELEMETRY_DISABLED=1

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0"

COPY --from=builder /opt/frontend/package.json ./package.json
COPY --from=builder /opt/frontend/components.json ./components.json
COPY --from=builder /opt/frontend/next-env.d.ts ./next-env.d.ts
COPY --from=builder /opt/frontend/next.config.js ./next.config.js
COPY --from=builder /opt/frontend/postcss.config.js ./postcss.config.js
COPY --from=builder /opt/frontend/tailwind.config.js ./tailwind.config.js
COPY --from=builder /opt/frontend/tsconfig.json ./tsconfig.json
COPY --from=builder /opt/frontend/public ./public
COPY --from=builder /opt/frontend/src ./src

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=bun:bun /opt/frontend/.next/standalone ./
COPY --from=builder --chown=bun:bun /opt/frontend/.next/static ./.next/static

USER bun

EXPOSE 3000

CMD ["bun", "./server.js"]
