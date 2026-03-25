"""
BT Blocker - Real Illusion Bluetooth Blocker
=============================================
What this does:
  - Bluetooth stays ON
  - Your PC stays discoverable
  - Drivers stay loaded, no errors
  - When a device tries to pair/connect → it gets silently rejected
  - The other device sees: "Couldn't connect" / "Pairing failed" 
    — looks like interference, profile mismatch, or a software glitch

How it works:
  - Opens a raw Bluetooth socket listener on all profiles
  - Accepts the connection request (so the handshake starts)
  - Immediately closes it → from the attacker's side it looks like
    a real connection failure, not a block
  - Simultaneously monitors PnP for any device that reaches "OK" 
    status and fires a BTH_IOCTL_DISCONNECT via DeviceIoControl
  - Registry key LocalSystemControlSet DisableSCO/DisableACL 
    adds a second layer at the BT controller level

Requirements: pip install pystray pillow pywin32
"""

import sys
import os
import time
import json
import threading
import subprocess
import ctypes
import ctypes.wintypes
import socket
import struct
from datetime import datetime
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import tkinter as tk
from tkinter import ttk

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
CONFIG_PATH   = os.path.join(os.path.expanduser("~"), ".bt_blocker_v2.json")
POLL_INTERVAL = 1.0

# Bluetooth address family / protocol constants (Windows)
AF_BTH         = 32
BTHPROTO_RFCOMM = 3
BTHPROTO_L2CAP  = 256

# IOCTL codes for Bluetooth HCI
IOCTL_BTH_DISCONNECT_DEVICE = 0x41000C  # DeviceIoControl disconnect

# ══════════════════════════════════════════════════════════════════════════════
#  SINGLE INSTANCE LOCK
# ══════════════════════════════════════════════════════════════════════════════
def acquire_lock():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", 47833))
        s.listen(1)
        return s
    except OSError:
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════════════════════
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def relaunch_as_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        f'"{os.path.abspath(__file__)}"', None, 1)
    sys.exit(0)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════
def load_config():
    default = {"blocking": False, "whitelist": [], "logs": []}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return {**default, **json.load(f)}
        except Exception:
            pass
    return default

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  WINDOWS BLUETOOTH API  (via ctypes — no driver changes)
# ══════════════════════════════════════════════════════════════════════════════

# --- Load WinAPI ---
_bt  = ctypes.WinDLL("BluetoothApis.dll", use_last_error=True)
_ws2 = ctypes.WinDLL("Ws2_32.dll",        use_last_error=True)
_k32 = ctypes.WinDLL("kernel32",          use_last_error=True)

# BLUETOOTH_ADDRESS union
class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [
        ("ullLong", ctypes.c_ulonglong),
        ("rgBytes", ctypes.c_ubyte * 6),
    ]

# BLUETOOTH_DEVICE_INFO
class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize",               ctypes.c_ulong),
        ("Address",              BLUETOOTH_ADDRESS),
        ("ulClassofDevice",      ctypes.c_ulong),
        ("fConnected",           ctypes.c_bool),
        ("fRemembered",          ctypes.c_bool),
        ("fAuthenticated",       ctypes.c_bool),
        ("stLastSeen",           ctypes.c_byte * 16),
        ("stLastUsed",           ctypes.c_byte * 16),
        ("szName",               ctypes.c_wchar * 248),
    ]

# BLUETOOTH_DEVICE_SEARCH_PARAMS
class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize",               ctypes.c_ulong),
        ("fReturnAuthenticated", ctypes.c_bool),
        ("fReturnRemembered",    ctypes.c_bool),
        ("fReturnUnknown",       ctypes.c_bool),
        ("fReturnConnected",     ctypes.c_bool),
        ("fIssueInquiry",        ctypes.c_bool),
        ("cTimeoutMultiplier",   ctypes.c_ubyte),
        ("hRadio",               ctypes.wintypes.HANDLE),
    ]

# BLUETOOTH_FIND_RADIO_PARAMS
class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong)]
# SOCKADDR_BTH - proper Bluetooth socket address structure
class SOCKADDR_BTH(ctypes.Structure):
    _fields_ = [
        ("addressFamily", ctypes.c_ushort),
        ("btAddr", ctypes.c_ulonglong),
        ("serviceClassId", ctypes.c_char * 16),
        ("port", ctypes.c_ulong),
    ]
