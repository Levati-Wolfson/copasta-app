"""Windows startup: add/remove app from 'Run at logon' (HKCU Run key)."""
import sys
import os

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Copasta"


def _get_launcher_cmd():
    """Command to run Copasta at logon.

    - Packaged build (PyInstaller bundle): run the .exe directly with --minimized.
    - Dev (running from source):           run pythonw.exe main.py --minimized.
    """
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return '"%s" --minimized' % exe

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return '"%s" "%s" --minimized' % (exe, script)


def get_start_with_windows():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except WindowsError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_start_with_windows(enable):
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_launcher_cmd())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except WindowsError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False
