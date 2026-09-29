#!/bin/sh
# Registers a free WARP identity once (kept in /data), then serves it as a SOCKS5 proxy.
set -eu
cd /data

if [ ! -f wgcf-profile.conf ]; then
  # An account without a profile is a half-finished earlier run; register refuses to run twice.
  if [ ! -f wgcf-account.toml ]; then
    if [ "${WARP_ACCEPT_TOS:-}" != "yes" ]; then
      echo "warp: registering needs WARP_ACCEPT_TOS=yes — you accept Cloudflare's terms:" >&2
      echo "warp: https://www.cloudflare.com/application/terms/" >&2
      exit 1
    fi
    wgcf register --accept-tos
  fi
  wgcf generate
fi

cat > /tmp/wireproxy.conf <<EOF
WGConfig = /data/wgcf-profile.conf

[Socks5]
BindAddress = 0.0.0.0:40000
EOF

exec wireproxy -c /tmp/wireproxy.conf