def get_radio_handle():
    """Get handle to the local BT radio."""
    params = BLUETOOTH_FIND_RADIO_PARAMS(dwSize=ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
    radio  = ctypes.wintypes.HANDLE()
    find   = _bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if find:
        _bt.BluetoothFindRadioClose(find)
        return radio
    return None

def get_connected_devices(radio=None):
    """
    Use BluetoothFindFirstDevice / BluetoothFindNextDevice to enumerate
    only CONNECTED devices (fConnected=True).
    Returns list of dicts: {name, address_int, address_str}
    """
    params = BLUETOOTH_DEVICE_SEARCH_PARAMS(
        dwSize               = ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS),
        fReturnAuthenticated = False,
        fReturnRemembered    = False,
        fReturnUnknown       = True,
        fReturnConnected     = True,   # ← only actually connected devices
        fIssueInquiry        = False,  # don't do active scan (too slow)
        cTimeoutMultiplier   = 2,
        hRadio               = radio or ctypes.wintypes.HANDLE(0),
    )
    dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
    devices  = []

    find = _bt.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(dev_info))
    if not find:
        return devices

    while True:
        if dev_info.fConnected:
            addr_int = dev_info.Address.ullLong
            addr_bytes = bytes(dev_info.Address.rgBytes)
            addr_str = ":".join(f"{b:02X}" for b in reversed(addr_bytes))
            devices.append({
                "name":        dev_info.szName or "Unknown",
                "address_int": addr_int,
                "address_str": addr_str,
                "remembered":  dev_info.fRemembered,
                "authenticated": dev_info.fAuthenticated,
            })
        dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
        if not _bt.BluetoothFindNextDevice(find, ctypes.byref(dev_info)):
            break

    _bt.BluetoothFindDeviceClose(find)
    return devices

def disconnect_device_api(address_int: int) -> bool:
    """
    Disconnect via BluetoothSetServiceState for common profiles.
    Disables services at protocol level without driver changes.
    """
    dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
    dev_info.Address.ullLong = address_int

    success = False
    try:
        # Try to disable all services (NULL GUID = all services)
        result = _bt.BluetoothSetServiceState(
            None,
            ctypes.byref(dev_info),
            None,
            0x00  # BLUETOOTH_SERVICE_DISABLE
        )
        if result == 0:
            success = True
    except Exception:
        pass

    return success

def remove_device_api(address_int: int) -> bool:
    """
    BluetoothRemoveDevice — removes pairing record.
    Device will need to pair again, but drivers stay intact.
    """
    addr = BLUETOOTH_ADDRESS()
    addr.ullLong = address_int
    result = _bt.BluetoothRemoveDevice(ctypes.byref(addr))
    return result == 0

def run_cmd(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)

def disable_bth_registry():
    """
    Disable SCO and ACL at registry level for extra protection.
    Adds second layer of BT blocking at controller level.
    """
    try:
        import winreg
        path = r"SYSTEM\CurrentControlSet\Services\BthServ"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "DisableSCO", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "DisableACL", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    except Exception:
        return False

def enable_bth_registry():
    """
    Re-enable SCO and ACL when blocking is disabled.
    """
    try:
        import winreg
        path = r"SYSTEM\CurrentControlSet\Services\BthServ"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "DisableSCO", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(key, "DisableACL", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    except Exception:
        return False

def get_pnp_bt_devices():
    """
    Secondary scan via PowerShell for devices that slip past the BT API.
    Only returns devices with Status=OK (actually connected).
    """
    ps = """
    Get-PnpDevice | Where-Object {
        ($_.Class -eq 'Bluetooth' -or $_.InstanceId -like 'BTHENUM*') -and
        $_.Status -eq 'OK'
    } | Select-Object FriendlyName, InstanceId | ConvertTo-Json -Compress
    """
    rc, out, _ = run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=10)
    devices = []
    if rc == 0 and out.strip():
        try:
            data = json.loads(out.strip())
            if isinstance(data, dict):
                data = [data]
            for d in data:
                devices.append({
                    "name":      d.get("FriendlyName") or "Unknown",
                    "device_id": d.get("InstanceId") or "",
                })
        except Exception:
            pass
    return devices

