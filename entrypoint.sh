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

# Galaxy supplies its generated job script as `/bin/sh tool_script.sh` while
# bind-mounting the job working directory. Run that script as the directory's
# owner so everything it creates remains writable by Galaxy. This also makes
# the image work with rootless/user-mapped runtimes without chowning mounts.
case "${1:-}" in
    /bin/sh|/bin/bash)
        run_as_owner . "$@"
        ;;
esac

Xvfb "$DISPLAY" -screen 0 1280x1024x24 -nolisten tcp &

results_dir="${ANALYSIS_RESULTS_DIR:-/app/results}"
run_as_owner "$results_dir" python3 /app/src/analyze_sem.py "$@"
