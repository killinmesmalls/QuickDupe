# Quick Dupe

Duplication macros for item exploits.

## Features

- **Keydoor Method** - Key duplication using Xbox controller emulation
- **Throwable Dupe** - Throwable item duplication with auto-loop
- **Triggernade Dupe** - Triggernade duplication with inventory drop
- **E-Spam Collection** - Rapid E key spam for item pickup
- **Manual Disconnect** - Toggle packet drop (inbound/outbound)

## Requirements

- Windows 10/11
- Run as Administrator
- ViGEmBus driver (bundled, auto-installs on first run)

## Download

Get the latest release from [Releases](https://github.com/killinmesmalls/QuickDupe/releases).

Run `QuickDupe.exe` as Administrator. Install ViGEmBus when prompted.

## Build from Source

Build your own exe so you have a unique binary signature.

### Requirements

- Python 3.10+
- PyInstaller

### Steps

1. Install dependencies:
```
pip install -r requirements.txt
pip install pyinstaller
```

2. Place these files in the same directory:
   - `quickdupe.py`
   - `QuickDupe.spec`
   - `icon.ico`
   - `icon.png`
   - `ViGEmBus_1.22.0_x64_x86_arm64.exe`
   - `WinDivert.dll`
   - `WinDivert64.sys`

3. Build:
```
pyinstaller QuickDupe.spec
```

4. Your exe will be in the `dist` folder.

## Notes

- Press ESC to stop all macros
- Triggernade drop position can be recorded for your screen resolution
