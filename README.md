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

For Windows users who should not work with Python or an IDE, build the portable
Windows app once and then run the generated `.exe`.

### After Cloning The Repository

Start here after the repository has been cloned to the Windows computer.

1. Open **PowerShell**.

2. Go into the cloned repository folder:

```powershell
cd C:\path\to\empkins-emrad
```

Replace `C:\path\to\empkins-emrad` with the actual folder where the repository
was cloned.

3. Make sure you are on the `guiV3` branch:

```powershell
git switch guiV3
git pull
```

4. Install `uv` once:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

5. Close PowerShell and open it again.

6. Go back into the cloned repository folder:

```powershell
cd C:\path\to\empkins-emrad
```

7. Build the Windows app:

```powershell
powershell -ExecutionPolicy ByPass -File .\packaging\build_windows.ps1
```

8. Open the generated app folder:

```text
dist\EmpkinS Radar Recorder
```

9. Start the app by double-clicking:

```text
EmpkinS Radar Recorder.exe
```

The build script also creates a ZIP file that can be copied to another Windows
computer:

```text
dist\EmpkinS-Radar-Recorder-Windows.zip
```

### Alternative: Download From GitHub Actions

If a Windows build has already been created on GitHub:

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Open the latest successful **Build Windows App** run on the `guiV3` branch.
4. Download the artifact named `EmpkinS-Radar-Recorder-Windows`.
5. Unzip it on the Windows computer.
6. Double-click `EmpkinS Radar Recorder.exe`.

For more details, see:

[packaging/WINDOWS_BUILD.md](packaging/WINDOWS_BUILD.md)
