# Arguments: <compose project> <service> <timeout seconds> <check command...>
# Prints the outcome on the first line: idle, busy, check_failed, or
# not_deployed. Any further lines are the reason.
project=$1
service=$2
limit=$3
shift 3

if ! containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project" 2>&1); then
    printf 'check_failed\ndocker error: %s\n' "$containers"
    exit 0
fi
if [ -z "$containers" ]; then
    printf 'not_deployed\nnothing deployed\n'
    exit 0
fi
if ! running=$(docker ps -q \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service" \
    --filter status=running 2>&1); then
    printf 'check_failed\ndocker error: %s\n' "$running"
    exit 0
fi
if [ -z "$running" ]; then
    printf 'check_failed\nservice not running\n'
    exit 0
fi
container=$(printf '%s\n' "$running" | head -n 1)

detail=$(timeout -k 5 "$limit" docker exec "$container" "$@" 2>&1 >/dev/null)
rc=$?
case $rc in
    0) echo idle; exit 0 ;;
    1) echo busy; exit 0 ;;
    124 | 137) reason="timed out after ${limit}s" ;;
    *) reason="exited $rc" ;;
esac
printf 'check_failed\n%s%s\n' "$reason" "${detail:+: $detail}"
