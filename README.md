# printer-agent

Lightweight local agent that monitors 3D prints through a camera, detects failures, and alerts
you wherever you are.

`printer-agent` is the local component of a 3D print monitoring system. It runs next to your
printer — on a Raspberry Pi, an old PC, a spare Android phone, or directly on printers with an
open embedded Linux — captures the print through any camera (USB webcam, IP/RTSP stream, or a
recorded video file), and talks to the printer over Moonraker or OctoPrint.

It records every job for later analysis, watches for failures such as spaghetti and bed
detachment, and can pause the print and notify you before an entire night of filament is wasted.
The agent opens an outbound connection to the server, so no port forwarding or router
configuration is required.

> **Status: pre-alpha.** The project is being built in the open and is not usable yet.

## Design notes

- **Runs beside the printer, not inside it.** No firmware modification and no root access is
  required on any printer. The agent speaks to the printer over its normal network API.
- **Outbound connections only.** Nothing is exposed to the internet on the user's network.
- **Observer mode first.** Until a detector has proven itself, the agent logs what it *would*
  have done and never touches a running print.
- **Portable by construction.** Plain command line Python, no GUI dependencies, so the same
  code runs on a Pi, a PC, a phone, or an embedded printer board.

## Recording

Recording is the first thing the agent does, and it comes before any detection:
print failures are rare, and a failure nobody recorded is training data lost for good.

```bash
# a USB webcam, one frame every 10 seconds
uv run printer-agent record --source webcam --name suporte-monitor

# a network camera, or a phone running an IP-camera app
uv run printer-agent record --source network --url rtsp://192.168.0.50:554/stream

# a recorded video file — replays instantly, no waiting
uv run printer-agent record --source file --path samples/failed-print.avi
```

Stop with `Ctrl+C`; the job metadata is written either way. Each run produces:

```
dados/
  2026-09-21_143022_suporte-monitor/
    frames/
      000001.jpg
      000002.jpg
    job.json
```

`job.json` records the source, the capture interval, start and end times, the frame count and
the outcome. `result` stays `unknown` until a print result is known — the printer reports it
once Moonraker integration lands.

Useful flags: `--interval`, `--quality`, `--output`, `--max-frames`, `--max-duration`.

## Following the printer

`watch` removes the need to remember anything: the printer starts and stops the recording, and
reports how each print ended, so recordings arrive already labelled.

```bash
# is the printer reachable?
uv run printer-agent status --printer-url http://192.168.0.42:7125

# follow it and record every print
uv run printer-agent watch --printer-url http://192.168.0.42:7125
```

`job.json` then also carries:

```json
{
  "result": "success",
  "notes": { "printer_outcome": "complete" },
  "gcode": { "estimated_time": 7200, "layer_count": 180, "filament_total": 4210.5 }
}
```

A print the printer reports as `complete` is labelled `success` and one that ended in `error`
is labelled `failure`. **`cancelled` stays `unknown` on purpose**: someone pressing cancel may
have spotted a failure or may simply have changed their mind, and guessing would poison the
dataset every later model is trained on. The raw printer outcome is kept in `notes` so those
jobs can be labelled by hand.

The websocket reconnects on its own with backoff — an agent watching an overnight print cannot
end its session because the network blinked.

### Observer mode

```yaml
mode: observer   # observer | active
```

`observer` is the default and the agent refuses every command that would change a running
print; it records what it *would* have done. Move to `active` only once a detector has earned
it. A false positive cancelling a 20 hour print costs more than a missed detection.


## Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) for dependency management

## Development

```bash
git clone https://github.com/arnaldoliro/printer-agent.git
cd printer-agent

uv sync                  # create the virtualenv and install dependencies
cp config.example.yaml config.yaml

uv run printer-agent --help
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```

`config.yaml` is gitignored: it holds local addresses and tokens and must never be committed.

## License

[AGPL-3.0-only](LICENSE)
