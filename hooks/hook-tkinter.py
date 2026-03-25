import os
import sys

hiddenimports = ["tkinter"]

datas = []
tcl_dir = os.path.join(sys.base_prefix, "tcl", "tcl8.6")
tk_dir = os.path.join(sys.base_prefix, "tcl", "tk8.6")

if os.path.isdir(tcl_dir):
    datas.append((tcl_dir, "_tcl_data"))
if os.path.isdir(tk_dir):
    datas.append((tk_dir, "_tk_data"))
