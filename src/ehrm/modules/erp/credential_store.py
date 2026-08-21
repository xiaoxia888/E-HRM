from __future__ import annotations

import ctypes
from ctypes import wintypes
import platform
import subprocess

from ehrm.core.exceptions import ConfigurationError


class _WindowsCredential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class SystemCredentialStore:
    """Stores one website's passwords in the operating system vault."""

    def __init__(self, service: str, display_name: str) -> None:
        self.service = service
        self.display_name = display_name

    def save_password(self, username: str, password: str) -> None:
        system = platform.system()
        if system == "Darwin":
            self._mac_save(username, password)
            return
        if system == "Windows":
            self._windows_save(username, password)
            return
        raise ConfigurationError(
            f"当前操作系统暂不支持安全保存{self.display_name}密码"
        )

    def load_password(self, username: str) -> str | None:
        if not username:
            return None
        system = platform.system()
        if system == "Darwin":
            command = [
                "security",
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                username,
                "-w",
            ]
            keychain = self._mac_default_keychain()
            if keychain:
                command.append(keychain)
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.rstrip("\n") if result.returncode == 0 else None
        if system == "Windows":
            return self._windows_load(username)
        return None

    def delete_password(self, username: str) -> None:
        if not username:
            return
        system = platform.system()
        if system == "Darwin":
            command = [
                "security",
                "delete-generic-password",
                "-s",
                self.service,
                "-a",
                username,
            ]
            keychain = self._mac_default_keychain()
            if keychain:
                command.append(keychain)
            subprocess.run(
                command,
                capture_output=True,
                check=False,
            )
        elif system == "Windows":
            advapi32 = ctypes.WinDLL("Advapi32.dll")
            advapi32.CredDeleteW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            advapi32.CredDeleteW.restype = wintypes.BOOL
            advapi32.CredDeleteW(self._windows_target(username), 1, 0)

    def _mac_save(self, username: str, password: str) -> None:
        command = [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            self.service,
            "-a",
            username,
            "-w",
            password,
        ]
        keychain = self._mac_default_keychain()
        if keychain:
            command.append(keychain)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ConfigurationError(
                f"无法将{self.display_name}密码保存到 macOS 钥匙串",
                details=result.stderr.strip() or None,
            )

    @staticmethod
    def _mac_default_keychain() -> str | None:
        result = subprocess.run(
            ["security", "default-keychain", "-d", "user"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip().strip('"')
        return value or None

    def _windows_target(self, username: str) -> str:
        return f"{self.service}:{username}"

    def _windows_save(self, username: str, password: str) -> None:
        blob = password.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(blob)
        credential = _WindowsCredential()
        credential.Type = 1
        credential.TargetName = self._windows_target(username)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_ubyte)
        )
        credential.Persist = 2
        credential.UserName = username
        advapi32 = ctypes.WinDLL("Advapi32.dll")
        advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(_WindowsCredential),
            wintypes.DWORD,
        ]
        advapi32.CredWriteW.restype = wintypes.BOOL
        if not advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ConfigurationError(
                f"无法将{self.display_name}密码保存到 Windows 凭据管理器"
            )

    def _windows_load(self, username: str) -> str | None:
        pointer = ctypes.POINTER(_WindowsCredential)()
        advapi32 = ctypes.WinDLL("Advapi32.dll")
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_WindowsCredential)),
        ]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        advapi32.CredFree.restype = None
        if not advapi32.CredReadW(
            self._windows_target(username), 1, 0, ctypes.byref(pointer)
        ):
            return None
        try:
            credential = pointer.contents
            raw = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return raw.decode("utf-16-le")
        finally:
            advapi32.CredFree(pointer)


class ErpCredentialStore(SystemCredentialStore):
    def __init__(self) -> None:
        super().__init__("NJNCC.EHRM.ERP", "ERP")


class RightsCredentialStore(SystemCredentialStore):
    def __init__(self) -> None:
        super().__init__("NJNCC.EHRM.JSHRSS", "江苏智慧人社")
