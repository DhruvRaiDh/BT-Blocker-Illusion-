import json
import subprocess


def run_cmd(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def get_pnp_bt_devices():
    ps = """
    Get-PnpDevice | Where-Object {
        ($_.Class -eq 'Bluetooth' -or $_.InstanceId -like 'BTHENUM*') -and
        $_.Status -eq 'OK'
    } | Select-Object FriendlyName, InstanceId | ConvertTo-Json -Compress
    """
    rc, out, _ = run_cmd([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=10)
    devices = []
    if rc == 0 and out.strip():
        try:
            data = json.loads(out.strip())
            if isinstance(data, dict):
                data = [data]
            for d in data:
                devices.append({
                    "name": d.get("FriendlyName") or "Unknown",
                    "device_id": d.get("InstanceId") or "",
                })
        except Exception:
            pass
    return devices


def pnp_soft_disconnect(device_id: str, log_fn=None) -> bool:
    ps = f"""
    $dev = Get-PnpDevice -InstanceId '{device_id}' -ErrorAction SilentlyContinue
    if ($dev) {{
        Disable-PnpDevice -InstanceId '{device_id}' -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
        Enable-PnpDevice  -InstanceId '{device_id}' -Confirm:$false -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }}
    """
    rc, _, err = run_cmd([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=15)
    if log_fn and err:
        log_fn(f"PnP error: {err}")
    return rc == 0
