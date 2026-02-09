"""
Email tools: send emails via SMTP or API services.

## Method 1: Resend API (Recommended for custom domains)
Best for Cloudflare domains or any custom domain.
- RESEND_API_KEY: Your Resend API key (get from resend.com)
- RESEND_FROM: Sender email (e.g., noreply@yourdomain.com)

Setup steps:
1. Create account at https://resend.com
2. Add your domain and verify DNS records (works with Cloudflare)
3. Generate API key
4. Set environment variables

## Method 2: SMTP (Traditional)
- SMTP_HOST: SMTP server hostname (default: smtp.gmail.com)
- SMTP_PORT: SMTP server port (default: 587)
- SMTP_USER: SMTP username/email address
- SMTP_PASSWORD: SMTP password or app-specific password
- SMTP_FROM: Default sender email (defaults to SMTP_USER)
- SMTP_USE_TLS: Whether to use TLS (default: true)

Common SMTP providers:
- Gmail: smtp.gmail.com:587 (use App Password)
- QQ Mail: smtp.qq.com:587 (use authorization code)
- 163 Mail: smtp.163.com:465 (SSL)
- Outlook: smtp-mail.outlook.com:587
- Aliyun: smtp.aliyun.com:465 (SSL)
"""

import logging
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional

from .base import SystemTool, ToolParameterSchema

logger = logging.getLogger(__name__)


# ===== Resend API Configuration =====
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "")

# ===== SMTP Configuration =====
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "") or SMTP_USER
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")


def _is_resend_configured() -> bool:
    """Check if Resend API is configured."""
    return bool(RESEND_API_KEY and RESEND_FROM)


def _is_smtp_configured() -> bool:
    """Check if SMTP is configured."""
    return bool(SMTP_USER and SMTP_PASSWORD)


def _is_email_configured() -> bool:
    """Check if any email sending method is configured."""
    return _is_resend_configured() or _is_smtp_configured()


def _get_email_method() -> str:
    """Get the configured email method."""
    if _is_resend_configured():
        return "resend"
    elif _is_smtp_configured():
        return "smtp"
    return "none"


