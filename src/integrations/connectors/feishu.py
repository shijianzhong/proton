from __future__ import annotations

import asyncio
import json
import logging
import time
import hashlib
import hmac
import re
from typing import Any, Dict, Optional, cast

import aiohttp

from ...portal import get_portal_manager
from ..models import PortalChannelBinding
from ..media_store import save_bytes
from ..runtime import ChatQueueManager, MessageDeduplicator, is_sender_allowed, try_pair_sender
from ..tls import create_aiohttp_session
from .base import Connector

logger = logging.getLogger(__name__)

try:
    import lark_oapi as lark

    _LARK_AVAILABLE = True
except Exception:
    lark = None  # type: ignore[assignment]
    _LARK_AVAILABLE = False


class FeishuConnector(Connector):
    def __init__(self, binding: PortalChannelBinding):
        super().__init__(binding)
        self._ws_client: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._tenant_token: Optional[str] = None
        self._tenant_token_expire_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._ws_task: Optional[asyncio.Task] = None
        self._dedup = MessageDeduplicator()
        self._queues = ChatQueueManager()
        self._mode = str(binding.config.get("mode") or "ws").strip().lower()
        self._image_re = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")

    @staticmethod
    def _extract_sender_id(sender: Dict[str, Any]) -> str:
        if not isinstance(sender, dict):
            return ""
        sender_id = sender.get("sender_id")
        if not isinstance(sender_id, dict):
            return ""
        for key in ("open_id", "user_id", "union_id"):
            value = str(sender_id.get(key) or "").strip()
            if value:
                return value
        return ""

    async def run(self) -> None:
        if not _LARK_AVAILABLE:
            raise RuntimeError("lark-oapi not installed")
        assert lark is not None
        lark_mod = cast(Any, lark)

        app_id = str(self.binding.config.get("app_id") or "").strip()
        app_secret = str(self.binding.config.get("app_secret") or "").strip()
        domain = str(self.binding.config.get("domain") or "https://open.feishu.cn").strip()
        if not app_id or not app_secret:
            raise RuntimeError("missing feishu app_id/app_secret")

        self._loop = asyncio.get_running_loop()
        self._http = create_aiohttp_session(self.binding.config)
        self._tenant_token = None
        self._tenant_token_expire_at = 0.0
        logger.info(
            "[%s/%s] connector run start: mode=%s app_id=%s domain=%s",
            self.binding.portal_id,
            self.binding.channel,
            self._mode,
            app_id,
            domain,
        )

        def on_message(data: Any) -> None:
            try:
                raw = lark_mod.JSON.marshal(data)
                payload = json.loads(raw)
            except Exception:
                logger.warning("[%s/%s] invalid event payload", self.binding.portal_id, self.binding.channel)
                return
            header = payload.get("header") or {}
            logger.info(
                "[%s/%s] ws on_message: payload_keys=%s event_type=%s",
                self.binding.portal_id,
                self.binding.channel,
                ",".join(sorted(payload.keys())),
                str(header.get("event_type") or ""),
            )
            if self._loop is None:
                logger.warning("[%s/%s] event loop not ready, dropping event", self.binding.portal_id, self.binding.channel)
                return
            asyncio.run_coroutine_threadsafe(self._on_event(app_id, app_secret, domain, payload), self._loop)

        try:
            await self._ensure_tenant_token(app_id, app_secret, domain)
            self.mark_success()
            if self._mode == "webhook":
                logger.info("[%s/%s] webhook mode active", self.binding.portal_id, self.binding.channel)
                while self._running:
                    await asyncio.sleep(1)
            else:
                def _ws_worker() -> None:
                    import lark_oapi.ws.client as ws_client_module  # type: ignore[import-not-found]

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    ws_client_module.loop = loop

                    original_connect = ws_client_module.websockets.connect

                    async def _connect_wrapper(*args: Any, **kwargs: Any) -> Any:
                        return await original_connect(*args, **kwargs)

                    ws_client_module.websockets.connect = _connect_wrapper
                    try:
                        logger.info("[%s/%s] ws worker starting", self.binding.portal_id, self.binding.channel)
                        event_handler = lark_mod.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_message).build()
                        self._ws_client = lark_mod.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=lark_mod.LogLevel.ERROR, domain=domain)
                        self._ws_client.start()
                        logger.warning("[%s/%s] ws client.start() returned unexpectedly", self.binding.portal_id, self.binding.channel)
                    except Exception as e:
                        logger.exception("[%s/%s] ws worker crashed: %s", self.binding.portal_id, self.binding.channel, str(e))
                        raise
                    finally:
                        ws_client_module.websockets.connect = original_connect
                        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                        for task in pending:
                            task.cancel()
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        try:
                            loop.stop()
                        except Exception:
                            pass
                        try:
                            loop.close()
                        except Exception:
                            pass

                self._ws_task = asyncio.create_task(asyncio.to_thread(_ws_worker))
                while self._running and self._ws_task and not self._ws_task.done():
                    await asyncio.sleep(1)
                if self._ws_task and self._ws_task.done():
                    exc = self._ws_task.exception()
                    if exc:
                        logger.error("[%s/%s] ws task done with exception: %s", self.binding.portal_id, self.binding.channel, str(exc))
                        raise exc
        finally:
            try:
                if self._ws_task and not self._ws_task.done():
                    stop_fn = getattr(self._ws_client, "stop", None)
                    if callable(stop_fn):
                        stop_fn()
            except Exception:
                pass
            if self._ws_task:
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except Exception:
                    pass
                self._ws_task = None
            if self._http:
                await self._http.close()
                self._http = None
            self._ws_client = None

    async def stop(self) -> None:
        await super().stop()
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except Exception:
                pass
            self._ws_task = None
        if self._http:
            await self._http.close()
            self._http = None
        self._ws_client = None

    async def handle_webhook(self, app_id: str, app_secret: str, domain: str, payload: Dict[str, Any], headers: Dict[str, str], raw_body: bytes) -> Dict[str, Any]:
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        verification_token = str(self.binding.config.get("verification_token") or "").strip()
        if verification_token:
            header = payload.get("header") or {}
            incoming_token = str(header.get("token") or payload.get("token") or "")
            if not incoming_token or not hmac.compare_digest(incoming_token, verification_token):
                return {"code": 401, "msg": "invalid verification token"}
        encrypt_key = str(self.binding.config.get("encrypt_key") or "").strip()
        if encrypt_key and not self._is_webhook_signature_valid(headers, raw_body, encrypt_key):
            return {"code": 401, "msg": "invalid signature"}
        if payload.get("encrypt"):
            return {"code": 400, "msg": "encrypted payload not supported"}
        if not self._http:
            self._http = create_aiohttp_session(self.binding.config)
        await self._ensure_tenant_token(app_id, app_secret, domain)
        await self._on_event(app_id, app_secret, domain, payload)
        return {"code": 0, "msg": "ok"}

    def _is_webhook_signature_valid(self, headers: Dict[str, str], body_bytes: bytes, encrypt_key: str) -> bool:
        timestamp = str(headers.get("x-lark-request-timestamp", "") or headers.get("X-Lark-Request-Timestamp", "") or "")
        nonce = str(headers.get("x-lark-request-nonce", "") or headers.get("X-Lark-Request-Nonce", "") or "")
        signature = str(headers.get("x-lark-signature", "") or headers.get("X-Lark-Signature", "") or "")
        if not timestamp or not nonce or not signature:
            return False
        try:
            body_str = body_bytes.decode("utf-8", errors="replace")
            content = f"{timestamp}{nonce}{encrypt_key}{body_str}"
            computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return hmac.compare_digest(computed, signature)
        except Exception:
            return False

    async def _on_event(self, app_id: str, app_secret: str, domain: str, payload: Dict[str, Any]) -> None:
        header = payload.get("header") or {}
        event_type = str(header.get("event_type") or "")
        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}
        sender_id = self._extract_sender_id(sender)
        logger.info(
            "[%s/%s] feishu event received: event_type=%s message_type=%s chat_id=%s sender_id_present=%s",
            self.binding.portal_id,
            self.binding.channel,
            event_type or "<empty>",
            str(message.get("message_type") or ""),
            str(message.get("chat_id") or ""),
            bool(sender_id),
        )
        if event_type and event_type != "im.message.receive_v1":
            logger.info(
                "[%s/%s] ignore event: unsupported event_type=%s",
                self.binding.portal_id,
                self.binding.channel,
                event_type,
            )
            return
        chat_id = str(message.get("chat_id") or "")
        if not chat_id:
            logger.warning("[%s/%s] drop event without chat_id", self.binding.portal_id, self.binding.channel)
            return
        message_id = str(message.get("message_id") or "")
        if message_id and self._dedup.seen(message_id):
            return

        msg_type = str(message.get("message_type") or "")
        content_raw = str(message.get("content") or "")
        try:
            content = json.loads(content_raw) if content_raw else {}
        except Exception:
            content = {}

        text = ""
        if msg_type == "text":
            text = str(content.get("text") or "").strip()
        elif msg_type == "image":
            image_key = str(content.get("image_key") or "").strip()
            if image_key:
                try:
                    raw = await self._download_image(domain, app_id, app_secret, image_key)
                    path = save_bytes(portal_id=self.binding.portal_id, channel="feishu", data=raw, suffix=".jpg", hint="image")
                    text = f"[图片] {path}"
                except Exception:
                    text = "[图片]"
        else:
            text = f"[{msg_type}]"

        text = text.strip()
        if not text:
            logger.info("[%s/%s] drop empty message: chat_id=%s", self.binding.portal_id, self.binding.channel, chat_id)
            return
        if not sender_id:
            logger.warning(
                "[%s/%s] drop message without sender_id(open_id/user_id/union_id): chat_id=%s message_id=%s",
                self.binding.portal_id,
                self.binding.channel,
                chat_id,
                message_id,
            )
            return

        if not is_sender_allowed(self.binding.config, sender_id):
            pairing_code = str(self.binding.config.get("pairing_code") or "")
            pairing_expires_at = self.binding.config.get("pairing_expires_at")
            text_norm = re.sub(r"[^A-Z0-9]", "", text.upper())
            code_norm = re.sub(r"[^A-Z0-9]", "", pairing_code.upper())
            logger.warning(
                "[%s/%s] pairing check: sender_id=%s text=%r text_norm=%s code=%r code_norm=%s expires_at=%s now=%s",
                self.binding.portal_id,
                self.binding.channel,
                sender_id,
                text,
                text_norm,
                pairing_code,
                code_norm,
                pairing_expires_at,
                int(time.time()),
            )
            pairing = try_pair_sender(self.binding.config, sender_id, text)
            if pairing.paired:
                logger.info(
                    "[%s/%s] sender paired successfully: sender_id=%s",
                    self.binding.portal_id,
                    self.binding.channel,
                    sender_id,
                )
                await self._send_text(app_id, app_secret, domain, chat_id, "已配对成功，可以开始对话。")
            else:
                logger.warning(
                    "[%s/%s] sender rejected: sender_id=%s reason=%s",
                    self.binding.portal_id,
                    self.binding.channel,
                    sender_id,
                    pairing.reason,
                )
                await self._send_text(app_id, app_secret, domain, chat_id, "未授权。请发送配对码完成绑定。")
            return

        portal_mgr = get_portal_manager()
        svc = await portal_mgr.get_service(self.binding.portal_id)
        if not svc:
            await self._send_text(app_id, app_secret, domain, chat_id, "Portal not found")
            return

        await self._queues.enqueue(
            chat_id,
            lambda: self._handle_text(app_id, app_secret, domain, chat_id, sender_id, message_id, text),
        )

    async def _handle_text(
        self,
        app_id: str,
        app_secret: str,
        domain: str,
        chat_id: str,
        sender_id: str,
        message_id: str,
        text: str,
    ) -> None:
        portal_mgr = get_portal_manager()
        svc = await portal_mgr.get_service(self.binding.portal_id)
        if not svc:
            await self._send_text(app_id, app_secret, domain, chat_id, "Portal not found")
            return
        typing_reaction_id: Optional[str] = None
        if message_id:
            typing_reaction_id = await self._add_typing_indicator(app_id, app_secret, domain, message_id)
        session_id = f"feishu:{self.binding.portal_id}:{chat_id}"
        reply = ""
        try:
            async for ev in svc.chat(session_id=session_id, user_message=text, user_id=sender_id or "default", stream=False):
                if ev.delta:
                    reply += ev.delta
            reply = reply.strip() or "…"
            img_url = ""
            m = self._image_re.search(reply)
            if m:
                img_url = m.group(1)
            if img_url:
                try:
                    image_key = await self._upload_image(domain, app_id, app_secret, img_url)
                    await self._send_image(app_id, app_secret, domain, chat_id, image_key)
                    cleaned = self._image_re.sub("", reply).strip()
                    if cleaned:
                        await self._send_text(app_id, app_secret, domain, chat_id, cleaned[:4000])
                    return
                except Exception as e:
                    logger.warning("[%s/%s] feishu send image failed: %s", self.binding.portal_id, self.binding.channel, str(e))
            await self._send_text(app_id, app_secret, domain, chat_id, reply[:4000])
        finally:
            if message_id and typing_reaction_id:
                await self._remove_typing_indicator(app_id, app_secret, domain, message_id, typing_reaction_id)

    async def _download_image(self, domain: str, app_id: str, app_secret: str, image_key: str) -> bytes:
        token = await self._ensure_tenant_token(app_id, app_secret, domain)
        if not self._http:
            raise RuntimeError("http client not ready")
        url = f"{domain.rstrip('/')}/open-apis/im/v1/images/{image_key}"
        async with self._http.get(url, headers={"Authorization": f"Bearer {token}"}) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"download image HTTP {resp.status}")
            return await resp.read()

    async def _upload_image(self, domain: str, app_id: str, app_secret: str, img_url: str) -> str:
        token = await self._ensure_tenant_token(app_id, app_secret, domain)
        if not self._http:
            raise RuntimeError("http client not ready")
        async with self._http.get(img_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            raw = await resp.read()
        form = aiohttp.FormData()
        form.add_field("image_type", "message")
        form.add_field("image", raw, filename="image.jpg", content_type="image/jpeg")
        url = f"{domain.rstrip('/')}/open-apis/im/v1/images"
        async with self._http.post(url, data=form, headers={"Authorization": f"Bearer {token}"}) as resp:
            data = await resp.json()
        image_key = str(((data.get("data") or {}).get("image_key")) or "")
        if not image_key:
            raise RuntimeError("upload image failed")
        return image_key

    async def _send_image(self, app_id: str, app_secret: str, domain: str, chat_id: str, image_key: str) -> None:
        token = await self._ensure_tenant_token(app_id, app_secret, domain)
        if not self._http:
            return
        url = f"{domain.rstrip('/')}/open-apis/im/v1/messages?receive_id_type=chat_id"
        body = {"receive_id": chat_id, "msg_type": "image", "content": json.dumps({"image_key": image_key}, ensure_ascii=False)}
        async with self._http.post(url, json=body, headers={"Authorization": f"Bearer {token}"}) as resp:
            await resp.text()
        self.mark_success()

    async def _add_typing_indicator(
        self,
        app_id: str,
        app_secret: str,
        domain: str,
        message_id: str,
    ) -> Optional[str]:
        if not self._http:
            return None
        token = await self._ensure_tenant_token(app_id, app_secret, domain)
        url = f"{domain.rstrip('/')}/open-apis/im/v1/messages/{message_id}/reactions"
        body = {"reaction_type": {"emoji_type": "Typing"}}
        try:
            async with self._http.post(url, json=body, headers={"Authorization": f"Bearer {token}"}) as resp:
                raw = await resp.text()
                if resp.status >= 400:
                    logger.warning(
                        "[%s/%s] add typing indicator failed: status=%s body=%s",
                        self.binding.portal_id,
                        self.binding.channel,
                        resp.status,
                        raw[:200],
                    )
                    return None
                try:
                    data = json.loads(raw)
                except Exception:
                    return None
                reaction_id = str(((data.get("data") or {}).get("reaction_id")) or "")
                return reaction_id or None
        except Exception as e:
            logger.warning(
                "[%s/%s] add typing indicator exception: %s",
                self.binding.portal_id,
                self.binding.channel,
                str(e),
            )
            return None

    async def _remove_typing_indicator(
        self,
        app_id: str,
        app_secret: str,
        domain: str,
        message_id: str,
        reaction_id: str,
    ) -> None:
        if not self._http:
            return
        token = await self._ensure_tenant_token(app_id, app_secret, domain)
        url = f"{domain.rstrip('/')}/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}"
        try:
            async with self._http.delete(url, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status >= 400:
                    raw = await resp.text()
                    logger.warning(
                        "[%s/%s] remove typing indicator failed: status=%s body=%s",
                        self.binding.portal_id,
                        self.binding.channel,
                        resp.status,
                        raw[:200],
                    )
        except Exception as e:
            logger.warning(
                "[%s/%s] remove typing indicator exception: %s",
                self.binding.portal_id,
                self.binding.channel,
                str(e),
            )

    async def _ensure_tenant_token(self, app_id: str, app_secret: str, domain: str) -> str:
        now = time.time()
        if self._tenant_token and now < self._tenant_token_expire_at:
            return self._tenant_token
        async with self._token_lock:
            now = time.time()
            if self._tenant_token and now < self._tenant_token_expire_at:
                return self._tenant_token
            if not self._http:
                raise RuntimeError("http client not ready")
            url = f"{domain.rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal"
            async with self._http.post(url, json={"app_id": app_id, "app_secret": app_secret}) as resp:
                data = await resp.json()
            token = str(data.get("tenant_access_token") or "")
            if not token:
                raise RuntimeError("failed to get tenant_access_token")
            expires_in = int(data.get("expire") or data.get("expires_in") or 7200)
            self._tenant_token = token
            self._tenant_token_expire_at = time.time() + max(60, expires_in - 60)
            return token

    async def _send_text(self, app_id: str, app_secret: str, domain: str, chat_id: str, text: str) -> None:
        if not self._http:
            return
        url = f"{domain.rstrip('/')}/open-apis/im/v1/messages?receive_id_type=chat_id"
        body = {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
        logger.info(
            "[%s/%s] send_text: chat_id=%s text_len=%s",
            self.binding.portal_id,
            self.binding.channel,
            chat_id,
            len(text),
        )
        for _ in range(2):
            token = await self._ensure_tenant_token(app_id, app_secret, domain)
            async with self._http.post(url, json=body, headers={"Authorization": f"Bearer {token}"}) as resp:
                raw = await resp.text()
                if resp.status in (401, 403):
                    self._tenant_token = None
                    self._tenant_token_expire_at = 0.0
                    continue
                if resp.status >= 400:
                    self._last_error = f"feishu send HTTP {resp.status}"
                    logger.warning("[%s/%s] send failed: %s", self.binding.portal_id, self.binding.channel, raw[:200])
                else:
                    logger.info(
                        "[%s/%s] send_text ok: status=%s chat_id=%s",
                        self.binding.portal_id,
                        self.binding.channel,
                        resp.status,
                        chat_id,
                    )
                    self.mark_success()
                return
