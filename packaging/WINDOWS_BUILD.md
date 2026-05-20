# Building the Windows App

These steps create a Windows app for users who should not interact with Python,
IDEs, or source code.

## One-Time Setup

Install `uv` on the Windows computer by opening PowerShell and running:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell after installation.

## Build

From the repository folder, run:

```powershell
powershell -ExecutionPolicy ByPass -File .\packaging\build_windows.ps1
```

The build output is:

```text
dist\EmpkinS Radar Recorder\EmpkinS Radar Recorder.exe
dist\EmpkinS-Radar-Recorder-Windows.zip
```

Give the ZIP file to the recording computer or the operator. They can unzip it
and double-click `EmpkinS Radar Recorder.exe`.

## GitHub Build

The repository also contains a GitHub Actions workflow:

```text
.github/workflows/build-windows.yml
```

On pushes to `guiV3`, or when started manually from the GitHub Actions tab, it
builds the same portable ZIP on a Windows runner and uploads it as an artifact.

## Recording Location

The app stores new recordings in:

```text
Documents\EmpkinS Radar Recordings
```

Each recording has its own folder and `recording.sqlite` database.
