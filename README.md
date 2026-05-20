# radRec

IHF Radar Recorder Suite

## Central recorder UI

Install or update the Python environment with:

```bash
uv sync
```

The new nurse-facing entry point is:

```bash
uv run python central_ui.py
```

After `uv sync`, the app can also be started with:

```bash
uv run emrad-recorder
```

On startup it creates a new recording folder under `recordings/` and opens a
dedicated SQLite database for that recording. Use **Start Recording** and
**Stop Recording** for acquisition. Use **Open Existing Recording** to load a
previous `recording.sqlite` for later export without recording into it. Use
**New Recording** to switch back to a fresh database.

The export panel shows recorded time coverage; drag over the timeline to select
a range and export it to HDF5.
Missing FirmwareV2 packet sequence IDs are shown live in the UI and exported as
`-1` filled packet slots, with missing sequence IDs stored in the HDF5 metadata.

The legacy recorder and viewer are still available as `server.py` and
`empkins_gui.py`.
