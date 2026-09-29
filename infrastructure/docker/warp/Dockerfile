# Optional Cloudflare WARP egress for yt-dlp (ADR-014): wgcf registers, wireproxy serves SOCKS5.
FROM alpine:3.22

ARG TARGETARCH
ARG WGCF_VERSION=2.3.0
ARG WIREPROXY_VERSION=1.1.3

# sha256 values are from each release's own checksums.txt; bump them with the versions.
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) \
        wgcf_sha=01614e38c0eb5f3405232e71cfaf02d64d4809e4988ad8f5a8071af16d193405; \
        wireproxy_sha=e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c ;; \
      arm64) \
        wgcf_sha=dcadadc42bcc410a4032a6d1c0490ea510e199f0aaaee397dc1aa0fbd27038e8; \
        wireproxy_sha=370e00bd2167960d1ecd1c3c1439715bbaa94a0a110a2040468670c9af6021b6 ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apk add --no-cache ca-certificates; \
    wget -q -O /usr/local/bin/wgcf \
      "https://github.com/ViRb3/wgcf/releases/download/v${WGCF_VERSION}/wgcf_${WGCF_VERSION}_linux_${TARGETARCH}"; \
    wget -q -O /tmp/wireproxy.tar.gz \
      "https://github.com/windtf/wireproxy/releases/download/v${WIREPROXY_VERSION}/wireproxy_linux_${TARGETARCH}.tar.gz"; \
    echo "${wgcf_sha}  /usr/local/bin/wgcf" | sha256sum -c -; \
    echo "${wireproxy_sha}  /tmp/wireproxy.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/wireproxy.tar.gz -C /usr/local/bin wireproxy; \
    rm /tmp/wireproxy.tar.gz; \
    chmod 0755 /usr/local/bin/wgcf /usr/local/bin/wireproxy; \
    adduser -D -u 10002 warp; \
    mkdir -p /data; \
    chown warp:warp /data

COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

USER warp
WORKDIR /data
ENTRYPOINT ["/entrypoint.sh"]
