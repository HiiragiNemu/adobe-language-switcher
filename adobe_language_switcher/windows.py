"""Narrow OS boundary, injectable in tests. Never terminate target applications."""
import csv
import ctypes
import io
import os
from pathlib import Path
import re
import subprocess
from .resources import SwitchError


def state_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'AdobeLanguageSwitcher'


def user_identity():
    if os.name != 'nt':
        return f'uid:{os.getuid()}'
    text = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], creationflags=0x08000000).decode(errors='replace')
    match = re.search(r'S-1-[\d-]+', text)
    if not match:
        raise SwitchError('Could not read Windows user SID')
    return match[0]


def is_admin():
    return os.name == 'nt' and bool(ctypes.windll.shell32.IsUserAnAdmin())


def elevate(arguments):
    from ctypes import wintypes
    command = worker_command(arguments)
    params = subprocess.list2cmdline(command[1:])
    execute = ctypes.windll.shell32.ShellExecuteW
    execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    execute.restype = ctypes.c_void_p
    result = execute(None, 'runas', command[0], params, str(Path(__file__).resolve().parents[1]), 0) or 0
    if result <= 32:
        raise SwitchError(f'Administrator request was cancelled or failed ({result})')


def worker_command(arguments):
    """Works from a source ZIP and from an installed wheel."""
    import sys
    return [sys.executable, '-m', 'adobe_language_switcher', *arguments]


def file_version(path):
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    dll = ctypes.WinDLL('version', use_last_error=True)
    dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    dummy = wintypes.DWORD()
    size = dll.GetFileVersionInfoSizeW(str(path), ctypes.byref(dummy))
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    if not dll.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    dll.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    if not dll.VerQueryValueW(buf, '\\', ctypes.byref(ptr), ctypes.byref(length)) or length.value < 16:
        return None
    values = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD))
    if values[0] != 0xFEEF04BD:
        return None
    hi, lo = values[2], values[3]
    return f'{hi >> 16}.{hi & 65535}.{lo >> 16}.{lo & 65535}'


class Registry:
    def get(self, path, name):
        if os.name != 'nt':
            raise SwitchError('Windows registry is required')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                value, kind = winreg.QueryValueEx(key, name)
                if kind != winreg.REG_SZ:
                    raise SwitchError('Unexpected registry value type')
                return value
        except FileNotFoundError:
            return None

    def set(self, path, name, value):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def require_closed(exe_name):
    if os.name != 'nt':
        raise SwitchError('Applying changes requires Windows')
    result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {exe_name}', '/FO', 'CSV', '/NH'], capture_output=True, creationflags=0x08000000)
    if result.returncode:
        raise SwitchError('Process check failed; nothing changed')
    rows = csv.reader(io.StringIO(result.stdout.decode(errors='replace')))
    if any(row and row[0].casefold() == exe_name.casefold() for row in rows):
        raise SwitchError(f'请先保存并退出 {exe_name}，工具不会强制结束进程。')


def discover():
    roots = set()
    for env in ('ProgramFiles', 'ProgramFiles(x86)'):
        base = Path(os.environ.get(env, '')) / 'Adobe'
        if base.is_dir():
            roots.update(p for p in base.iterdir() if p.is_dir())
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key_name in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                                    display = winreg.QueryValueEx(sub, 'DisplayName')[0]
                                    if re.search('Premiere|After Effects|Media Encoder|Audition', display, re.I):
                                        location = winreg.QueryValueEx(sub, 'InstallLocation')[0]
                                        if location:
                                            roots.add(Path(location))
                            except OSError:
                                continue
                except OSError:
                    pass
    from .adapters import inspect_installation
    found = {}
    for root in sorted(roots):
        try:
            app = inspect_installation(root)
            found[str(app.root)] = app
        except (SwitchError, OSError):
            continue
    return list(found.values())
