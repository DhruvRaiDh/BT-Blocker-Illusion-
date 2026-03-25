# BT Blocker - Illusion Mode

A sophisticated Bluetooth blocking application for Windows that prevents device connections while keeping Bluetooth fully functional and discoverable.

## Features

- **Illusion Mode**: Blocks connections without touching drivers
- **Three-Layer Defense**:
  - RFCOMM Socket Trap (accepts then drops connections)
  - Windows Bluetooth API (protocol-level disconnect)
  - Registry layer (DisableSCO/ACL)
- **Whitelist Support**: Allow specific devices to connect
- **Real-time Dashboard**: Monitor connections and manage settings
- **System Tray Integration**: Runs in background with persistent state

## How It Works

1. **Socket Trap Layer**: Opens listeners on RFCOMM channels - when a device connects, we accept then immediately close (device sees "connection failed")

2. **Bluetooth API Layer**: Disconnects devices via `BluetoothSetServiceState` - no driver modifications, appears as protocol error

3. **Registry Layer**: Disables SCO/ACL at controller level for extra protection

## Installation

### Option 1: Pre-built EXE
No release artifact is published yet. Build locally (see Option 2) or copy the locally built `dist/BT_Blocker.exe` if someone shares it with you. Running from the repo alone will not fetch an EXE.

### Option 2: Install from Source
```powershell
pip install pystray pillow pywin32
python bt_blocker.py
```

## Requirements

- Windows 10/11
- Administrator privileges
- Python 3.8+ (if running from source)
- Bluetooth adapter

## Building EXE

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --uac-admin --name "BT_Blocker" --manifest admin.manifest --hidden-import=pystray._win32 --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageDraw --collect-all pystray bt_blocker.py
```

## Current status / limitations

- The app currently blocks **all** devices when blocking is ON. Whitelist checks are applied only in the BT API and PnP layers, but the global RFCOMM socket trap and registry DisableSCO/ACL layers still disrupt whitelisted devices. Result: allow-listing is not reliable yet.
- The PnP “soft disconnect” step momentarily disables and re-enables the Bluetooth device node. It is not a permanent driver disable, but you will see a brief disable/enable cycle when blocking is active.
- No published binary download; you must build locally via PyInstaller.

## Usage

1. Run `BT_Blocker.exe` (as Admin)
2. **Dashboard tabs**:
   - **Live Connections**: See currently connected devices
   - **Whitelist**: Add/remove devices to always allow
   - **Activity Log**: Monitor blocking activity

3. **Controls**:
   - Toggle blocking ON/OFF
   - Whitelist devices
   - Manually drop connections
   - View real-time logs

## Configuration

Settings are saved to `~/.bt_blocker_v2.json`:
```json
{
  "blocking": false,
  "whitelist": ["Device Name", "AA:BB:CC:DD:EE:FF"],
  "logs": [...]
}
```

## How the Illusion Works

When you enable blocking:
1. Remote device initiates connection → our socket accepts it
2. We immediately close the socket → device sees connection failure
3. Registry layers prevent reconnection attempts
4. Device displays: "Couldn't connect" / "Pairing failed"
5. **To the device, it looks like natural interference, not a block**

## Notes

- **Drivers stay loaded**: The PnP soft cycle briefly disables/enables the BT device node; it does not uninstall drivers.
- **Bluetooth stays ON**: You remain discoverable.
- **Non-destructive**: Turning blocking OFF restores normal connectivity.
- **Whitelist caveat**: Because of global socket/registry layers, whitelisted devices may still be blocked in the current build.

## License

MIT

## Author

Dhruv Rai
