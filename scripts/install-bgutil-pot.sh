#!/usr/bin/env bash
set -Eeuo pipefail

DATA_DIR=/var/lib/top40-archiver
POT_DIR="$DATA_DIR/bgutil-ytdlp-pot-provider"
DENO_CACHE="$DATA_DIR/.cache/deno"

BGUTIL_VERSION=1.3.2
BGUTIL_COMMIT=7511309af023b09788dc8f2efc96cc3671291e6c
BGUTIL_REPO=https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git

DENO_BIN=/usr/local/bin/deno
SERVICE_USER=top40archiver
SERVICE_GROUP=top40archiver

id "$SERVICE_USER" >/dev/null 2>&1 || {
    SERVICE_USER=top40
    SERVICE_GROUP=top40
}

command -v git >/dev/null 2>&1 || {
    echo "FOUT: git ontbreekt voor BGUtil-installatie."
    exit 1
}

[ -x "$DENO_BIN" ] || {
    echo "FOUT: Deno ontbreekt: $DENO_BIN"
    exit 1
}

install -d \
  -o "$SERVICE_USER" \
  -g "$SERVICE_GROUP" \
  -m 0750 \
  "$DENO_CACHE"

install_dependencies() {
    local root=$1

    [ -f "$root/server/src/main.ts" ] || {
        echo "FOUT: BGUtil server/src/main.ts ontbreekt."
        return 1
    }

    [ -f "$root/server/deno.json" ] || {
        echo "FOUT: BGUtil server/deno.json ontbreekt."
        return 1
    }

    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$root"

    runuser -u "$SERVICE_USER" -- env \
      HOME="$DATA_DIR" \
      DENO_DIR="$DENO_CACHE" \
      bash -c '
        set -Eeuo pipefail
        cd "$1/server"
        "$2" install --allow-scripts=npm:canvas --frozen
      ' _ "$root" "$DENO_BIN"

    [ -d "$root/server/node_modules" ] || {
        echo "FOUT: Deno maakte geen server/node_modules."
        return 1
    }
}

current_commit=""

if [ -d "$POT_DIR/.git" ]; then
    current_commit=$(git -C "$POT_DIR" rev-parse HEAD 2>/dev/null || true)
fi

if [ "$current_commit" = "$BGUTIL_COMMIT" ]; then
    echo "BGUtil $BGUTIL_VERSION broncode is al correct."
    install_dependencies "$POT_DIR"
else
    echo "BGUtil $BGUTIL_VERSION installeren..."

    NEXT="${POT_DIR}.next.$$"
    OLD="${POT_DIR}.old.$$"

    rm -rf "$NEXT" "$OLD"

    cleanup() {
        rm -rf "$NEXT"
    }
    trap cleanup EXIT

    git clone \
      --single-branch \
      --branch "$BGUTIL_VERSION" \
      "$BGUTIL_REPO" \
      "$NEXT"

    actual=$(git -C "$NEXT" rev-parse HEAD)

    [ "$actual" = "$BGUTIL_COMMIT" ] || {
        echo "FOUT: onverwachte BGUtil commit: $actual"
        return_code=1
        exit "$return_code"
    }

    install_dependencies "$NEXT"

    if [ -e "$POT_DIR" ]; then
        mv "$POT_DIR" "$OLD"
    fi

    if ! mv "$NEXT" "$POT_DIR"; then
        if [ -e "$OLD" ]; then
            mv "$OLD" "$POT_DIR"
        fi
        echo "FOUT: BGUtil atomische installatie mislukt."
        exit 1
    fi

    rm -rf "$OLD"
    trap - EXIT
fi

chown -R "$SERVICE_USER:$SERVICE_GROUP" "$POT_DIR"

echo "BGUtil provider gereed:"
echo "  versie : $BGUTIL_VERSION"
echo "  commit : $(git -C "$POT_DIR" rev-parse HEAD)"
echo "  server : $POT_DIR/server"
echo "  deno   : $("$DENO_BIN" --version | head -n1)"
