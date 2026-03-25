from btblocker.admin import is_admin, relaunch_as_admin
from btblocker.locking import acquire_lock
from btblocker.app import BTBlocker


if __name__ == "__main__":
    if not is_admin():
        relaunch_as_admin()
    lock = acquire_lock()
    if lock is None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "BT Blocker is already running.\nCheck the system tray.",
            "BT Blocker", 0x40)
        raise SystemExit(0)
    try:
        BTBlocker().run()
    finally:
        try:
            lock.close()
        except Exception:
            pass