class EmailConfig:
    """
    Runtime email configuration that can be updated via API.
    Uses singleton pattern with database persistence.
    """
    _instance: Optional["EmailConfig"] = None
    _initialized: bool = False

    def __init__(self):
        # Resend config
        self.resend_api_key = RESEND_API_KEY
        self.resend_from = RESEND_FROM

        # SMTP config
        self.smtp_host = SMTP_HOST
        self.smtp_port = SMTP_PORT
        self.smtp_user = SMTP_USER
        self.smtp_password = SMTP_PASSWORD
        self.smtp_from = SMTP_FROM
        self.smtp_use_tls = SMTP_USE_TLS

        # Preferred method (auto-detect or manual)
        self.preferred_method = "auto"  # "auto", "resend", "smtp"

    @classmethod
    async def initialize_from_storage(cls) -> "EmailConfig":
        """Initialize configuration from database, fallback to environment variables."""
        instance = cls.get_instance()

        if cls._initialized:
            return instance

        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            # Load from database
            saved_config = await storage.load_config("email")

            if saved_config:
                logger.info("Loading email config from database")
                instance.resend_api_key = saved_config.get("resend_api_key", instance.resend_api_key)
                instance.resend_from = saved_config.get("resend_from", instance.resend_from)
                instance.smtp_host = saved_config.get("smtp_host", instance.smtp_host)
                instance.smtp_port = saved_config.get("smtp_port", instance.smtp_port)
                instance.smtp_user = saved_config.get("smtp_user", instance.smtp_user)
                instance.smtp_password = saved_config.get("smtp_password", instance.smtp_password)
                instance.smtp_from = saved_config.get("smtp_from", instance.smtp_from)
                instance.smtp_use_tls = saved_config.get("smtp_use_tls", instance.smtp_use_tls)
                instance.preferred_method = saved_config.get("preferred_method", instance.preferred_method)
            else:
                logger.info("No saved email config found, using environment variables")
        except Exception as e:
            logger.warning(f"Failed to load email config from storage: {e}, using environment variables")

        cls._initialized = True
        return instance

    @classmethod
    def get_instance(cls) -> "EmailConfig":
        if cls._instance is None:
            cls._instance = EmailConfig()
        return cls._instance

    async def save_to_storage(self) -> None:
        """Save current configuration to database."""
        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            config_data = {
                "resend_api_key": self.resend_api_key,
                "resend_from": self.resend_from,
                "smtp_host": self.smtp_host,
                "smtp_port": self.smtp_port,
                "smtp_user": self.smtp_user,
                "smtp_password": self.smtp_password,
                "smtp_from": self.smtp_from,
                "smtp_use_tls": self.smtp_use_tls,
                "preferred_method": self.preferred_method,
            }

            await storage.save_config("email", config_data)
            logger.info("Email config saved to database")
        except Exception as e:
            logger.error(f"Failed to save email config to storage: {e}")

    async def update(
        self,
        resend_api_key: Optional[str] = None,
        resend_from: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        smtp_from: Optional[str] = None,
        smtp_use_tls: Optional[bool] = None,
        preferred_method: Optional[str] = None,
    ) -> None:
        """Update email configuration and save to database."""
        if resend_api_key is not None:
            self.resend_api_key = resend_api_key
        if resend_from is not None:
            self.resend_from = resend_from
        if smtp_host is not None:
            self.smtp_host = smtp_host
        if smtp_port is not None:
            self.smtp_port = smtp_port
        if smtp_user is not None:
            self.smtp_user = smtp_user
        if smtp_password is not None:
            self.smtp_password = smtp_password
        if smtp_from is not None:
            self.smtp_from = smtp_from
        if smtp_use_tls is not None:
            self.smtp_use_tls = smtp_use_tls
        if preferred_method is not None:
            self.preferred_method = preferred_method

        # Save to database after update
        await self.save_to_storage()

    def is_resend_configured(self) -> bool:
        return bool(self.resend_api_key and self.resend_from)

    def is_smtp_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password)

    def is_configured(self) -> bool:
        return self.is_resend_configured() or self.is_smtp_configured()

    def get_method(self) -> str:
        """Get the active email method."""
        if self.preferred_method == "resend" and self.is_resend_configured():
            return "resend"
        elif self.preferred_method == "smtp" and self.is_smtp_configured():
            return "smtp"
        elif self.preferred_method == "auto":
            if self.is_resend_configured():
                return "resend"
            elif self.is_smtp_configured():
                return "smtp"
        return "none"

    def to_dict(self) -> Dict[str, Any]:
        """Get current configuration (masks sensitive data)."""
        def mask_key(key: str) -> str:
            if not key:
                return ""
            if len(key) <= 8:
                return "*" * len(key)
            return key[:4] + "****" + key[-4:]

        return {
            "preferred_method": self.preferred_method,
            "active_method": self.get_method(),
            "resend": {
                "configured": self.is_resend_configured(),
                "api_key_preview": mask_key(self.resend_api_key),
                "from": self.resend_from,
            },
            "smtp": {
                "configured": self.is_smtp_configured(),
                "host": self.smtp_host,
                "port": self.smtp_port,
                "user": self.smtp_user,
                "password_preview": mask_key(self.smtp_password),
                "from": self.smtp_from or self.smtp_user,
                "use_tls": self.smtp_use_tls,
            },
        }


def get_email_config() -> EmailConfig:
    """Get the global email config instance."""
    return EmailConfig.get_instance()


async def _send_via_resend(
    config: EmailConfig,
    to: List[str],
    subject: str,
    body: str,
    html: bool = False,
    cc: Optional[List[str]] = None,
) -> str:
    """Send email via Resend API."""
    import aiohttp

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {config.resend_api_key}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "from": config.resend_from,
        "to": to,
        "subject": subject,
    }

    if html:
        payload["html"] = body
    else:
        payload["text"] = body

    if cc:
        payload["cc"] = cc

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            result = await response.json()

            if response.status == 200:
                return (
                    f"✅ 邮件发送成功 (Resend)\n"
                    f"收件人: {', '.join(to)}\n"
                    f"主题: {subject}\n"
                    f"ID: {result.get('id', 'N/A')}\n"
                    f"---\n"
                    f"Email sent successfully via Resend."
                )
            else:
                error_msg = result.get("message", result.get("error", str(result)))
                return f"❌ Resend 发送失败: {error_msg} | Error sending via Resend: {error_msg}"


