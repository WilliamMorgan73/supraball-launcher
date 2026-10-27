#!/bin/sh
# Opens this launcher when you press Play on Supraball in Steam.
#
# In Steam: Supraball > Properties > General > Launch Options, enter:
#   "/path/to/steam-launch.sh" %command%
#
# Steam passes the official launcher (via Proton) as the arguments. They are ignored,
# unless this launcher isn't installed, in which case the official one runs as before.

here=$(dirname "$(readlink -f "$0")")
launcher="$here/.venv/bin/supraball-launcher"

if [ ! -x "$launcher" ]; then
    echo "steam-launch.sh: $launcher not found (run 'uv sync' in $here); starting the official launcher" >&2
    exec "$@"
fi

# Steam injects its overlay and runtime libraries for the game; keep them out of the Qt app.
unset LD_PRELOAD LD_LIBRARY_PATH

exec "$launcher"
