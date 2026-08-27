#!/bin/sh
set -eu

run_as_owner() {
    owner_path="$1"
    shift

    if [ "$(id -u)" = "0" ] && [ -e "$owner_path" ]; then
        run_uid="$(stat -c %u "$owner_path")"
        run_gid="$(stat -c %g "$owner_path")"
        if [ "$run_uid" != "0" ]; then
            runtime_home="/tmp/sem-analysis-${run_uid}"
            mkdir -p "$runtime_home"
            chown "$run_uid:$run_gid" "$runtime_home"
            export HOME="$runtime_home"
            exec gosu "$run_uid:$run_gid" "$@"
        fi
    fi

    exec "$@"
}

# Galaxy starts the image with its generated shell script. Match the owner of
# the bind-mounted job directory before that script creates any files.
case "${1:-}" in
    /bin/sh|/bin/bash)
        run_as_owner . "$@"
        ;;
esac

# For direct Docker use, derive ownership from the requested output mount.
results_dir="${ANALYSIS_RESULTS_DIR:-}"
expect_output=0
for argument in "$@"; do
    if [ "$expect_output" = "1" ]; then
        results_dir="$argument"
        break
    fi
    if [ "$argument" = "--output" ]; then
        expect_output=1
    fi
done
results_dir="${results_dir:-/app/results}"

if [ "$(id -u)" = "0" ] && [ -e "$results_dir" ]; then
    run_as_owner "$results_dir" /usr/local/bin/sem-analysis "$@"
fi

display="${DISPLAY:-:99}"
export DISPLAY="$display"

Xvfb "$display" \
    -screen 0 1280x1024x24 \
    -nolisten tcp &

xvfb_pid="$!"

cleanup() {
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Give Xvfb a moment to create its display socket.
attempt=0
while [ ! -S "/tmp/.X11-unix/X${display#:}" ]; do
    attempt=$((attempt + 1))

    if [ "$attempt" -ge 50 ]; then
        echo "Xvfb did not become ready on display $display" >&2
        exit 1
    fi

    sleep 0.1
done

python3 /app/src/analyze_sem.py "$@"