async def _send_via_smtp(
    config: EmailConfig,
    to: List[str],
    subject: str,
    body: str,
    html: bool = False,
    cc: Optional[List[str]] = None,
) -> str:
    """Send email via SMTP."""
    import aiosmtplib

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.smtp_from or config.smtp_user
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)

    # Add body
    if html:
        msg.attach(MIMEText(body, "html", "utf-8"))
    else:
        msg.attach(MIMEText(body, "plain", "utf-8"))

    # Send email
    all_recipients = to + (cc or [])

    try:
        import ssl
        import os
        
        # Create SSL context - only disable verification in development
        ssl_context = None
        if os.environ.get("FLASK_ENV") == "development" or os.environ.get("DEBUG") == "True":
            # Create SSL context with certificate verification disabled for development
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        if config.smtp_use_tls:
            # Use STARTTLS
            await aiosmtplib.send(
                msg,
                hostname=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user,
                password=config.smtp_password,
                start_tls=True,
                recipients=all_recipients,
                tls_context=ssl_context,
            )
        else:
            # Use SSL (for ports like 465)
            await aiosmtplib.send(
                msg,
                hostname=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user,
                password=config.smtp_password,
                use_tls=True,
                recipients=all_recipients,
                tls_context=ssl_context,
            )

        recipient_info = f"收件人: {', '.join(to)}"
        if cc:
            recipient_info += f" (抄送: {', '.join(cc)})"

        return (
            f"✅ 邮件发送成功 (SMTP)\n"
            f"{recipient_info}\n"
            f"主题: {subject}\n"
            f"---\n"
            f"Email sent successfully via SMTP."
        )

    except Exception as e:
        if "SMTPAuthenticationError" in str(type(e).__name__):
            return (
                f"❌ SMTP 认证失败。请检查:\n"
                f"  - SMTP_USER 和 SMTP_PASSWORD 是否正确\n"
                f"  - Gmail 请使用应用专用密码（非普通密码）\n"
                f"  - QQ/163 邮箱请使用授权码\n"
                f"详情: {e}\n"
                f"---\n"
                f"SMTP authentication failed."
            )
        elif "SMTPConnectError" in str(type(e).__name__):
            return (
                f"❌ 无法连接到 SMTP 服务器 {config.smtp_host}:{config.smtp_port}\n"
                f"请检查 SMTP_HOST 和 SMTP_PORT 设置。\n"
                f"详情: {e}\n"
                f"---\n"
                f"Could not connect to SMTP server."
            )
        else:
            return f"❌ SMTP 发送失败: {e} | Error sending via SMTP: {e}"


class SendEmailTool(SystemTool):
    """Send an email via Resend API or SMTP. 通过 Resend API 或 SMTP 发送邮件。"""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        config = get_email_config()
        method = config.get_method()
        if method == "resend":
            status = f"已配置 (Resend API, 发件人: {config.resend_from})"
        elif method == "smtp":
            status = f"已配置 (SMTP via {config.smtp_host})"
        else:
            status = "未配置"
        return (
            f"发送邮件给一个或多个收件人。当前状态: {status}。"
            f"支持纯文本和 HTML 格式，可添加抄送。"
            f"需要配置 Resend API 或 SMTP。"
            f" | Send email to recipients. Currently {status}. "
            "Supports plain text and HTML. Requires Resend API or SMTP config."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="to",
                type="string",
                description="Recipient email address(es), comma-separated for multiple",
                required=True,
            ),
            ToolParameterSchema(
                name="subject",
                type="string",
                description="Email subject line",
                required=True,
            ),
            ToolParameterSchema(
                name="body",
                type="string",
                description="Email body content",
                required=True,
            ),
            ToolParameterSchema(
                name="html",
                type="boolean",
                description="Whether the body is HTML content (default: false, plain text)",
                required=False,
                default=False,
            ),
            ToolParameterSchema(
                name="cc",
                type="string",
                description="CC recipient email address(es), comma-separated for multiple",
                required=False,
            ),
        ]

    @property
    def category(self) -> str:
        return "communication"

    @property
    def requires_approval(self) -> bool:
        return True  # Sending email is a sensitive operation

    async def execute(self, **kwargs: Any) -> str:
        to = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")
        html = kwargs.get("html", False)
        cc = kwargs.get("cc", "")

        if not to:
            return "错误: 'to' (收件人邮箱) 为必填项 | Error: 'to' (recipient email) is required"
        if not subject:
            return "错误: 'subject' (邮件主题) 为必填项 | Error: 'subject' is required"
        if not body:
            return "错误: 'body' (邮件正文) 为必填项 | Error: 'body' is required"

        config = get_email_config()
        method = config.get_method()

        if method == "none":
            return (
                "错误: 邮件服务未配置。请选择以下方式之一:\n\n"
                "📧 **方式1: Resend API (推荐用于自定义域名)**\n"
                "适合 Cloudflare 域名。设置:\n"
                "  - RESEND_API_KEY: 你的 Resend API Key\n"
                "  - RESEND_FROM: 发件人地址 (如 noreply@yourdomain.com)\n"
                "配置步骤: https://resend.com → 添加域名 → 验证 DNS → 获取 API Key\n\n"
                "📬 **方式2: SMTP**\n"
                "用于传统邮箱。设置:\n"
                "  - SMTP_USER: 你的邮箱地址\n"
                "  - SMTP_PASSWORD: 密码或授权码\n"
                "  - SMTP_HOST: SMTP 服务器 (默认: smtp.gmail.com)\n"
                "  - SMTP_PORT: 端口 (默认: 587)\n\n"
                "或在设置面板中配置。\n\n"
                "---\n"
                "Error: Email not configured. Choose one method:\n"
                "Method 1: Resend API - Set RESEND_API_KEY and RESEND_FROM\n"
                "Method 2: SMTP - Set SMTP_USER and SMTP_PASSWORD"
            )

        # Parse recipients
        to_list = [addr.strip() for addr in to.split(",") if addr.strip()]
        cc_list = [addr.strip() for addr in cc.split(",") if addr.strip()] if cc else None

        try:
            if method == "resend":
                return await _send_via_resend(config, to_list, subject, body, html, cc_list)
            else:
                return await _send_via_smtp(config, to_list, subject, body, html, cc_list)
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return f"Error sending email: {e}"


