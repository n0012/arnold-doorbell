# Setup

## Prerequisites

- **Home Assistant** with `packages` enabled:
  ```yaml
  # configuration.yaml
  homeassistant:
    packages: !include_dir_named packages/
  ```
- **Frigate** (which bundles **go2rtc**), or a standalone go2rtc with its HTTP API on `:1984`.
- A **Reolink** (or other ONVIF) doorbell/camera with a speaker and two-way audio. Tested on **D340W**.
- **ffmpeg** on whatever host runs `scripts/pad-clips.sh`.
- Optional: **frigate-hass-card** (HACS) for the live feed on the dashboard.

Copy `.env.example` → `.env` and fill it in.

## 1. Get the clips

Clips are not in this repo. Fetch for personal use:
```bash
scripts/arnold-download.sh urls.txt ./arnold
```
(See README → *Legal & credits* for the source and terms.)

## 2. Pad the clips

```bash
scripts/pad-clips.sh ./arnold /media/frigate/arnold 1200 2.5
```
Put the output on a volume your **go2rtc/Frigate container can read by path**
(e.g. under Frigate's media mount). ~8 MB for the full library.

Why padding? See README → *The two engineering problems*.

## 3. Add the ONVIF backchannel stream

Merge `frigate/config.snippet.yml` into your Frigate `go2rtc:` config, set your
camera IP, and restart Frigate. Verify:
```bash
curl -s http://GO2RTC_HOST:1984/api/streams | grep doorbell_talk
```

## 4. Smoke-test the pipeline

```bash
curl -X POST "http://GO2RTC_HOST:1984/api/ffmpeg?dst=doorbell_talk&file=/media/frigate/arnold/choppa.mp3"
```
The doorbell should say *"Get to the choppa!"* If the **tail is cut**, increase
the trailing silence in step 2. If the **start is cut**, increase the lead-in
(the ONVIF handshake is slow to open) — or warm the backchannel.

## 5. Install the HA package

```bash
python3 scripts/generate_config.py \
    --clips ./arnold \
    --go2rtc http://GO2RTC_HOST:1984 \
    --stream doorbell_talk \
    --container-dir /media/frigate/arnold \
    --out arnold.yaml
cp arnold.yaml /path/to/homeassistant/packages/arnold.yaml
```
Restart HA (new `rest_command` / `input_*` domains load at startup). Confirm
`script.arnold_play`, `input_select.arnold_clip`, etc. exist in Developer Tools.

## 6. Build the dashboard

Adapt `homeassistant/dashboard-arnold.example.yaml` into a new view, or generate
a fuller board. Each button just calls `script.arnold_play` with a `clip`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| `curl` returns 500 | stream has no backchannel | source must be `onvif://`, not `rtsp://…554` |
| `curl` returns 400 | bad file path/params | check `--container-dir` matches the path *inside* the container |
| Tail of clip cut off | backchannel closes early | more trailing silence (`apad`) |
| Start of clip cut off | slow ONVIF handshake | more lead-in (`adelay`) or warm the channel |
| ~1–1.5 s delay per tap | cold backchannel handshake | expected; warming it trades off with human intercom |
| No audio at all | wrong ONVIF port / creds | Reolink ONVIF is usually `:8000`; verify creds |
