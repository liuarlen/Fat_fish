"""国内翻译服务适配层。

已内置：
- 百度翻译开放平台
- 有道智云
- 腾讯云机器翻译（TMT）
- 阿里云机器翻译
- OpenAI 兼容大模型（DeepSeek / 通义千问 / 智谱 GLM 等）
- 离线本地演示库

所有实现都带连接/读取超时与中文错误提示，网络异常不会让界面永久卡住。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import random
import re
import string
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from .library import DemoMemory


class ProviderError(RuntimeError):
    """可直接展示给用户的翻译服务错误。"""


def _merge_translation_parts(parts: Sequence[str]) -> str:
    """模型把一段拆成多条返回时，尽量无损地重新拼回一段。"""
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    if not cleaned:
        raise ProviderError("翻译服务返回了空结果。")
    if len(cleaned) == 1:
        return cleaned[0]
    result = cleaned[0]
    for part in cleaned[1:]:
        if re.search(r"[\u3400-\u9fff，。；：！？、）】》」』]$", result) or re.match(
            r"^[\u3400-\u9fff，。；：！？、（【《「『]", part
        ):
            result += part
        else:
            result += " " + part
    return re.sub(r"[ \t]{2,}", " ", result).strip()


def translate_batch_resilient(
    request_batch,
    texts: Sequence[str],
    depth: int = 0,
    max_depth: int = 1,
) -> List[str]:
    """批量翻译，并修复模型返回条数不一致的情况。

    某些大模型/网页接口偶尔会把 25 段合并成 23 段。直接报错会让整页无法翻译，
    这里先二分重试；仍不一致时逐条翻译。若单条被拆成多条，则合并回一条。
    """
    items = list(texts)
    if not items:
        return []
    results = request_batch(items)
    if len(results) == len(items):
        return [str(value or "").strip() for value in results]
    if len(items) == 1:
        return [_merge_translation_parts(results)]
    if depth >= max_depth or len(items) <= 8:
        out: List[str] = []
        for text in items:
            single = request_batch([text])
            out.append(_merge_translation_parts(single))
        return out
    middle = max(1, len(items) // 2)
    return (
        translate_batch_resilient(request_batch, items[:middle], depth + 1, max_depth)
        + translate_batch_resilient(request_batch, items[middle:], depth + 1, max_depth)
    )


# --------------------------------------------------------------------------- #
# 服务元数据（设置界面直接从这里生成表单）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    placeholder: str = ""
    secret: bool = False
    help: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    short_label: str
    subtitle: str
    fields: Tuple[FieldSpec, ...] = ()
    docs_url: str = ""
    badge: str = ""


PROVIDER_SPECS: Dict[str, ProviderSpec] = {
    "bilibili": ProviderSpec(
        key="bilibili",
        label="B站 Index-Translate（免费）",
        short_label="B站免费翻译",
        subtitle="B站开源的翻译模型，官方免费接口，无需 API Key，适合轻量使用",
        docs_url="https://github.com/bilibili/Index-Translate",
        badge="免费",
    ),
    "google": ProviderSpec(
        key="google",
        label="Google 翻译（网页免费）",
        short_label="Google 翻译",
        subtitle="Google 公共网页接口，无需 API Key；大陆网络可能不可用或限流",
        docs_url="https://translate.google.com/",
        badge="免费",
    ),
    "demo": ProviderSpec(
        key="demo",
        label="本地演示库（离线）",
        short_label="本地演示库",
        subtitle="使用内置示例语料与你的翻译记忆库，无需联网",
        badge="离线",
    ),
    "baidu": ProviderSpec(
        key="baidu",
        label="百度翻译开放平台",
        short_label="百度翻译",
        subtitle="通用文本翻译，国内访问稳定，支持整页批量请求",
        fields=(
            FieldSpec("appid", "APP ID", "百度翻译开放平台 APP ID"),
            FieldSpec("secret", "密钥", "百度翻译开放平台密钥", secret=True),
        ),
        docs_url="https://fanyi-api.baidu.com/",
        badge="国内 API",
    ),
    "youdao": ProviderSpec(
        key="youdao",
        label="有道智云",
        short_label="有道智云",
        subtitle="网易有道文本翻译，使用 v3 签名接口",
        fields=(
            FieldSpec("app_key", "应用 ID", "有道智云应用 ID"),
            FieldSpec("app_secret", "应用密钥", "有道智云应用密钥", secret=True),
        ),
        docs_url="https://ai.youdao.com/",
        badge="国内 API",
    ),
    "tencent": ProviderSpec(
        key="tencent",
        label="腾讯云机器翻译",
        short_label="腾讯云 TMT",
        subtitle="腾讯云 TMT 批量翻译，支持术语与多语种",
        fields=(
            FieldSpec("secret_id", "SecretId", "腾讯云 SecretId"),
            FieldSpec("secret_key", "SecretKey", "腾讯云 SecretKey", secret=True),
            FieldSpec("region", "地域", "ap-guangzhou"),
        ),
        docs_url="https://cloud.tencent.com/product/tmt",
        badge="国内 API",
    ),
    "aliyun": ProviderSpec(
        key="aliyun",
        label="阿里云机器翻译",
        short_label="阿里云翻译",
        subtitle="阿里云通用版机器翻译（TranslateGeneral）",
        fields=(
            FieldSpec("access_key_id", "AccessKey ID", "阿里云 AccessKey ID"),
            FieldSpec("access_key_secret", "AccessKey Secret", "阿里云 AccessKey Secret", secret=True),
            FieldSpec("region", "地域", "cn-hangzhou"),
        ),
        docs_url="https://help.aliyun.com/product/30313.html",
        badge="国内 API",
    ),
    "llm": ProviderSpec(
        key="llm",
        label="大模型翻译（OpenAI 兼容）",
        short_label="大模型",
        subtitle="DeepSeek / 通义千问 / 智谱 GLM / Moonshot，上下文翻译质量更高",
        fields=(
            FieldSpec("base_url", "Base URL", "https://api.deepseek.com/v1"),
            FieldSpec("model", "模型名", "deepseek-chat"),
            FieldSpec("api_key", "API Key", "sk-...", secret=True),
        ),
        docs_url="https://api-docs.deepseek.com/",
        badge="大模型",
    ),
}

ENGINE_ORDER = ["bilibili", "google", "demo", "baidu", "youdao", "tencent", "aliyun", "llm"]


LLM_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "label": "通义千问（百炼）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "moonshot": {
        "label": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "custom": {
        "label": "自定义接口",
        "base_url": "",
        "model": "",
    },
}


TARGET_NAMES = {
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "ar": "阿拉伯语",
}


BAIDU_LANG = {
    "auto": "auto", "zh-CN": "zh", "zh-TW": "cht", "en": "en",
    "ja": "jp", "ko": "kor", "fr": "fra", "de": "de", "es": "spa",
    "ru": "ru", "pt": "pt", "it": "it", "ar": "ara",
}
YOUDAO_LANG = {
    "auto": "auto", "zh-CN": "zh-CHS", "zh-TW": "zh-CHT", "en": "en",
    "ja": "ja", "ko": "ko", "fr": "fr", "de": "de", "es": "es",
    "ru": "ru", "pt": "pt", "it": "it", "ar": "ar",
}
TENCENT_LANG = {
    "auto": "auto", "zh-CN": "zh", "zh-TW": "zh-TW", "en": "en",
    "ja": "ja", "ko": "ko", "fr": "fr", "de": "de", "es": "es",
    "ru": "ru", "pt": "pt", "it": "it", "ar": "ar",
}
ALIYUN_LANG = {
    "auto": "auto", "zh-CN": "zh", "zh-TW": "zh-tw", "en": "en",
    "ja": "ja", "ko": "ko", "fr": "fr", "de": "de", "es": "es",
    "ru": "ru", "pt": "pt", "it": "it", "ar": "ar",
}


# --------------------------------------------------------------------------- #
# 基类
# --------------------------------------------------------------------------- #
class BaseProvider:
    key = "base"
    label = "翻译服务"

    def __init__(
        self,
        options: Optional[Dict[str, Any]] = None,
        source: str = "auto",
        target: str = "zh-CN",
        glossary: Optional[Sequence[Tuple[str, str]]] = None,
    ):
        self.options = options or {}
        self.source = source
        self.target = target
        self.glossary = list(glossary or [])
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Fat_fish/1.2.1 (Windows; PDF in-place translator)",
        })

    # -- 配置 -------------------------------------------------------------- #
    def missing_fields(self) -> List[str]:
        spec = PROVIDER_SPECS.get(self.key)
        missing = []
        for item in (spec.fields if spec else ()):
            if not str(self.options.get(item.key, "")).strip():
                missing.append(item.label)
        return missing

    def validate(self) -> None:
        missing = self.missing_fields()
        if missing:
            raise ProviderError("请在「设置 → 翻译服务」中填写：" + "、".join(missing))

    # -- 接口 -------------------------------------------------------------- #
    def translate(self, text: str) -> str:
        raise NotImplementedError

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        """默认逐条翻译；网络请求并发 4 路，避免整页串行等待。"""
        items = [t or "" for t in texts]
        if not any(t.strip() for t in items):
            return ["" for _ in items]
        results: List[str] = ["" for _ in items]
        indices = [i for i, t in enumerate(items) if t.strip()]

        def work(index: int) -> Tuple[int, str]:
            return index, self.translate(items[index])

        if len(indices) == 1:
            index = indices[0]
            results[index] = work(index)[1]
            return results
        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=min(4, len(indices))) as pool:
            for index, translated in pool.map(work, indices):
                results[index] = translated
        return results

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # -- HTTP -------------------------------------------------------------- #
    def _request_json(
        self,
        method: str,
        url: str,
        timeout: Tuple[float, float] = (10.0, 40.0),
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ConnectTimeout:
            raise ProviderError("连接翻译服务超时，请检查网络或代理设置。")
        except requests.exceptions.ReadTimeout:
            raise ProviderError("翻译服务响应超时，请稍后重试。")
        except requests.exceptions.SSLError:
            raise ProviderError("HTTPS 证书校验失败，请检查系统时间或代理。")
        except requests.exceptions.RequestException as exc:
            raise ProviderError(f"网络请求失败：{str(exc)[:160]}")
        if response.status_code != 200:
            body = (response.text or "")[:200]
            raise ProviderError(f"翻译服务返回 HTTP {response.status_code}：{body}")
        try:
            return response.json()
        except ValueError:
            raise ProviderError("翻译服务返回了无法解析的内容。")


# --------------------------------------------------------------------------- #
# 百度
# --------------------------------------------------------------------------- #
class BaiduProvider(BaseProvider):
    key = "baidu"
    label = "百度翻译"
    ENDPOINT = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    _ERRORS = {
        "52001": "请求超时，请重试。",
        "52002": "翻译服务系统错误，请重试。",
        "52003": "APP ID 或密钥无效，请检查设置。",
        "54000": "必填参数为空。",
        "54001": "签名错误，请检查密钥。",
        "54003": "访问频率受限，请稍后再试。",
        "54004": "账户余额不足。",
        "54005": "长文本请求频繁，请降低速度。",
        "58000": "客户端 IP 非法。",
        "58001": "目标语言不支持。",
        "58002": "服务已关闭。",
    }

    def _translate_chunk(self, texts: Sequence[str]) -> List[str]:
        self.validate()
        appid = str(self.options.get("appid", "")).strip()
        secret = str(self.options.get("secret", "")).strip()
        q = "\n".join(re.sub(r"\s*\n\s*", " ", t).strip() for t in texts)
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5((appid + q + salt + secret).encode("utf-8")).hexdigest()
        data = {
            "q": q,
            "from": BAIDU_LANG.get(self.source, self.source or "auto"),
            "to": BAIDU_LANG.get(self.target, self.target),
            "appid": appid,
            "salt": salt,
            "sign": sign,
        }
        payload = self._request_json("POST", self.ENDPOINT, data=data)
        if payload.get("error_code"):
            code = str(payload.get("error_code"))
            message = self._ERRORS.get(code) or payload.get("error_msg") or "未知错误"
            raise ProviderError(f"百度翻译：{message}（{code}）")
        rows = payload.get("trans_result") or []
        results = [str(row.get("dst", "")) for row in rows if isinstance(row, dict)]
        if len(results) != len(texts):
            # 极少数情况下换行会被合并，单条重试保证不串段
            if len(texts) == 1:
                return [results[0] if results else ""]
            return [self._translate_single(t) for t in texts]
        return results

    def _translate_single(self, text: str) -> str:
        q = re.sub(r"\s*\n\s*", " ", text).strip()
        appid = str(self.options.get("appid", "")).strip()
        secret = str(self.options.get("secret", "")).strip()
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5((appid + q + salt + secret).encode("utf-8")).hexdigest()
        payload = self._request_json("POST", self.ENDPOINT, data={
            "q": q,
            "from": BAIDU_LANG.get(self.source, self.source or "auto"),
            "to": BAIDU_LANG.get(self.target, self.target),
            "appid": appid,
            "salt": salt,
            "sign": sign,
        })
        if payload.get("error_code"):
            code = str(payload.get("error_code"))
            raise ProviderError(
                "百度翻译：" + (self._ERRORS.get(code) or payload.get("error_msg") or "未知错误")
                + f"（{code}）"
            )
        rows = payload.get("trans_result") or []
        return "\n".join(str(row.get("dst", "")) for row in rows if isinstance(row, dict))

    def translate(self, text: str) -> str:
        return self._translate_single(text)

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = [re.sub(r"\s*\n\s*", " ", t or "").strip() for t in texts]
        results: List[str] = ["" for _ in items]
        batches: List[List[int]] = []
        current: List[int] = []
        size = 0
        for index, text in enumerate(items):
            if not text:
                continue
            length = len(text.encode("utf-8"))
            if current and size + length > 4800:
                batches.append(current)
                current, size = [], 0
            current.append(index)
            size += length + 1
        if current:
            batches.append(current)
        for batch in batches:
            translated = self._translate_chunk([items[i] for i in batch])
            for index, value in zip(batch, translated):
                results[index] = value
        return results


# --------------------------------------------------------------------------- #
# 有道
# --------------------------------------------------------------------------- #
class YoudaoProvider(BaseProvider):
    key = "youdao"
    label = "有道智云"
    ENDPOINT = "https://openapi.youdao.com/api"

    _ERRORS = {
        "101": "应用 ID 无效。",
        "102": "应用密钥无效。",
        "103": "翻译文本过长。",
        "108": "应用 ID 未授权。",
        "110": "无相关服务。",
        "111": "账户欠费。",
        "112": "请求频率受限。",
        "113": "查询文本为空。",
        "202": "签名校验失败。",
        "401": "账户已停用。",
        "411": "访问频率受限。",
        "412": "请求过长。",
    }

    @staticmethod
    def _truncate(text: str) -> str:
        size = len(text)
        if size <= 20:
            return text
        return text[:10] + str(size) + text[-10:]

    def _request(self, texts: Sequence[str]) -> List[str]:
        self.validate()
        app_key = str(self.options.get("app_key", "")).strip()
        app_secret = str(self.options.get("app_secret", "")).strip()
        q = "\n".join(re.sub(r"\s*\n\s*", " ", t).strip() for t in texts)
        salt = str(uuid.uuid4())
        curtime = str(int(time.time()))
        sign_str = app_key + self._truncate(q) + salt + curtime + app_secret
        sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
        payload = self._request_json("POST", self.ENDPOINT, data={
            "q": q,
            "from": YOUDAO_LANG.get(self.source, self.source or "auto"),
            "to": YOUDAO_LANG.get(self.target, self.target),
            "appKey": app_key,
            "salt": salt,
            "sign": sign,
            "signType": "v3",
            "curtime": curtime,
        })
        code = str(payload.get("errorCode", "0"))
        if code != "0":
            raise ProviderError(
                "有道智云：" + (self._ERRORS.get(code) or "翻译失败")
                + f"（错误码 {code}）"
            )
        translation = payload.get("translation") or []
        if isinstance(translation, str):
            translation = [translation]
        values = [str(v).strip() for v in translation]
        if len(values) == len(texts):
            return values
        if len(texts) == 1:
            return [values[0] if values else ""]
        # 返回是整段译文时，用换行还原；数量对不上就逐条重试
        if len(values) == 1 and "\n" in values[0]:
            parts = [p.strip() for p in values[0].split("\n")]
            if len(parts) == len(texts):
                return parts
        return [self.translate(t) for t in texts]

    def translate(self, text: str) -> str:
        return self._request([text])[0]

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = [re.sub(r"\s*\n\s*", " ", t or "").strip() for t in texts]
        results: List[str] = ["" for _ in items]
        batch: List[int] = []
        size = 0
        for index, text in enumerate(items):
            if not text:
                continue
            if batch and size + len(text) > 4500:
                translated = self._request([items[i] for i in batch])
                for target_index, value in zip(batch, translated):
                    results[target_index] = value
                batch, size = [], 0
            batch.append(index)
            size += len(text) + 1
        if batch:
            translated = self._request([items[i] for i in batch])
            for target_index, value in zip(batch, translated):
                results[target_index] = value
        return results


# --------------------------------------------------------------------------- #
# 腾讯云 TMT
# --------------------------------------------------------------------------- #
class TencentProvider(BaseProvider):
    key = "tencent"
    label = "腾讯云机器翻译"
    HOST = "tmt.tencentcloudapi.com"
    SERVICE = "tmt"
    VERSION = "2018-03-21"

    @staticmethod
    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _headers(self, action: str, payload: str) -> Dict[str, str]:
        secret_id = str(self.options.get("secret_id", "")).strip()
        secret_key = str(self.options.get("secret_key", "")).strip()
        region = str(self.options.get("region", "ap-guangzhou")).strip() or "ap-guangzhou"
        timestamp = int(time.time())
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        content_type = "application/json; charset=utf-8"
        host = self.HOST
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host}\n"
            f"x-tc-action:{action.lower()}\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            "POST\n/\n\n" + canonical_headers + "\n" + signed_headers
            + "\n" + hashed_payload
        )
        credential_scope = f"{date}/{self.SERVICE}/tc3_request"
        string_to_sign = (
            "TC3-HMAC-SHA256\n" + str(timestamp) + "\n" + credential_scope
            + "\n" + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        )
        k_date = self._hmac(("TC3" + secret_key).encode("utf-8"), date)
        k_service = self._hmac(k_date, self.SERVICE)
        k_signing = self._hmac(k_service, "tc3_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        authorization = (
            "TC3-HMAC-SHA256 "
            f"Credential={secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": self.VERSION,
            "X-TC-Region": region,
        }

    def _request_chunk(self, texts: Sequence[str]) -> List[str]:
        self.validate()
        body = {
            "SourceTextList": list(texts),
            "Source": TENCENT_LANG.get(self.source, self.source or "auto"),
            "Target": TENCENT_LANG.get(self.target, self.target),
            "ProjectId": 0,
        }
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        headers = self._headers("TextTranslateBatch", payload)
        data = self._request_json(
            "POST", f"https://{self.HOST}", data=payload.encode("utf-8"),
            headers=headers, timeout=(10.0, 50.0),
        )
        response = data.get("Response") or {}
        error = response.get("Error") or {}
        if error:
            raise ProviderError(
                f"腾讯云 TMT：{error.get('Message') or '请求失败'}"
                f"（{error.get('Code') or 'unknown'}）"
            )
        results = response.get("TargetTextList") or []
        if len(results) != len(texts):
            raise ProviderError("腾讯云 TMT 返回的译文数量与原文不一致。")
        return [str(v) for v in results]

    def translate(self, text: str) -> str:
        return self._request_chunk([text])[0]

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = [re.sub(r"\s*\n\s*", " ", t or "").strip() for t in texts]
        results: List[str] = ["" for _ in items]
        for start in range(0, len(items), 20):
            chunk = items[start:start + 20]
            translated = self._request_chunk(chunk)
            for offset, value in enumerate(translated):
                results[start + offset] = value
        return results


# --------------------------------------------------------------------------- #
# 阿里云
# --------------------------------------------------------------------------- #
class AliyunProvider(BaseProvider):
    key = "aliyun"
    label = "阿里云机器翻译"

    @staticmethod
    def _percent(value: str) -> str:
        return quote(str(value), safe="~")

    def _translate_one(self, text: str) -> str:
        self.validate()
        access_id = str(self.options.get("access_key_id", "")).strip()
        access_secret = str(self.options.get("access_key_secret", "")).strip()
        region = str(self.options.get("region", "cn-hangzhou")).strip() or "cn-hangzhou"
        endpoint = f"https://mt.{region}.aliyuncs.com/"
        params = {
            "AccessKeyId": access_id,
            "Action": "TranslateGeneral",
            "Format": "JSON",
            "FormatType": "text",
            "RegionId": region,
            "Scene": "general",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "SourceLanguage": ALIYUN_LANG.get(self.source, self.source or "auto"),
            "SourceText": re.sub(r"\s*\n\s*", " ", text).strip(),
            "TargetLanguage": ALIYUN_LANG.get(self.target, self.target),
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2018-10-12",
        }
        canonical = "&".join(
            f"{self._percent(k)}={self._percent(v)}"
            for k, v in sorted(params.items())
        )
        string_to_sign = "GET&%2F&" + self._percent(canonical)
        signature = base64.b64encode(
            hmac.new(
                (access_secret + "&").encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")
        params["Signature"] = signature
        payload = self._request_json("GET", endpoint, params=params)
        if payload.get("Code"):
            raise ProviderError(
                f"阿里云翻译：{payload.get('Message') or '请求失败'}"
                f"（{payload.get('Code')}）"
            )
        data = payload.get("Data") or {}
        value = data.get("Translated") or data.get("Translation") or ""
        if not value:
            raise ProviderError("阿里云翻译返回了空译文。")
        return str(value)

    def translate(self, text: str) -> str:
        return self._translate_one(text)

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = [t or "" for t in texts]
        results: List[str] = ["" for _ in items]
        indices = [i for i, t in enumerate(items) if t.strip()]
        with ThreadPoolExecutor(max_workers=min(4, len(indices) or 1)) as pool:
            for index, value in zip(indices, pool.map(lambda i: self._translate_one(items[i]), indices)):
                results[index] = value
        return results


# --------------------------------------------------------------------------- #
# 大模型（OpenAI 兼容）
# --------------------------------------------------------------------------- #
class LLMProvider(BaseProvider):
    key = "llm"
    label = "大模型翻译"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = str(self.options.get("base_url") or "https://api.deepseek.com/v1").strip()
        base = base.rstrip("/")
        if base.endswith("/chat/completions"):
            self.url = base
        else:
            self.url = base + "/chat/completions"
        self.model = str(self.options.get("model") or "deepseek-chat").strip()
        self.temperature = float(self.options.get("temperature", 0.1) or 0.1)

    def validate(self) -> None:
        missing = []
        if not str(self.options.get("api_key", "")).strip():
            missing.append("API Key")
        if not str(self.options.get("base_url", "")).strip():
            missing.append("Base URL")
        if not str(self.options.get("model", "")).strip():
            missing.append("模型名")
        if missing:
            raise ProviderError("请在「设置 → 翻译服务」中填写：" + "、".join(missing))

    def _prompt(self, texts: Sequence[str]) -> str:
        lang = TARGET_NAMES.get(self.target, self.target)
        glossary = ""
        if self.glossary:
            terms = {source: target for source, target in self.glossary}
            glossary = (
                "\n优先采用以下术语对照（原文 => 译文）：\n"
                + json.dumps(terms, ensure_ascii=False, indent=1)
            )
        return (
            f"你是专业的 PDF 文档翻译引擎。请把下面的 JSON 字符串数组逐项翻译成{lang}。"
            "要求：\n"
            "1. 只输出一个 JSON 字符串数组，长度与输入完全一致，不要输出解释或 Markdown；\n"
            "2. 保持段落完整，不合并、不拆分、不遗漏；\n"
            "3. 数字、公式、图表编号、网址、引用标记、专有缩写保持原样；\n"
            "4. 译文自然、准确，适合正式文档阅读，不要添加原文没有的内容。"
            + glossary
            + "\n\n输入：\n"
            + json.dumps(list(texts), ensure_ascii=False, indent=1)
        )

    @staticmethod
    def _parse_array(content: str) -> List[str]:
        text = (content or "").strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except Exception:
            match = re.search(r"\[[\s\S]*\]", text)
            if not match:
                raise ProviderError("大模型没有返回可解析的 JSON 数组。")
            try:
                data = json.loads(match.group(0))
            except Exception:
                raise ProviderError("大模型返回的 JSON 格式不正确。")
        if isinstance(data, dict):
            for key in ("translations", "result", "data", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                raise ProviderError("大模型返回的不是数组。")
        if not isinstance(data, list):
            raise ProviderError("大模型返回的不是数组。")
        return [str(item) for item in data]

    def _request_batch(self, texts: Sequence[str]) -> List[str]:
        self.validate()
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个严谨的文档翻译引擎，只输出要求的 JSON 数组。",
                },
                {"role": "user", "content": self._prompt(texts)},
            ],
        }
        payload = self._request_json(
            "POST", self.url, json=body, timeout=(15.0, 150.0),
            headers={
                "Authorization": f"Bearer {self.options.get('api_key', '')}",
                "Content-Type": "application/json",
            },
        )
        if payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                error = error.get("message") or str(error)
            raise ProviderError(f"大模型接口：{str(error)[:300]}")
        try:
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except Exception:
            raise ProviderError(f"大模型接口返回异常：{str(payload)[:200]}")
        return self._parse_array(content)

    def translate(self, text: str) -> str:
        return translate_batch_resilient(self._request_batch, [text])[0]

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = list(texts)
        out: List[str] = []
        current: List[str] = []
        size = 0
        for text in items:
            if current and (len(current) >= 25 or size + len(text) > 26000):
                out.extend(translate_batch_resilient(self._request_batch, current))
                current, size = [], 0
            current.append(text)
            size += len(text)
        if current:
            out.extend(translate_batch_resilient(self._request_batch, current))
        return out


# --------------------------------------------------------------------------- #
# Google 翻译（网页免费接口，无需 Key）
# --------------------------------------------------------------------------- #
class GoogleProvider(BaseProvider):
    """Google Translate 的公共网页接口，不需要 API Key。

    这是非官方网页接口，可能限流；大陆网络通常无法直接访问。
    """

    key = "google"
    label = "Google 翻译"
    PRIMARY = "https://translate.googleapis.com/translate_a/single"
    BACKUP = "https://clients5.google.com/translate_a/t"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

    def _lang(self) -> str:
        return {
            "zh-CN": "zh-CN",
            "zh-TW": "zh-TW",
            "auto": "auto",
        }.get(self.target, self.target or "auto")

    def _parse_payload(self, data) -> str:
        if isinstance(data, dict):
            for key in ("translatedText", "translation", "text"):
                if data.get(key):
                    return str(data[key])
            sentences = data.get("sentences")
            if isinstance(sentences, list):
                return "".join(
                    str(item.get("trans") or item.get("text") or "")
                    for item in sentences if isinstance(item, dict)
                )
            return ""
        if isinstance(data, list):
            # translate_a/single: [[["译文", "原文", ...], ...], ...]
            if data and isinstance(data[0], list):
                pieces: List[str] = []
                for segment in data[0]:
                    if isinstance(segment, list) and segment:
                        pieces.append(str(segment[0] or ""))
                    elif isinstance(segment, str):
                        pieces.append(segment)
                if pieces:
                    return "".join(pieces)
            # clients5 translate_a/t: ["译文", ...]
            if data and all(isinstance(item, str) for item in data):
                return "".join(data)
            # 有些返回是 [{"translatedText": "..."}]
            if data and isinstance(data[0], dict):
                return "".join(
                    str(item.get("translatedText") or item.get("trans") or "")
                    for item in data if isinstance(item, dict)
                )
        return ""

    def _request_raw(self, text: str) -> str:
        source = "auto" if self.source in ("", "auto") else self.source
        params = {
            "client": "gtx",
            "sl": source,
            "tl": self._lang(),
            "dt": "t",
            "q": text,
        }
        errors = []
        try:
            payload = self._request_json(
                "GET", self.PRIMARY, params=params, timeout=(8.0, 35.0)
            )
            translated = self._parse_payload(payload).strip()
            if translated:
                return translated
        except ProviderError as exc:
            errors.append(str(exc))
        try:
            payload = self._request_json(
                "GET",
                self.BACKUP,
                params={
                    "client": "dict-chrome-ex",
                    "sl": source,
                    "tl": self._lang(),
                    "q": text,
                },
                timeout=(8.0, 35.0),
            )
            translated = self._parse_payload(payload).strip()
            if translated:
                return translated
        except ProviderError as exc:
            errors.append(str(exc))
        joined = "；".join(errors)
        if "429" in joined:
            raise ProviderError(
                "Google 免费网页接口当前限流（HTTP 429）。"
                "请稍后再试，或改用 B站免费翻译/其它服务。"
            )
        raise ProviderError(
            "Google 翻译请求失败，可能需要代理或当前网络无法访问。"
            + (f"（{joined[:240]}）" if joined else "")
            + " 可改用 B站免费翻译或配置国内云服务。"
        )

    @staticmethod
    def _markers(count: int) -> List[str]:
        return [f"[[{index + 1}]]" for index in range(count)]

    def _translate_chunk(self, texts: Sequence[str]) -> List[str]:
        items = list(texts)
        if len(items) == 1:
            return [self._request_raw(items[0])]
        markers = self._markers(len(items))
        merged = "\n".join(
            f"{marker} {text}" for marker, text in zip(markers, items)
        )
        translated = self._request_raw(merged)
        positions = [translated.find(marker) for marker in markers]
        if all(position >= 0 for position in positions) and positions == sorted(positions):
            results: List[str] = []
            for index, position in enumerate(positions):
                start = position + len(markers[index])
                end = positions[index + 1] if index + 1 < len(positions) else len(translated)
                results.append(translated[start:end].strip())
            if all(results):
                return results
        # 标记被翻译坏时，退化为逐条请求，保证顺序和数量。
        return [self._request_raw(text) for text in items]

    def translate(self, text: str) -> str:
        return self._request_raw(text)

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = list(texts)
        results: List[str] = ["" for _ in items]
        current: List[int] = []
        size = 0
        batches: List[List[int]] = []
        for index, text in enumerate(items):
            if not (text or "").strip():
                continue
            if current and (len(current) >= 12 or size + len(text) > 2800):
                batches.append(current)
                current, size = [], 0
            current.append(index)
            size += len(text)
        if current:
            batches.append(current)
        for batch in batches:
            translated = self._translate_chunk([items[index] for index in batch])
            for index, value in zip(batch, translated):
                results[index] = value
        return results


# --------------------------------------------------------------------------- #
# B站 Index-Translate（免费、无需 Key）
# --------------------------------------------------------------------------- #
class BilibiliProvider(BaseProvider):
    """B站开源的 Index-Translate 翻译模型。

    官方提供免 Key 的 OpenAI 兼容接口，适合作为开箱即用的免费线路。
    这是公共免费服务，可能限流或变更，不适合高并发/敏感文档。
    """

    key = "bilibili"
    label = "B站免费翻译"
    URL = "https://index-translate.bilibili.com/v1/chat/completions"
    MODEL = "Index-Translate-35B-A3B"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session.headers.update({"Content-Type": "application/json"})

    def _prompt(self, texts: Sequence[str]) -> str:
        lang = TARGET_NAMES.get(self.target, self.target)
        glossary = ""
        if self.glossary:
            terms = {source: target for source, target in self.glossary}
            glossary = (
                "\n优先采用以下术语对照（原文 => 译文）：\n"
                + json.dumps(terms, ensure_ascii=False, indent=1)
            )
        return (
            f"把下面的 JSON 字符串数组逐项翻译成{lang}。"
            "只输出一个 JSON 字符串数组，长度和顺序与输入完全一致，不要输出解释或 Markdown。"
            "保持段落完整，不合并、不拆分；数字、公式、图表编号、网址、引用标记保持原样。"
            + glossary
            + "\n输入：\n"
            + json.dumps(list(texts), ensure_ascii=False, indent=1)
        )

    def _request_batch(self, texts: Sequence[str]) -> List[str]:
        body = {
            "model": self.MODEL,
            "temperature": 0.1,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的文档翻译引擎，只输出要求的 JSON 字符串数组。",
                },
                {"role": "user", "content": self._prompt(texts)},
            ],
        }
        try:
            payload = self._request_json(
                "POST", self.URL, json=body, timeout=(10.0, 75.0)
            )
        except ProviderError as exc:
            text = str(exc)
            if "429" in text or "频率" in text or "限流" in text:
                raise ProviderError(
                    "B站免费翻译当前请求过多，请稍后再试，"
                    "或在设置中改用本地库/其它翻译服务。"
                )
            raise
        if payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                error = error.get("message") or str(error)
            raise ProviderError(f"B站免费翻译：{str(error)[:240]}")
        try:
            content = payload["choices"][0]["message"]["content"]
        except Exception:
            raise ProviderError(f"B站免费翻译返回异常：{str(payload)[:200]}")
        if not str(content or "").strip():
            raise ProviderError("B站免费翻译返回了空译文。")
        try:
            return LLMProvider._parse_array(content)
        except ProviderError as exc:
            raise ProviderError(f"B站免费翻译返回格式异常：{exc}")

    def translate(self, text: str) -> str:
        return translate_batch_resilient(self._request_batch, [text])[0]

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        items = list(texts)
        results: List[str] = ["" for _ in items]
        batches: List[List[int]] = []
        current: List[int] = []
        size = 0
        for index, text in enumerate(items):
            if not (text or "").strip():
                continue
            if current and (len(current) >= 20 or size + len(text) > 12000):
                batches.append(current)
                current, size = [], 0
            current.append(index)
            size += len(text)
        if current:
            batches.append(current)
        for batch in batches:
            translated = translate_batch_resilient(
                self._request_batch, [items[i] for i in batch]
            )
            for index, value in zip(batch, translated):
                results[index] = value
        return results


# --------------------------------------------------------------------------- #
# 离线演示
# --------------------------------------------------------------------------- #
class DemoProvider(BaseProvider):
    key = "demo"
    label = "本地演示库"

    def __init__(self, *args, demo_path: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.demo = DemoMemory(demo_path) if demo_path else None

    def translate(self, text: str) -> str:
        hit = self.demo.lookup(text) if self.demo else None
        return hit.target if hit else ""

    def translate_many(self, texts: Sequence[str]) -> List[str]:
        return [self.translate(text) for text in texts]


def create_provider(
    engine: str,
    options: Dict[str, Any],
    source: str,
    target: str,
    glossary: Optional[Sequence[Tuple[str, str]]] = None,
    demo_path: str = "",
) -> BaseProvider:
    engine = (engine or "bilibili").lower()
    if engine == "bilibili":
        return BilibiliProvider(options, source, target, glossary)
    if engine == "google":
        return GoogleProvider(options, source, target, glossary)
    if engine == "baidu":
        return BaiduProvider(options, source, target, glossary)
    if engine == "youdao":
        return YoudaoProvider(options, source, target, glossary)
    if engine == "tencent":
        return TencentProvider(options, source, target, glossary)
    if engine == "aliyun":
        return AliyunProvider(options, source, target, glossary)
    if engine == "llm":
        return LLMProvider(options, source, target, glossary)
    if engine == "demo":
        return DemoProvider(options, source, target, glossary, demo_path=demo_path)
    raise ProviderError(f"未知翻译服务：{engine}")
