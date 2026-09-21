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
