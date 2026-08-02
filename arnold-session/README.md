# arnold-session — optional warm-session sidecar

A ~180-line stdlib-only Python service that sits between Home Assistant and
go2rtc. It cuts first-tap latency and turns one silent failure mode into a loud
one. **Entirely optional** — the base setup works without it.

```
HA rest_command -> arnold-session :8098 -> go2rtc :1984 -> doorbell speaker
```

## Why

go2rtc tears down the RTSP session to the doorbell after every clip, so each tap
pays a fresh handshake. Holding a consumer open on the talk stream keeps that
session established.

Measured on a Reolink Video Doorbell WiFi, 30s idle gaps between taps:

| Condition | Latency |
| --- | --- |
| No warm session (5 runs) | 1.53–1.60s, mean **1.55s** |
| Warm session held (3 runs) | 0.43–0.87s, mean **0.72s** |

Roughly **2x**. With a pre-warm on the doorbell press, the *first* clip lands in
**~0.43s** instead of ~1.8s.

The saving is the RTSP handshake, not anything local: ffmpeg spawn is only
~0.15s of the 1.55s, and the camera answers ONVIF in ~90ms.

## Behaviour

- First tap opens the session (~1.8s, pays the cold handshake).
- Subsequent taps reuse it (~0.3–1.0s).
- After `IDLE_TIMEOUT` seconds with no taps, the session drops.
- `/warm` opens it ahead of time — wire it to your doorbell press sensor.
- The keepalive reconnects itself if it drops mid-session.

Latency degrades back toward cold under rapid repeated taps (measured
0.26s → 1.29s firing every 4s), recovering after a pause. Cause not identified;
it is not producer accumulation, ffmpeg processes, or backchannel contention —
all three were measured and ruled out.

## Does this block the intercom?

This was the main reason the base build stayed cold-on-demand. Measured from
inside the Frigate container (`ss` on the host cannot see the container's
sockets):

| | Idle | Session held |
| --- | --- | --- |
| TCP connections to doorbell | 2 | **3** (extra on `:554`) |
| Receive rate | baseline | **+~4.7 Mbps** |
| Frigate CPU | 32.5% | 34.2% (noise) |

The extra connection is go2rtc pulling the **hi-res** stream on `:554` to keep
the session alive. Crucially **no connection to `:8000` is held** at any point —
idle, warm, during a clip, or after. The warm session holds a *video* stream,
not the ONVIF backchannel, so the reported failure mode where an open
backchannel disables the chime and strands the doorbell in 2-way mode does not
appear to apply. Verified by mechanism, not by ringing the bell — confirm on
your own hardware before relying on it.

That ~4.7 Mbps is not free, especially on the **WiFi** doorbell. It is why the
pre-warm is wired to an actual doorbell press rather than to person detection,
which fires on every passer-by.

## Clip validation

go2rtc returns **HTTP 200 for a missing file**. If the clip directory moves or
disappears, every tap silently does nothing while HA logs success. This service
checks the file exists first and returns 404. See the storage gotcha in the main
[README](../README.md#design-notes--gotchas).

Clip names are validated against `^[A-Za-z0-9][A-Za-z0-9._-]*$` before use in a
path, since the endpoint is reachable on the LAN.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /play?clip=NAME` | Warm the session and play `NAME.mp3` |
| `GET/POST /warm` | Open the session without playing |
| `GET /status` | Session state and idle time |
| `GET /healthz` | Container healthcheck |

## Config

| Var | Default | Notes |
| --- | --- | --- |
| `GO2RTC_URL` | `http://127.0.0.1:1984` | |
| `STREAM` | `doorbell_talk` | go2rtc stream carrying the backchannel |
| `IDLE_TIMEOUT` | `90` | Seconds of inactivity before dropping |
| `PLAY_TIMEOUT` | `20` | Upstream request timeout |
| `CLIP_DIR` | `/clips` | Read-only mount, existence check only |
| `REMOTE_CLIP_DIR` | `/arnold-clips` | Path **as go2rtc sees it** |

`REMOTE_CLIP_DIR` is the path inside the *Frigate* container, because go2rtc
opens the file itself. The clips must be mounted into both containers. Serving
them to go2rtc over HTTP instead was tried and abandoned as unverifiable — a
bogus URL returns 200 exactly like a bogus path.

## Deploy

See [`docker-compose.example.yml`](docker-compose.example.yml). Then point Home
Assistant at it:

```yaml
rest_command:
  arnold_doorbell:
    method: POST
    url: "http://ARNOLD_SESSION_HOST:8098/play?clip={{ clip }}"
    timeout: 20
  arnold_warm:
    method: POST
    url: "http://ARNOLD_SESSION_HOST:8098/warm"
    timeout: 10
```

No dashboard changes are needed — buttons call `script.arnold_play`, which calls
the `rest_command`, so repointing that one URL redirects every button.

## Checking it

```bash
curl "http://ARNOLD_SESSION_HOST:8098/status"
curl "http://ARNOLD_SESSION_HOST:8098/warm"
curl "http://ARNOLD_SESSION_HOST:8098/play?clip=choppa"   # audible
docker logs arnold-session --tail 20
```
