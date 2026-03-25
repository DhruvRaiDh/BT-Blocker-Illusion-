try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


PATH = r"SYSTEM\CurrentControlSet\Services\BthServ"


def disable_bth_registry():
    if not winreg:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PATH, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "DisableSCO", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "DisableACL", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def enable_bth_registry():
    if not winreg:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PATH, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "DisableSCO", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, "DisableACL", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False
