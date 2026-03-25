# Custom tkinter pre-hook to avoid PyInstaller skipping tkinter when Tcl/Tk
# detection fails on the build machine.
def pre_find_module_path(hook_api):
    # Leave search_dirs untouched; the default hook empties this when
    # tcl/tk probing fails, which would exclude tkinter entirely.
    return
