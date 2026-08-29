# Custom Caddy build - the stock caddy:2-alpine image doesn't include
# the rate-limiting module (it's a community plugin, not core Caddy).
# xcaddy compiles it in. This build itself can run in CI (GitHub
# Actions) and get pushed to GHCR alongside the app image - no local
# Docker needed.
FROM caddy:2-builder-alpine AS builder

RUN xcaddy build \
    --with github.com/mholt/caddy-ratelimit

FROM caddy:2-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
