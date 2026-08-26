from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ehrm.core.exceptions import (
    AiConnectionFailedError,
    AiRequestFailedError,
    AiResponseInvalidError,
    ConfigurationError,
)
from ehrm.core.settings import AiSamplingSettings, OllamaSettings
from ehrm.modules.ai.models import (
    ExtractionResponse,
    ModelMetrics,
    ReasoningMode,
)
from ehrm.modules.ai.normalizer import normalize_semantic_extraction
from ehrm.modules.ai.v2_models import (
    SEMANTIC_EXTRACTION_JSON_SCHEMA,
    validate_semantic_extraction_payload,
)
from ehrm.modules.erp.models import ErpTaskRecord


class OllamaTaskExtractionClient:
    """Calls an Ollama-hosted Qwen model and validates structured output."""

    def __init__(
        self,
        settings: OllamaSettings,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self._system_prompt = self._load_prompt(settings.prompt_path)

    def ensure_available(self) -> None:
        payload = self._request_json(
            "GET",
            self._url("/api/tags"),
            operation="检查 Ollama 服务",
            connection_error=True,
        )
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise AiConnectionFailedError("Ollama 模型列表响应格式不正确")
        names = {
            str(item.get("name") or item.get("model") or "").strip()
            for item in raw_models
            if isinstance(item, dict)
        }
        if self.settings.model not in names:
            raise AiConnectionFailedError(
                f"Ollama 未部署模型：{self.settings.model}",
                details="当前模型：" + "、".join(sorted(name for name in names if name)),
            )

    def extract(
        self,
        record: ErpTaskRecord,
        reasoning_mode: str | ReasoningMode,
    ) -> ExtractionResponse:
        mode = ReasoningMode.parse(reasoning_mode)
        input_payload = {
            "application_date": record.initiated_date,
            "title_summary": record.title,
            "request_details": record.description,
        }
        request_payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(input_payload, ensure_ascii=False),
                },
            ],
            "stream": False,
            "think": mode.ollama_think,
            "format": SEMANTIC_EXTRACTION_JSON_SCHEMA,
            "keep_alive": self.settings.keep_alive,
            "options": self._options(mode),
        }

        last_error: AiRequestFailedError | AiResponseInvalidError | None = None
        for attempt in range(self.settings.retry_count + 1):
            if attempt:
                self.logger.info(
                    "重试大模型任务解析 code=%s attempt=%s",
                    record.code,
                    attempt + 1,
                )
                time.sleep(self.settings.retry_delay_ms / 1000)
            try:
                response = self._request_json(
                    "POST",
                    self._url(self.settings.chat_path),
                    payload=request_payload,
                    operation="解析 ERP 任务",
                )
                return self._parse_response(
                    response,
                    mode,
                    record=record,
                )
            except (AiRequestFailedError, AiResponseInvalidError) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _parse_response(
        self,
        payload: dict[str, Any],
        mode: ReasoningMode,
        *,
        record: ErpTaskRecord,
    ) -> ExtractionResponse:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise AiResponseInvalidError("Ollama 响应缺少 message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            done_reason = str(payload.get("done_reason") or "")
            raise AiResponseInvalidError(
                "模型没有返回最终 JSON",
                details=(
                    f"done_reason={done_reason or 'unknown'}；"
                    "可能是推理内容耗尽了 num_predict，请提高该配置"
                ),
            )
        try:
            raw_extraction = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AiResponseInvalidError(
                "模型返回的内容不是合法 JSON",
                details=str(exc),
            ) from exc
        extraction = normalize_semantic_extraction(
            validate_semantic_extraction_payload(raw_extraction),
            record,
        )
        thinking = message.get("thinking")
        metrics = ModelMetrics(
            model=str(payload.get("model") or self.settings.model),
            reasoning_mode=mode.value,
            ollama_think=mode.ollama_think,
            done_reason=str(payload.get("done_reason") or ""),
            total_duration_ns=self._non_negative_int(payload.get("total_duration")),
            prompt_eval_count=self._non_negative_int(
                payload.get("prompt_eval_count")
            ),
            eval_count=self._non_negative_int(payload.get("eval_count")),
            thinking_characters=len(thinking) if isinstance(thinking, str) else 0,
        )
        return ExtractionResponse(extraction=extraction, metrics=metrics)

    def _options(self, mode: ReasoningMode) -> dict[str, int | float]:
        sampling = (
            self.settings.non_thinking
            if mode is ReasoningMode.OFF
            else self.settings.thinking
        )
        return {
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "top_k": sampling.top_k,
            "min_p": sampling.min_p,
            "presence_penalty": sampling.presence_penalty,
            "repeat_penalty": sampling.repeat_penalty,
            "num_ctx": self.settings.num_ctx,
            "num_predict": self.settings.num_predict,
        }

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        operation: str,
        connection_error: bool = False,
    ) -> dict[str, Any]:
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        error_type = AiConnectionFailedError if connection_error else AiRequestFailedError
        try:
            with urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                status = response.status
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = self._error_message(body) or f"HTTP {exc.code}"
            raise error_type(f"{operation}失败：{message}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise error_type(
                f"{operation}失败",
                details=str(getattr(exc, "reason", exc)),
            ) from exc
        if not 200 <= status < 300:
            raise error_type(f"{operation}返回 HTTP {status}")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise error_type(
                f"{operation}返回了无法解析的数据",
                details=str(exc),
            ) from exc
        if not isinstance(parsed, dict):
            raise error_type(f"{operation}响应根节点不是 JSON 对象")
        if parsed.get("error"):
            raise error_type(f"{operation}失败：{parsed['error']}")
        return parsed

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _load_prompt(path: Path) -> str:
        if not path.is_file():
            raise ConfigurationError(f"大模型提示词文件不存在：{path}")
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(
                f"无法读取大模型提示词：{path}", details=str(exc)
            ) from exc
        if not content:
            raise ConfigurationError(f"大模型提示词内容为空：{path}")
        return content

    @staticmethod
    def _error_message(body: str) -> str:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body.strip()[:500]
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or "").strip()
        return ""

    @staticmethod
    def _non_negative_int(value: object) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
