#!/usr/bin/env bash
# Fetch the Arnold clip library for PERSONAL use.
#
# Clips are NOT included in this repo (they're copyrighted — see README).
# Supply your own source. Be a good citizen: rate-limit, personal use only,
# don't hammer whatever host you point this at.
#
# Provide a urls.txt (one URL per line). A sample list of filenames the
# soundboard's curated buttons expect is in docs/curated-clips.txt.
#
# Usage: ./arnold-download.sh <urls.txt> <dst_dir>

set -euo pipefail
URLS="${1:?usage: arnold-download.sh <urls.txt> <dst_dir>}"
DST="${2:?usage: arnold-download.sh <urls.txt> <dst_dir>}"
mkdir -p "$DST"

while IFS= read -r url; do
  [ -z "$url" ] && continue
  case "$url" in \#*) continue;; esac
  fn="$(basename "$url")"
  echo "-> $fn"
  curl -fsSL --retry 2 -o "$DST/$fn" "$url" || echo "  (skip: $url)"
  sleep 0.5   # be nice to the host
done < "$URLS"

echo "done -> $DST"
echo "Clips are © their respective rights holders — personal use only."
