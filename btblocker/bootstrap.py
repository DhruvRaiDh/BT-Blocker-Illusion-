import os
import sys


def init_tk_env():
    """Ensure Tcl/Tk paths are set for packaged and source runs."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
        os.environ.setdefault("TCL_LIBRARY", os.path.join(base_path, "tcl", "tcl8.6"))
        os.environ.setdefault("TK_LIBRARY", os.path.join(base_path, "tcl", "tk8.6"))
    else:
        tcl_dir = os.path.join(sys.base_prefix, "tcl", "tcl8.6")
        tk_dir = os.path.join(sys.base_prefix, "tcl", "tk8.6")
        if os.path.isdir(tcl_dir):
            os.environ.setdefault("TCL_LIBRARY", tcl_dir)
        if os.path.isdir(tk_dir):
            os.environ.setdefault("TK_LIBRARY", tk_dir)
