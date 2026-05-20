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

On startup it creates a new recording folder under
`Documents/EmpkinS Radar Recordings` and opens a dedicated SQLite database for
that recording. Use **Start Recording** and **Stop Recording** for acquisition.
Use **Open Existing Recording** to load a previous `recording.sqlite` for later
export without recording into it. Use **New Recording** to switch back to a
fresh database.

The export panel shows recorded time coverage; drag over the timeline to select
a range and export it to HDF5.
Missing FirmwareV2 packet sequence IDs are shown live in the UI and exported as
`-1` filled packet slots, with missing sequence IDs stored in the HDF5 metadata.

The legacy recorder and viewer are still available as `server.py` and
`empkins_gui.py`.

## Windows App Build

For Windows users who should not work with Python or an IDE, use the portable
Windows app.

### Recommended: Download From GitHub Actions

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Open the latest successful **Build Windows App** run on the `guiV3` branch.
4. Download the artifact named `EmpkinS-Radar-Recorder-Windows`.
5. Unzip it on the Windows computer.
6. Double-click:

```text
EmpkinS Radar Recorder.exe
```

### If You Need To Build It On Windows

Open PowerShell on the Windows computer and install `uv` once:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell. From the repository folder, run:

```powershell
powershell -ExecutionPolicy ByPass -File .\packaging\build_windows.ps1
```

The script creates:

```text
dist\EmpkinS Radar Recorder\EmpkinS Radar Recorder.exe
dist\EmpkinS-Radar-Recorder-Windows.zip
```

The ZIP can be copied to another Windows computer, unzipped, and started by
double-clicking `EmpkinS Radar Recorder.exe`.

For more details, see:

[packaging/WINDOWS_BUILD.md](packaging/WINDOWS_BUILD.md)
