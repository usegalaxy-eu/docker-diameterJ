#!/bin/sh
set -eu

# Galaxy supplies its generated job script as `/bin/sh tool_script.sh`. Allow
# that shell command to run normally instead of treating it as analyze_sem.py
# arguments. The Galaxy wrapper invokes this entrypoint again for the analysis.
case "${1:-}" in
    /bin/sh|/bin/bash)
        exec "$@"
        ;;
esac

display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
Xvfb ":${display_number}" -screen 0 1280x1024x24 -nolisten tcp &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null || true' EXIT INT TERM

results_dir="${ANALYSIS_RESULTS_DIR:-/app/results}"
if [ "$(id -u)" = "0" ]; then
    if [ -n "${PUID:-}" ]; then
        run_uid="$PUID"
    elif [ -e "$results_dir" ]; then
        run_uid="$(stat -c %u "$results_dir")"
    else
        run_uid=1000
    fi
    if [ -n "${PGID:-}" ]; then
        run_gid="$PGID"
    elif [ -e "$results_dir" ]; then
        run_gid="$(stat -c %g "$results_dir")"
    else
        run_gid="$run_uid"
    fi

    runtime_home="/tmp/sem-analysis-${run_uid}"
    mkdir -p "$runtime_home"
    chown "$run_uid:$run_gid" "$runtime_home"
    export HOME="$runtime_home"
    exec gosu "$run_uid:$run_gid" python3 /app/src/analyze_sem.py "$@"
fi

exec python3 /app/src/analyze_sem.py "$@"
