import ctypes
import ctypes.wintypes
import socket
import struct

AF_BTH = 32
BTHPROTO_RFCOMM = 3
BTHPROTO_L2CAP = 256
IOCTL_BTH_DISCONNECT_DEVICE = 0x41000C

_bt = ctypes.WinDLL("BluetoothApis.dll", use_last_error=True)
_ws2 = ctypes.WinDLL("Ws2_32.dll", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong),
                ("rgBytes", ctypes.c_ubyte * 6)]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("Address", BLUETOOTH_ADDRESS),
        ("ulClassofDevice", ctypes.c_ulong),
        ("fConnected", ctypes.c_bool),
        ("fRemembered", ctypes.c_bool),
        ("fAuthenticated", ctypes.c_bool),
        ("stLastSeen", ctypes.c_byte * 16),
        ("stLastUsed", ctypes.c_byte * 16),
        ("szName", ctypes.c_wchar * 248),
    ]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("fReturnAuthenticated", ctypes.c_bool),
        ("fReturnRemembered", ctypes.c_bool),
        ("fReturnUnknown", ctypes.c_bool),
        ("fReturnConnected", ctypes.c_bool),
        ("fIssueInquiry", ctypes.c_bool),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", ctypes.wintypes.HANDLE),
    ]


class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong)]


class SOCKADDR_BTH(ctypes.Structure):
    _fields_ = [
        ("addressFamily", ctypes.c_ushort),
        ("btAddr", ctypes.c_ulonglong),
        ("serviceClassId", ctypes.c_char * 16),
        ("port", ctypes.c_ulong),
    ]


def get_radio_handle():
    params = BLUETOOTH_FIND_RADIO_PARAMS(dwSize=ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
    radio = ctypes.wintypes.HANDLE()
    find = _bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if find:
        _bt.BluetoothFindRadioClose(find)
        return radio
    return None


def get_connected_devices(radio=None):
    params = BLUETOOTH_DEVICE_SEARCH_PARAMS(
        dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS),
        fReturnAuthenticated=False,
        fReturnRemembered=False,
        fReturnUnknown=True,
        fReturnConnected=True,
        fIssueInquiry=False,
        cTimeoutMultiplier=2,
        hRadio=radio or ctypes.wintypes.HANDLE(0),
    )
    dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
    devices = []
    find = _bt.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(dev_info))
    if not find:
        return devices
    while True:
        if dev_info.fConnected:
            addr_int = dev_info.Address.ullLong
            addr_bytes = bytes(dev_info.Address.rgBytes)
            addr_str = ":".join(f"{b:02X}" for b in reversed(addr_bytes))
            devices.append({
                "name": dev_info.szName or "Unknown",
                "address_int": addr_int,
                "address_str": addr_str,
                "remembered": dev_info.fRemembered,
                "authenticated": dev_info.fAuthenticated,
            })
        dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
        if not _bt.BluetoothFindNextDevice(find, ctypes.byref(dev_info)):
            break
    _bt.BluetoothFindDeviceClose(find)
    return devices


def disconnect_device_api(address_int: int) -> bool:
    dev_info = BLUETOOTH_DEVICE_INFO(dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_INFO))
    dev_info.Address.ullLong = address_int
    try:
        result = _bt.BluetoothSetServiceState(None, ctypes.byref(dev_info), None, 0x00)
        return result == 0
    except Exception:
        return False


def remove_device_api(address_int: int) -> bool:
    addr = BLUETOOTH_ADDRESS()
    addr.ullLong = address_int
    return _bt.BluetoothRemoveDevice(ctypes.byref(addr)) == 0
