import os
import sys

hiddenimports = ["tkinter"]

_datas = []
tcl_dir = os.path.join(sys.base_prefix, "tcl", "tcl8.6")
tk_dir = os.path.join(sys.base_prefix, "tcl", "tk8.6")

if os.path.isdir(tcl_dir):
    _datas.append((tcl_dir, "tcl/tcl8.6"))
if os.path.isdir(tk_dir):
    _datas.append((tk_dir, "tcl/tk8.6"))

datas = _datas