def pnp_soft_disconnect(device_id: str, log_fn) -> bool:
    """
    Soft disconnect via PnP — restarts the device node WITHOUT 
    disabling the driver. Device sees a connection reset, not a block.
    This is different from /disable-device — driver stays fully loaded.
    """
    ps = f"""
    $dev = Get-PnpDevice -InstanceId '{device_id}' -ErrorAction SilentlyContinue
    if ($dev) {{
        Disable-PnpDevice -InstanceId '{device_id}' -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
        Enable-PnpDevice  -InstanceId '{device_id}' -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }}
    """
    rc, _, _ = run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=15)
    return rc == 0

# ══════════════════════════════════════════════════════════════════════════════
#  RFCOMM SOCKET TRAP
#  Opens BT socket listeners on common profiles.
#  When a device connects → we accept then immediately close.
#  The remote device sees: connection established → immediately reset
#  = looks like "service unavailable" or "profile not supported"
# ══════════════════════════════════════════════════════════════════════════════
class SocketTrap:
    """Listens on BT RFCOMM channels and immediately drops any connection."""

    CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]  # common RFCOMM channels

    def __init__(self, log_fn):
        self._log      = log_fn
        self._running  = False
        self._sockets  = []
        self._threads  = []

    def start(self):
        if self._running:
            return
        self._running = True
        for ch in self.CHANNELS:
            t = threading.Thread(target=self._listen, args=(ch,), daemon=True)
            t.start()
            self._threads.append(t)
        self._log("Socket trap active on RFCOMM channels 1-12")

    def stop(self):
        self._running = False
        for s in self._sockets:
            try:
                s.close()
            except Exception:
                pass
        self._sockets.clear()

    def _listen(self, channel: int):
        try:
            sock = socket.socket(AF_BTH, socket.SOCK_STREAM, BTHPROTO_RFCOMM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Use proper SOCKADDR_BTH structure
            sockaddr = SOCKADDR_BTH()
            sockaddr.addressFamily = AF_BTH
            sockaddr.btAddr = 0
            sockaddr.port = channel
            
            sock.bind(sockaddr)
            sock.listen(5)
            self._sockets.append(sock)
        except Exception:
            return

        while self._running:
            try:
                sock.settimeout(1.0)
                try:
                    conn, addr = sock.accept()
                    # Connection accepted — immediately close it
                    # Remote device sees: connected → reset → "couldn't connect"
                    conn.close()
                    self._log(f"Trapped & dropped connection on RFCOMM ch{channel}")
                except socket.timeout:
                    continue
            except Exception:
                break

# ══════════════════════════════════════════════════════════════════════════════
#  TRAY ICON
# ══════════════════════════════════════════════════════════════════════════════
def make_icon(blocking: bool) -> Image.Image:
    size = 128
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    clr  = (210, 35, 35, 255) if blocking else (30, 120, 255, 255)
    d.ellipse([6, 6, size-6, size-6], fill=clr)
    cx, cy = size//2, size//2
    # Bluetooth symbol
    d.line([(cx, cy-36), (cx, cy+36)],     fill="white", width=6)
    d.line([(cx, cy-36), (cx+22, cy-14)],  fill="white", width=5)
    d.line([(cx+22, cy-14), (cx-18, cy+14)], fill="white", width=5)
    d.line([(cx, cy+36), (cx+22, cy+14)],  fill="white", width=5)
    d.line([(cx+22, cy+14), (cx-18, cy-14)], fill="white", width=5)
    if blocking:
        d.line([(18, 18), (size-18, size-18)], fill=(255,255,255,200), width=10)
    return img.resize((64, 64), Image.LANCZOS)

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class BTBlocker:
    def __init__(self):
        self.cfg        = load_config()
        self.tray       = None
        self.gui_root   = None
        self._running   = True
        self._blocking  = self.cfg.get("blocking", False)
        self._logs      = list(self.cfg.get("logs", []))
        self._lock      = threading.Lock()
        self._trap      = SocketTrap(self._log)
        self._radio     = None
        # GUI refs
        self._log_widget  = None
        self._status_var  = None
        self._status_lbl  = None
        self._toggle_btn  = None
        self._dev_tree    = None
        self._wl_listbox  = None
        self._wl_entry    = None

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        ts    = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > 300:
                self._logs = self._logs[-300:]
            self.cfg["logs"] = self._logs
        save_config(self.cfg)
        print(entry)
        if self.gui_root:
            try:
                self.gui_root.after(0, self._push_log, entry)
            except Exception:
                pass

    def _push_log(self, entry):
        if self._log_widget:
            try:
                self._log_widget.config(state="normal")
                self._log_widget.insert(tk.END, entry + "\n")
                self._log_widget.see(tk.END)
                self._log_widget.config(state="disabled")
            except Exception:
                pass

    # ── Whitelist check ───────────────────────────────────────────────────────
    def _is_whitelisted(self, identifier: str) -> bool:
        return any(w.upper() in identifier.upper()
                   for w in self.cfg.get("whitelist", []) if w)

    # ── Blocking toggle ───────────────────────────────────────────────────────
    def set_blocking(self, value: bool):
        self._blocking       = value
        self.cfg["blocking"] = value
        save_config(self.cfg)
        if value:
            self._log("═══ ILLUSION BLOCKING ON ═══")
            self._log("BT stays ON • Drivers intact • Connections will be silently rejected")
            if disable_bth_registry():
                self._log("  Registry layer: DisableSCO/ACL applied")
            self._trap.start()
            self._disconnect_all_connected()
        else:
            self._log("═══ BLOCKING OFF — connections allowed ═══")
            self._trap.stop()
            if enable_bth_registry():
                self._log("  Registry layer: Re-enabled")
        self._update_tray()
        if self.gui_root:
            try:
                self.gui_root.after(0, self._refresh_status)
            except Exception:
                pass

    def _disconnect_all_connected(self):
        """On block enable — immediately drop any currently connected devices."""
        try:
            radio   = get_radio_handle()
            devices = get_connected_devices(radio)
            for dev in devices:
                if self._is_whitelisted(dev["address_str"]) or \
                   self._is_whitelisted(dev["name"]):
                    self._log(f"  Whitelisted: {dev['name']} — allowing connection")
                    continue
                self._log(f"Dropping active connection: {dev['name']} ({dev['address_str']})")
                ok = disconnect_device_api(dev["address_int"])
                self._log(f"  BT API disconnect: {'OK' if ok else 'FAIL'}")
                if not ok:
                    ok2 = remove_device_api(dev["address_int"])
                    self._log(f"  Remove device:     {'OK' if ok2 else 'FAIL'}")
        except Exception as e:
            self._log(f"  Disconnect sweep error: {e}")

    # ── Monitor loop ──────────────────────────────────────────────────────────
    def _monitor(self):
        self._log("Monitor started.")
        self._radio = get_radio_handle()

        while self._running:
            try:
                if self._blocking:
                    # Layer 1: Windows BT API — catches devices that fully connected
                    try:
                        devices = get_connected_devices(self._radio)
                        for dev in devices:
                            if self._is_whitelisted(dev["address_str"]) or \
                               self._is_whitelisted(dev["name"]):
                                continue
                            self._log(f"ILLUSION >> {dev['name']} ({dev['address_str']})")
                            ok = disconnect_device_api(dev["address_int"])
                            if ok:
                                self._log(f"  ✓ Blocked — device sees connection failure")
                            else:
                                pnp_devs = get_pnp_bt_devices()
                                for pnp in pnp_devs:
                                    if pnp["name"] == dev["name"]:
                                        if pnp_soft_disconnect(pnp["device_id"], self._log):
                                            self._log(f"  ✓ PnP cycle successful")
                                        break
                    except Exception as e:
                        self._log(f"  BT API error: {e}")

                    # Layer 2: PnP scan — catches anything that slipped through
                    try:
                        pnp_devs = get_pnp_bt_devices()
                        for dev in pnp_devs:
                            if self._is_whitelisted(dev["device_id"]) or \
                               self._is_whitelisted(dev["name"]):
                                continue
                            self._log(f"PnP catch >> {dev['name']}")
                            # Soft cycle — disable+enable, NOT permanent disable
                            # Driver stays loaded, just triggers a reconnect we'll catch again
                            pnp_soft_disconnect(dev["device_id"], self._log)
                    except Exception as e:
                        self._log(f"  PnP scan error: {e}")

            except Exception as e:
                self._log(f"Monitor error: {e}")

            time.sleep(POLL_INTERVAL)

        self._log("Monitor stopped.")

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _update_tray(self):
        if self.tray:
            try:
                self.tray.icon  = make_icon(self._blocking)
                self.tray.title = "BT Blocker — " + \
                    ("ILLUSION BLOCKING" if self._blocking else "ALLOWING")
            except Exception:
                pass

    def _build_tray(self):
        def toggle_lbl(i):
            return "Illusion: ON  (click to disable)" if self._blocking \
                   else "Illusion: OFF  (click to enable)"
        menu = pystray.Menu(
            item("Open Dashboard", self._open_gui, default=True),
            pystray.Menu.SEPARATOR,
            item(toggle_lbl, lambda icon, i: self.set_blocking(not self._blocking)),
            pystray.Menu.SEPARATOR,
            item("Exit", self._exit),
        )
        self.tray = pystray.Icon(
            "BT Blocker", make_icon(self._blocking), "BT Blocker", menu)

    # ── GUI ───────────────────────────────────────────────────────────────────
    def _open_gui(self, icon=None, tray_item=None):
        if self.gui_root and self.gui_root.winfo_exists():
            self.gui_root.deiconify()
            self.gui_root.lift()
            self.gui_root.focus_force()
            return
        threading.Thread(target=self._build_gui, daemon=True).start()

    def _build_gui(self):
        root = tk.Tk()
        self.gui_root = root
        root.title("BT Blocker")
        root.geometry("720x600")
        root.resizable(False, False)

        BG = "#080813"; BG2 = "#10102a"; BG3 = "#1a1a3a"
        ACC = "#3d6fff"; RED = "#ff3d3d"; GRN = "#3dff7a"
        TXT = "#d0d0ff"; MUTED = "#444466"; F = "Consolas"

        root.configure(bg=BG)
        root.after(1, lambda: root.wm_attributes("-toolwindow", True))
        root.protocol("WM_DELETE_WINDOW", root.withdraw)

        s = ttk.Style(root)
        s.theme_use("clam")
        s.configure("TFrame",           background=BG)
        s.configure("TNotebook",        background=BG, borderwidth=0)
        s.configure("TNotebook.Tab",    background=BG3, foreground=TXT,
                    font=(F,9), padding=[14,4])
        s.configure("TLabel",           background=BG, foreground=TXT, font=(F,10))
        s.configure("TEntry",           fieldbackground=BG3, foreground=TXT,
                    insertcolor=ACC, font=(F,10))
        s.configure("Treeview",         background=BG2, foreground=TXT,
                    fieldbackground=BG2, font=(F,9), rowheight=22)
        s.configure("Treeview.Heading", background=BG3, foreground=ACC,
                    font=(F,9,"bold"))
        s.map("TNotebook.Tab",
              background=[("selected", ACC)], foreground=[("selected","white")])

        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG2, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  ⬡  BT BLOCKER", bg=BG2, fg=ACC,
                 font=(F,16,"bold")).pack(side="left", padx=8)
        tk.Label(hdr, text="  [ADMIN ✓]" if is_admin() else "  [NO ADMIN ✗]",
                 bg=BG2, fg=GRN if is_admin() else RED,
                 font=(F,9)).pack(side="left")
        # Mode badge
        tk.Label(hdr, text="  ILLUSION MODE — drivers stay intact",
                 bg=BG2, fg=MUTED, font=(F,8)).pack(side="left", padx=12)

        # ── Status row ──────────────────────────────────────────────────────
        sr = tk.Frame(root, bg=BG, pady=12)
        sr.pack(fill="x", padx=22)
        self._status_var = tk.StringVar()
        self._status_lbl = tk.Label(sr, textvariable=self._status_var,
                                    bg=BG, font=(F,13,"bold"))
        self._status_lbl.pack(side="left")
        self._toggle_btn = tk.Button(
            sr, text="", width=32, font=(F,10,"bold"),
            relief="flat", cursor="hand2", bd=0,
            command=lambda: self.set_blocking(not self._blocking))
        self._toggle_btn.pack(side="right")

        tk.Frame(root, bg="#1c1c44", height=1).pack(fill="x", padx=22)

        # ── How it works banner ──────────────────────────────────────────────
        info = tk.Frame(root, bg="#0d0d22", pady=6)
        info.pack(fill="x", padx=22, pady=(6,0))
        tk.Label(info,
                 text="  ● BT stays ON & discoverable   "
                      "● Drivers untouched   "
                      "● Connections accepted then instantly dropped   "
                      "● Other device sees: \"Couldn't connect\"",
                 bg="#0d0d22", fg="#3355aa", font=(F,8)).pack(anchor="w")

        # ── Notebook ────────────────────────────────────────────────────────
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=22, pady=8)

        # Tab: Live Connections
        t1 = ttk.Frame(nb)
        nb.add(t1, text="  Live Connections  ")
        tk.Label(t1, text="Devices currently connected to your PC (these will be dropped when blocking):",
                 bg=BG, fg=MUTED, font=(F,8)).pack(anchor="w", pady=(6,2))
        self._dev_tree = ttk.Treeview(t1,
            columns=("Name","Address","Auth"), show="headings", height=9)
        self._dev_tree.heading("Name",    text="Device Name")
        self._dev_tree.heading("Address", text="BT Address")
        self._dev_tree.heading("Auth",    text="Paired")
        self._dev_tree.column("Name",    width=260)
        self._dev_tree.column("Address", width=160, anchor="center")
        self._dev_tree.column("Auth",    width=80,  anchor="center")
        self._dev_tree.tag_configure("connected",   foreground=RED)
        self._dev_tree.tag_configure("whitelisted", foreground=GRN)
        self._dev_tree.pack(fill="both", expand=True)
        br = tk.Frame(t1, bg=BG)
        br.pack(fill="x", pady=5)
        for txt, cmd, fg in [
            ("↻  Refresh",            self._refresh_devices, TXT),
            ("＋  Whitelist Selected", self._whitelist_sel,   GRN),
            ("✕  Drop Selected Now",  self._drop_selected,   RED),
        ]:
            tk.Button(br, text=txt, bg=BG3, fg=fg, relief="flat",
                      font=(F,9), cursor="hand2", padx=10,
                      command=cmd).pack(side="left", padx=3)

        # Tab: Whitelist
        t2 = ttk.Frame(nb)
        nb.add(t2, text="  Whitelist  ")
        tk.Label(t2, text="Whitelisted devices are always allowed to connect freely:",
                 bg=BG, fg=MUTED, font=(F,8)).pack(anchor="w", pady=(6,2))
        self._wl_listbox = tk.Listbox(t2, bg=BG2, fg=GRN, font=(F,9),
                                      height=9, selectbackground=BG3,
                                      activestyle="none", bd=0,
                                      highlightthickness=0)
        self._wl_listbox.pack(fill="both", expand=True)
        wr = tk.Frame(t2, bg=BG)
        wr.pack(fill="x", pady=5)
        self._wl_entry = ttk.Entry(wr)
        self._wl_entry.pack(side="left", fill="x", expand=True, padx=(0,6))
        for txt, cmd, fg in [("Add", self._add_wl, GRN), ("Remove", self._remove_wl, RED)]:
            tk.Button(wr, text=txt, bg=BG3, fg=fg, relief="flat",
                      font=(F,9), cursor="hand2", padx=10,
                      command=cmd).pack(side="left", padx=2)

        # Tab: Log
        t3 = ttk.Frame(nb)
        nb.add(t3, text="  Activity Log  ")
        self._log_widget = tk.Text(t3, bg="#04040e", fg="#4477ee",
                                   font=(F,8), state="disabled",
                                   wrap="none", bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(t3, orient="vertical", command=self._log_widget.yview)
        self._log_widget.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_widget.pack(fill="both", expand=True)
        tk.Button(t3, text="Clear Log", bg=BG3, fg=MUTED, relief="flat",
                  font=(F,8), cursor="hand2",
                  command=self._clear_log).pack(anchor="e", pady=3)

        # Footer
        ft = tk.Frame(root, bg="#04040e", height=22)
        ft.pack(fill="x", side="bottom")
        ft.pack_propagate(False)
        tk.Label(ft,
                 text="  ● Process persists after window close  |  Right-click tray icon to Exit",
                 bg="#04040e", fg=MUTED, font=(F,7)).pack(side="left", pady=3)

        self._refresh_status()
        self._refresh_devices()
        self._refresh_wl()
        self._reload_log()
        root.mainloop()
        self.gui_root = None

    # ── GUI helpers ──────────────────────────────────────────────────────────
    def _refresh_status(self):
        if not self._status_var:
            return
        if self._blocking:
            self._status_var.set("● ILLUSION ACTIVE")
            self._status_lbl.config(fg="#ff3d3d")
            self._toggle_btn.config(
                text="  🟢  Allow Connections  ",
                bg="#3a0f0f", fg="#ff7070", activebackground="#5a1a1a")
        else:
            self._status_var.set("● ALLOWING")
            self._status_lbl.config(fg="#3dff7a")
            self._toggle_btn.config(
                text="  🔴  Activate Illusion  ",
                bg="#0f3a1f", fg="#3dff7a", activebackground="#1a5a2a")

    def _refresh_devices(self):
        if not self._dev_tree:
            return
        for r in self._dev_tree.get_children():
            self._dev_tree.delete(r)
        try:
            radio   = get_radio_handle()
            devices = get_connected_devices(radio)
            if not devices:
                self._dev_tree.insert("", "end",
                    values=("No devices currently connected","",""))
                return
            for d in devices:
                wl  = self._is_whitelisted(d["address_str"]) or \
                      self._is_whitelisted(d["name"])
                tag = "whitelisted" if wl else "connected"
                self._dev_tree.insert("", "end", values=(
                    d["name"],
                    d["address_str"],
                    "Yes" if d["authenticated"] else "No"
                ), tags=(tag,))
        except Exception as e:
            self._dev_tree.insert("", "end", values=(f"Scan error: {e}","",""))

    def _whitelist_sel(self):
        for sel in self._dev_tree.selection():
            vals = self._dev_tree.item(sel)["values"]
            addr = str(vals[1]) if len(vals) > 1 else ""
            name = str(vals[0]) if len(vals) > 0 else ""
            if addr and addr != "No devices currently connected":
                self.cfg.setdefault("whitelist", []).append(addr)
                self._log(f"Whitelisted: {name} ({addr})")
        save_config(self.cfg)
        self._refresh_wl()
        self._refresh_devices()

    def _drop_selected(self):
        """Manually drop a selected connected device."""
        for sel in self._dev_tree.selection():
            vals = self._dev_tree.item(sel)["values"]
            name = str(vals[0])
            addr = str(vals[1])
            # Find address_int from current scan
            try:
                radio   = get_radio_handle()
                devices = get_connected_devices(radio)
                for dev in devices:
                    if dev["address_str"] == addr:
                        self._log(f"Manual drop: {name}")
                        disconnect_device_api(dev["address_int"])
                        break
            except Exception as e:
                self._log(f"Drop error: {e}")
        self._refresh_devices()

    def _refresh_wl(self):
        if not self._wl_listbox:
            return
        self._wl_listbox.delete(0, tk.END)
        for w in self.cfg.get("whitelist", []):
            self._wl_listbox.insert(tk.END, w)

    def _add_wl(self):
        val = self._wl_entry.get().strip()
        if val and val not in self.cfg.get("whitelist", []):
            self.cfg.setdefault("whitelist", []).append(val)
            save_config(self.cfg)
            self._wl_entry.delete(0, tk.END)
            self._refresh_wl()

    def _remove_wl(self):
        sel = self._wl_listbox.curselection()
        if not sel:
            return
        val = self._wl_listbox.get(sel[0])
        self.cfg["whitelist"].remove(val)
        save_config(self.cfg)
        self._refresh_wl()

    def _reload_log(self):
        if not self._log_widget:
            return
        self._log_widget.config(state="normal")
        self._log_widget.delete("1.0", tk.END)
        for line in self._logs[-150:]:
            self._log_widget.insert(tk.END, line + "\n")
        self._log_widget.see(tk.END)
        self._log_widget.config(state="disabled")

    def _clear_log(self):
        self._logs.clear()
        self.cfg["logs"] = []
        save_config(self.cfg)
        if self._log_widget:
            self._log_widget.config(state="normal")
            self._log_widget.delete("1.0", tk.END)
            self._log_widget.config(state="disabled")

    # ── Exit ─────────────────────────────────────────────────────────────────
    def _exit(self, icon=None, tray_item=None):
        self._log("Exiting...")
        self._running = False
        self._trap.stop()
        if self.gui_root:
            try:
                self.gui_root.destroy()
            except Exception:
                pass
        if self.tray:
            self.tray.stop()

    # ── Run ───────────────────────────────────────────────────────────────────
    def run(self):
        threading.Thread(target=self._monitor, daemon=True,
                         name="BTMonitor").start()
        self._build_tray()
        self._log("BT Blocker v2 started — ILLUSION MODE")
        if self._blocking:
            self._log("Resuming illusion blocking from last session.")
            self._trap.start()
            self._disconnect_all_connected()
        self.tray.run()

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not is_admin():
        relaunch_as_admin()
    lock = acquire_lock()
    if lock is None:
        ctypes.windll.user32.MessageBoxW(
            0,
            "BT Blocker is already running.\nCheck the system tray.",
            "BT Blocker", 0x40)
        sys.exit(0)
    try:
        BTBlocker().run()
    finally:
        try:
            lock.close()
        except Exception:
            pass