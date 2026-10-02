# Arguments: <compose project> <service> <timeout seconds> <check command...>
# Prints one outcome key on the first line, then optional detail. The role maps
# the key through lxc_busy_check_outcomes.
project=$1
service=$2
limit=$3
shift 3

if ! containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project" 2>&1); then
    printf 'docker-error\n%s\n' "$containers"
    exit 0
fi
if [ -z "$containers" ]; then
    echo not-deployed
    exit 0
fi
if ! running=$(docker ps -q \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service" \
    --filter status=running 2>&1); then
    printf 'docker-error\n%s\n' "$running"
    exit 0
fi
if [ -z "$running" ]; then
    echo service-not-running
    exit 0
fi
container=$(printf '%s\n' "$running" | head -n 1)

detail=$(timeout -k 5 "$limit" docker exec "$container" "$@" 2>&1 >/dev/null)
printf 'rc=%s\n%s\n' "$?" "$detail"
