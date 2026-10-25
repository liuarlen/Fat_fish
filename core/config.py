"""应用路径、设置持久化与 Windows DPAPI 凭据保护。"""

from __future__ import annotations

import base64
import copy
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sys
import tempfile
from typing import Any, Dict, Optional


APP_NAME = "YiPagePDF"
APP_DISPLAY_NAME = "肥鱼译文"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_root() -> str:
    """源码运行用项目目录；PyInstaller 打包后从 _MEIPASS / exe 同目录找资源。"""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, "resources"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "resources"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "_internal", "resources"))
    candidates.append(os.path.join(PROJECT_ROOT, "resources"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[-1]


RESOURCE_DIR = _resource_root()


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), APP_NAME)
        os.makedirs(fallback, exist_ok=True)
        return fallback


CONFIG_DIR = app_data_dir()
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
LIBRARY_PATH = os.path.join(CONFIG_DIR, "library.sqlite")
LOG_PATH = os.path.join(CONFIG_DIR, "app.log")


DEFAULTS: Dict[str, Any] = {
    "engine": "bilibili",
    "source_lang": "auto",
    "target_lang": "zh-CN",
    "use_library": True,
    "auto_save_memory": True,
    "fuzzy_threshold": 0.84,
    "font_scale": 1.0,
    "auto_shrink": True,
    "mode": "redact",
    "show_quality_marks": True,
    "providers": {
        "baidu": {"appid": "", "secret": ""},
        "youdao": {"app_key": "", "app_secret": ""},
        "tencent": {"secret_id": "", "secret_key": "", "region": "ap-guangzhou"},
        "aliyun": {
            "access_key_id": "",
            "access_key_secret": "",
            "region": "cn-hangzhou",
        },
        "llm": {
            "preset": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "",
            "temperature": 0.1,
        },
    },
    "library_dir": "",
    "recent_files": [],
    "last_dir": "",
}


SECRET_FIELDS = {
    "baidu": ("secret",),
    "youdao": ("app_secret",),
    "tencent": ("secret_key",),
    "aliyun": ("access_key_secret",),
    "llm": ("api_key",),
}

_SECRET_PREFIX = "dpapi:"
_FALLBACK_PREFIX = "b64:"


# --------------------------------------------------------------------------- #
# Windows DPAPI
# --------------------------------------------------------------------------- #
if os.name == "nt":
    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL


def _blob(data: bytes) -> "_DataBlob":
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    )


def _dpapi_protect(data: bytes) -> Optional[bytes]:
    if os.name != "nt":
        return None
    try:
        input_blob = _blob(data)
        output_blob = _DataBlob()
        if not _crypt32.CryptProtectData(
            ctypes.byref(input_blob), "YiPagePDF", None, None, None, 0,
            ctypes.byref(output_blob),
        ):
            return None
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            _kernel32.LocalFree(output_blob.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> Optional[bytes]:
    if os.name != "nt":
        return None
    try:
        input_blob = _blob(data)
        output_blob = _DataBlob()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0,
            ctypes.byref(output_blob),
        ):
            return None
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            _kernel32.LocalFree(output_blob.pbData)
    except Exception:
        return None


def protect_secret(value: str) -> str:
    """把 API 密钥变成只能由当前 Windows 用户解开的字符串。"""
    if not value:
        return ""
    raw = value.encode("utf-8")
    protected = _dpapi_protect(raw)
    if protected:
        return _SECRET_PREFIX + base64.b64encode(protected).decode("ascii")
    # 非 Windows 或 DPAPI 不可用时作可逆编码，避免配置里出现明文。
    return _FALLBACK_PREFIX + base64.b64encode(raw).decode("ascii")


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_SECRET_PREFIX):
        try:
            raw = base64.b64decode(value[len(_SECRET_PREFIX):])
            plain = _dpapi_unprotect(raw)
            return plain.decode("utf-8") if plain else ""
        except Exception:
            return ""
    if value.startswith(_FALLBACK_PREFIX):
        try:
            return base64.b64decode(value[len(_FALLBACK_PREFIX):]).decode("utf-8")
        except Exception:
            return ""
    # 兼容用户手工编辑的配置
    return value


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #
def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class AppConfig:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            self.data = _deep_merge(DEFAULTS, loaded)
        except Exception:
            self.data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    # -- 翻译库位置 -------------------------------------------------------- #
    def library_dir(self) -> str:
        """翻译库目录；空值表示默认的 %APPDATA%\\YiPagePDF。"""
        custom = str(self.data.get("library_dir", "") or "").strip()
        if not custom:
            return os.path.dirname(LIBRARY_PATH)
        return os.path.abspath(os.path.expanduser(custom))

    def library_file(self) -> str:
        return os.path.join(self.library_dir(), "library.sqlite")

    # -- 翻译服务 ---------------------------------------------------------- #
    def provider_config(self, engine: str, decrypt: bool = True) -> Dict[str, Any]:
        config = copy.deepcopy(self.data.get("providers", {}).get(engine, {}))
        if decrypt:
            for field in SECRET_FIELDS.get(engine, ()):
                config[field] = unprotect_secret(str(config.get(field, "")))
        return config

    def set_provider_config(self, engine: str, values: Dict[str, Any]) -> None:
        self.data.setdefault("providers", {}).setdefault(engine, {})
        for key, value in values.items():
            if key in SECRET_FIELDS.get(engine, ()):
                value = protect_secret(str(value or ""))
            self.data["providers"][engine][key] = value

    def remember_file(self, path: str) -> None:
        path = os.path.abspath(path)
        recent = [p for p in self.data.get("recent_files", []) if p != path]
        recent.insert(0, path)
        self.data["recent_files"] = recent[:8]
        self.data["last_dir"] = os.path.dirname(path)
        self.save()


def resource_path(*parts: str) -> str:
    return os.path.join(RESOURCE_DIR, *parts)


def setup_logging() -> str:
    """简单滚动日志；Qt 的异常也会写到这里，方便排查。"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2 * 1024 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        import logging

        logging.basicConfig(
            filename=LOG_PATH,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            encoding="utf-8",
        )
        return LOG_PATH
    except Exception:
        return ""


def install_exception_hook() -> None:
    import logging
    import traceback

    def hook(exc_type, exc, tb):
        logging.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            sys.__stderr__.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    sys.excepthook = hook
