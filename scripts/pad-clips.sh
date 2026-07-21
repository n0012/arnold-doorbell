#!/usr/bin/env bash
# Pad every .mp3 with a short lead-in + trailing silence.
#
# WHY: go2rtc closes the ONVIF backchannel the instant the file's audio ends,
# which clips the last word ("...choppa!"). Trailing silence keeps the channel
# open long enough for the real audio to fully flush to the speaker. A little
# lead-in silence covers the backchannel handshake so the first word isn't cut.
#
# Also downmixes to 16 kHz mono, which the doorbell backchannel is happy with.
#
# Usage:  ./pad-clips.sh <src_dir> <dst_dir> [lead_ms] [tail_s]
# Example: ./pad-clips.sh ./arnold /media/frigate/arnold 1200 2.5

set -euo pipefail

SRC="${1:?usage: pad-clips.sh <src_dir> <dst_dir> [lead_ms] [tail_s]}"
DST="${2:?usage: pad-clips.sh <src_dir> <dst_dir> [lead_ms] [tail_s]}"
LEAD_MS="${3:-1200}"     # lead-in silence, milliseconds
TAIL_S="${4:-2.5}"       # trailing silence, seconds

mkdir -p "$DST"
n=0; fail=0
for f in "$SRC"/*.mp3; do
  [ -e "$f" ] || continue
  b="$(basename "$f")"
  if ffmpeg -y -loglevel error -i "$f" \
      -af "adelay=${LEAD_MS}:all=1,apad=pad_dur=${TAIL_S}" \
      -ar 16000 -ac 1 "$DST/$b" 2>/dev/null; then
    n=$((n+1))
  else
    fail=$((fail+1)); echo "FAILED: $b" >&2
  fi
done
echo "padded OK: $n   failed: $fail   -> $DST"
