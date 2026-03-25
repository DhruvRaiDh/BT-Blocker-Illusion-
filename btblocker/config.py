import json
import os

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".bt_blocker_v2.json")


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
