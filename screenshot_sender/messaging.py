import functools
import logging
import base64
import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )
except ImportError:
    lark = None
    CreateImageRequest = None
    CreateImageRequestBody = None
    CreateMessageRequest = None
    CreateMessageRequestBody = None

from .common import require_dependency


logger = logging.getLogger("screenshot_sender")


def retry(max_attempts: int = 3, base_delay: float = 2.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt < max_attempts - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"推送失败 (第{attempt + 1}次): {exc}, {delay:.0f}秒后重试"
                        )
                        time.sleep(delay)
            raise last_error

        return wrapper

    return decorator


class Messenger(ABC):
    @abstractmethod
    def send_text(self, text: str) -> None:
        pass

    @abstractmethod
    def send_image(self, image_path: str) -> None:
        pass


class FeishuMessenger(Messenger):
    def __init__(self, app_id: str, app_secret: str, log_level: str = "INFO"):
        require_dependency("lark_oapi", lark)

        level_map = {
            "DEBUG": lark.LogLevel.DEBUG,
            "INFO": lark.LogLevel.INFO,
            "WARNING": lark.LogLevel.WARNING,
            "ERROR": lark.LogLevel.ERROR,
        }

        self.client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(level_map.get(log_level.upper(), lark.LogLevel.INFO))
            .build()
        )
        self.receive_id_type: Optional[str] = None
        self.receive_id: Optional[str] = None

    @retry()
    def upload_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            request = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                )
                .build()
            )

            response = self.client.im.v1.image.create(request)

        if not response.success():
            raise RuntimeError(
                f"上传图片失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )

        return response.data.image_key

    def configure_target(self, receive_id_type: str, receive_id: str) -> None:
        self.receive_id_type = receive_id_type
        self.receive_id = receive_id

    def _require_target(self) -> Tuple[str, str]:
        if not self.receive_id_type or not self.receive_id:
            raise RuntimeError("飞书接收目标未配置")
        return self.receive_id_type, self.receive_id

    @retry()
    def send_text(self, text: str) -> None:
        receive_id_type, receive_id = self._require_target()
        content = json.dumps({"text": text}, ensure_ascii=False)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.create(request)

        if not response.success():
            raise RuntimeError(
                f"发送文本失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )

    @retry()
    def send_image(self, image_path: str) -> None:
        receive_id_type, receive_id = self._require_target()
        image_key = self.upload_image(image_path)
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("image")
                .content(content)
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.create(request)

        if not response.success():
            raise RuntimeError(
                f"发送图片失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )


class WecomMessenger(Messenger):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    @staticmethod
    def build_image_payload(image_path: str) -> dict:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        return {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(image_bytes).decode("utf-8"),
                "md5": hashlib.md5(image_bytes).hexdigest(),
            },
        }

    @retry()
    def _post_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=15) as response:
                resp_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"企业微信请求失败: status={e.code}, body={detail}") from e
        except (urllib_error.URLError, OSError) as e:
            reason = getattr(e, "reason", str(e))
            raise RuntimeError(f"企业微信请求失败: {reason}") from e

        try:
            result = json.loads(resp_body) if resp_body else {}
        except json.JSONDecodeError as e:
            raise RuntimeError(f"企业微信返回了非法 JSON: {resp_body}") from e

        if result.get("errcode", 0) != 0:
            raise RuntimeError(
                f"企业微信发送失败: errcode={result.get('errcode')}, errmsg={result.get('errmsg')}"
            )

    def send_text(self, text: str) -> None:
        self._post_json(
            {
                "msgtype": "text",
                "text": {
                    "content": text,
                },
            }
        )

    def send_image(self, image_path: str) -> None:
        self._post_json(self.build_image_payload(image_path))


def build_messenger(cfg: dict) -> Messenger:
    provider = cfg["PUSH_PROVIDER"]

    if provider == "feishu":
        messenger = FeishuMessenger(
            app_id=cfg["APP_ID"],
            app_secret=cfg["APP_SECRET"],
            log_level=cfg["LOG_LEVEL"],
        )
        messenger.configure_target(
            receive_id_type=cfg["RECEIVE_ID_TYPE"],
            receive_id=cfg["RECEIVE_ID"],
        )
        return messenger

    if provider == "wecom":
        return WecomMessenger(webhook_url=cfg["WECOM_WEBHOOK_URL"])

    raise ValueError(f"不支持的 PUSH_PROVIDER: {provider}")
