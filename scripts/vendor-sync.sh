#!/bin/sh
# Replace a vendored compose file with upstream's copy from its marker URL.
#
# Usage: scripts/vendor-sync.sh <compose.yaml> [<old-version> <new-version>]
#
# The first line of <compose.yaml> must be "# vendor: <url>". When both
# versions are given and the URL contains "/<old-version>/", that path segment
# becomes "/<new-version>/" before the download. The file is rewritten as the
# updated marker line followed by upstream's bytes.
set -eu

file=$1
marker=$(head -n 1 "$file")
case $marker in
  "# vendor: "*) url=${marker#"# vendor: "} ;;
  *) echo "vendor-sync: $file: first line is not '# vendor: <url>'" >&2; exit 1 ;;
esac

if [ $# -eq 3 ]; then
  case $url in
    *"/$2/"*) url="${url%%"/$2/"*}/$3/${url#*"/$2/"}" ;;
  esac
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$url" -o "$tmp"
{ printf '# vendor: %s\n' "$url"; cat "$tmp"; } > "$file"
