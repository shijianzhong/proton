"""
Web tools: search and fetch web content.
"""

import logging
import os
import re
from typing import Any, List, Optional
from urllib.parse import urlparse, quote_plus

import aiohttp

from .base import SystemTool, ToolParameterSchema

logger = logging.getLogger(__name__)


# API keys from environment
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CX", "")  # Google Custom Search Engine ID


class WebSearchTool(SystemTool):
    """Search the web using Brave Search API or Google."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information. Returns a list of search results "
            "with titles, URLs, and snippets. Useful for finding current information, "
            "looking up facts, or researching topics."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="query",
                type="string",
                description="The search query",
                required=True,
            ),
            ToolParameterSchema(
                name="count",
                type="integer",
                description="Number of results to return (default: 5, max: 10)",
                required=False,
                default=5,
            ),
        ]

    @property
    def category(self) -> str:
        return "web"

    async def _search_brave(self, query: str, count: int) -> str:
        """Search using Brave Search API."""
        if not BRAVE_API_KEY:
            return "Error: BRAVE_API_KEY not configured"

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY,
        }
        params = {
            "q": query,
            "count": min(count, 10),
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return f"Error: Search API returned status {resp.status}"

                data = await resp.json()
                results = data.get("web", {}).get("results", [])

                if not results:
                    return "No results found"

                output = []
                for i, result in enumerate(results[:count], 1):
                    title = result.get("title", "No title")
                    url = result.get("url", "")
                    snippet = result.get("description", "No description")
                    output.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")

                return "\n\n".join(output)

    async def _search_google(self, query: str, count: int) -> str:
        """Search using Google Custom Search API."""
        if not GOOGLE_API_KEY or not GOOGLE_CX:
            return "Error: GOOGLE_API_KEY or GOOGLE_CX not configured"

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CX,
            "q": query,
            "num": min(count, 10),
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return f"Error: Search API returned status {resp.status}"

                data = await resp.json()
                results = data.get("items", [])

                if not results:
                    return "No results found"

                output = []
                for i, result in enumerate(results[:count], 1):
                    title = result.get("title", "No title")
                    url = result.get("link", "")
                    snippet = result.get("snippet", "No description")
                    output.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")

                return "\n\n".join(output)

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        count = kwargs.get("count", 5)

        if not query:
            return "Error: query is required"

        try:
            # Try Brave first, then Google
            if BRAVE_API_KEY:
                return await self._search_brave(query, count)
            elif GOOGLE_API_KEY and GOOGLE_CX:
                return await self._search_google(query, count)
            else:
                return (
                    "Error: No search API configured. "
                    "Please set BRAVE_API_KEY or (GOOGLE_API_KEY + GOOGLE_CX) environment variables."
                )
        except Exception as e:
            logger.error(f"Error performing web search: {e}")
            return f"Error performing search: {e}"


class WebFetchTool(SystemTool):
    """Fetch and extract content from a web page."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a web page and extract its main content as plain text. "
            "Useful for reading articles, documentation, or any web content. "
            "Removes navigation, ads, and other non-content elements."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="url",
                type="string",
                description="The URL of the web page to fetch",
                required=True,
            ),
            ToolParameterSchema(
                name="max_length",
                type="integer",
                description="Maximum length of extracted content (default: 10000)",
                required=False,
                default=10000,
            ),
        ]

    @property
    def category(self) -> str:
        return "web"

    def _extract_text(self, html: str, max_length: int) -> str:
        """Extract readable text from HTML."""
        # Try to use readability if available
        try:
            from readability import Document
            doc = Document(html)
            content = doc.summary()
            # Remove HTML tags from the summary
            text = re.sub(r'<[^>]+>', '', content)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_length]
        except ImportError:
            pass

        # Fallback: simple HTML tag removal
        # Remove script and style elements
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)

        # Decode HTML entities
        import html
        text = html.unescape(text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_length]

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        max_length = kwargs.get("max_length", 10000)

        if not url:
            return "Error: url is required"

        # Validate URL
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return "Error: URL must start with http:// or https://"
        except Exception:
            return "Error: Invalid URL format"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ProtonBot/1.0; +https://proton.ai)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return f"Error: HTTP {resp.status} - {resp.reason}"

                    content_type = resp.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return f"Error: URL does not return HTML content (got {content_type})"

                    html = await resp.text()
                    text = self._extract_text(html, max_length)

                    if not text:
                        return "Error: Could not extract content from page"

                    # Add source info
                    return f"Content from {url}:\n\n{text}"

        except aiohttp.ClientTimeout:
            return "Error: Request timed out"
        except Exception as e:
            logger.error(f"Error fetching URL: {e}")
            return f"Error fetching URL: {e}"


class WebDownloadTool(SystemTool):
    """Download a file from a URL."""

    @property
    def name(self) -> str:
        return "web_download"

    @property
    def description(self) -> str:
        return (
            "Download a file from a URL and save it to the workspace. "
            "Useful for downloading images, documents, or other files."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="url",
                type="string",
                description="The URL of the file to download",
                required=True,
            ),
            ToolParameterSchema(
                name="filename",
                type="string",
                description="Filename to save as (in workspace). If not provided, uses URL filename.",
                required=False,
            ),
        ]

    @property
    def category(self) -> str:
        return "web"

    @property
    def requires_approval(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        filename = kwargs.get("filename", "")

        if not url:
            return "Error: url is required"

        # Derive filename from URL if not provided
        if not filename:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "downloaded_file"

        # Security: ensure filename is safe
        filename = re.sub(r'[^\w\-_\.]', '_', filename)

        # Get workspace path
        workspace = os.path.expanduser(os.environ.get("PROTON_WORKSPACE", "~/.proton/workspace"))
        os.makedirs(workspace, exist_ok=True)
        filepath = os.path.join(workspace, filename)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ProtonBot/1.0)",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=120) as resp:
                    if resp.status != 200:
                        return f"Error: HTTP {resp.status} - {resp.reason}"

                    # Get content length if available
                    content_length = resp.headers.get("Content-Length", "unknown")

                    # Download and save
                    with open(filepath, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)

                    file_size = os.path.getsize(filepath)
                    return f"Downloaded {url} to {filename} ({file_size} bytes)"

        except aiohttp.ClientTimeout:
            return "Error: Download timed out"
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return f"Error downloading file: {e}"
