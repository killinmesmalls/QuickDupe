# Building Quick Dupe

Build your own exe so you have a unique binary signature.

## Requirements

- Python 3.10+
- PyInstaller

## Steps

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

- Run as Administrator (required for packet filtering)
- Install ViGEmBus driver on first run for controller emulation
