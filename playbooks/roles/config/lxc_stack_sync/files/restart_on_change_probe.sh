# Runs in a stack directory.
# Arguments: <compose project>, then "=<path>" for each file the stack syncs
# from the repo and "<service>=<path>" for each x-restart-on-change
# declaration, with paths relative to the stack directory.
# A service tracks every synced file it bind-mounts on its own, matched by
# inode, plus its declared files. Prints "<service> <file>..." for each service
# with a tracked file modified after one of its containers last started.
# Containers of services no longer in the Compose files are ignored.
project=$1
shift
services=$(docker compose -p "$project" config --services) || exit 1
ids=$(docker ps -aq \
    --filter "label=com.docker.compose.project=$project" \
    --filter label=com.docker.compose.oneoff=False) || exit 1
[ -n "$ids" ] || exit 0
# shellcheck disable=SC2086 # one container id per word
containers=$(docker inspect --format \
    '{{index .Config.Labels "com.docker.compose.service"}} {{.State.StartedAt}}{{range .Mounts}}{{if eq .Type "bind"}} {{.Source}}{{end}}{{end}}' \
    $ids) || exit 1

stale=
while read -r service started sources; do
    printf '%s\n' "$services" | grep -qxF "$service" || continue
    born=$(date -d "$started" +%s%N) || exit 1
    tracked=
    for source in $sources; do
        [ -f "$source" ] || continue
        for arg; do
            case $arg in
                =*) [ "$source" -ef "${arg#=}" ] && tracked="$tracked ${arg#=}" ;;
            esac
        done
    done
    for arg; do
        case $arg in "$service="*) tracked="$tracked ${arg#*=}" ;; esac
    done
    for path in $tracked; do
        if [ "$(date -r "$path" +%s%N)" -gt "$born" ]; then
            stale="$stale$service $path
"
        fi
    done
done <<EOF
$containers
EOF
printf '%s' "$stale" | sort -u | awk '{ files[$1] = files[$1] " " $2 } END { for (s in files) print s files[s] }'