class CheckEmailConfigTool(SystemTool):
    """Check if email sending is configured. 检查邮件发送是否已配置。"""

    @property
    def name(self) -> str:
        return "check_email_config"

    @property
    def description(self) -> str:
        return (
            "检查邮件发送是否已正确配置，返回配置状态和配置指引。"
            " | Check if email sending is properly configured."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return []

    @property
    def category(self) -> str:
        return "communication"

    async def execute(self, **kwargs: Any) -> str:
        config = get_email_config()
        method = config.get_method()

        if method == "resend":
            return (
                f"✅ 邮件已配置 (Resend API):\n"
                f"  - 发件人: {config.resend_from}\n"
                f"  - API Key: {config.resend_api_key[:8]}...{config.resend_api_key[-4:]}\n\n"
                f"Resend 推荐用于自定义域名（如 Cloudflare 域名）。\n"
                f"---\n"
                f"Email configured via Resend API."
            )
        elif method == "smtp":
            masked_password = config.smtp_password[:2] + "****" + config.smtp_password[-2:] if len(config.smtp_password) > 4 else "****"
            return (
                f"✅ 邮件已配置 (SMTP):\n"
                f"  - 服务器: {config.smtp_host}\n"
                f"  - 端口: {config.smtp_port}\n"
                f"  - 用户: {config.smtp_user}\n"
                f"  - 密码: {masked_password}\n"
                f"  - 发件人: {config.smtp_from or config.smtp_user}\n"
                f"  - TLS: {config.smtp_use_tls}\n"
                f"---\n"
                f"Email configured via SMTP."
            )
        else:
            return (
                "❌ 邮件未配置。\n\n"
                "**方式1: Resend API (推荐用于自定义域名)**\n"
                "适合 Cloudflare 域名。步骤:\n"
                "1. 在 https://resend.com 注册\n"
                "2. 添加域名并配置 DNS 记录\n"
                "3. 生成 API Key\n"
                "4. 设置环境变量:\n"
                "   - RESEND_API_KEY=re_xxxxx\n"
                "   - RESEND_FROM=noreply@yourdomain.com\n\n"
                "**方式2: SMTP**\n"
                "用于 Gmail、QQ邮箱、163邮箱等。设置:\n"
                "  - SMTP_USER: 邮箱地址\n"
                "  - SMTP_PASSWORD: 密码或授权码\n"
                "  - SMTP_HOST: SMTP 服务器 (默认: smtp.gmail.com)\n"
                "  - SMTP_PORT: 端口 (默认: 587)\n\n"
                "常用 SMTP 配置:\n"
                "  Gmail: smtp.gmail.com:587 (使用应用专用密码)\n"
                "  QQ邮箱: smtp.qq.com:587 (使用授权码)\n"
                "  163邮箱: smtp.163.com:465 (SSL, 设置 SMTP_USE_TLS=false)\n"
                "  Outlook: smtp-mail.outlook.com:587\n"
                "---\n"
                "Email is NOT configured."
            )
