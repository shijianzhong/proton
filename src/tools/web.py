"""
Web tools: search and fetch web content.

Supported Search Providers (in order of priority):
1. SearXNG - Free, self-hosted meta-search engine (recommended for China users)
2. Serper - Google Search API (paid, requires API key)
3. Brave Search - High quality results (requires API key)
4. Bing Search - Free tier available, works in China
5. Google Custom Search - Requires API key
6. DuckDuckGo - Free fallback, may be slow

Configuration via environment variables:
- SEARCH_PROVIDER: Preferred provider (searxng/serper/brave/bing/google/duckduckgo)
- SEARXNG_BASE_URL: SearXNG instance URL (e.g., http://localhost:8080)
- SERPER_API_KEY: Serper.dev API key
- BRAVE_API_KEY: Brave Search API key
- BING_API_KEY: Bing Search API key
- GOOGLE_API_KEY + GOOGLE_CX: Google Custom Search credentials
"""

import logging
import os
import re
import json
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Dict
from urllib.parse import urlparse, quote_plus, unquote, parse_qs

import aiohttp

from .base import SystemTool, ToolParameterSchema

logger = logging.getLogger(__name__)


# ============== Configuration ==============

# Preferred search provider
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "").lower()

# SearXNG (free, self-hosted)
SEARXNG_BASE_URL = os.environ.get("SEARXNG_BASE_URL", "")

# Serper.dev (Google Search API)
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

# Brave Search
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

# Bing Search (works in China)
BING_API_KEY = os.environ.get("BING_API_KEY", "")

# Tavily Search
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# Google Custom Search
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CX", "")


# ============== Runtime Configuration ==============

class SearchConfig:
    """Runtime search configuration that can be updated via API with database persistence."""

    _instance = None
    _initialized = False

    def __init__(self):
        # Load from environment as defaults
        self.provider = SEARCH_PROVIDER or "bing"  # Default to Bing
        self.searxng_base_url = SEARXNG_BASE_URL
        self.serper_api_key = SERPER_API_KEY
        self.brave_api_key = BRAVE_API_KEY
        self.bing_api_key = BING_API_KEY
        self.tavily_api_key = TAVILY_API_KEY
        self.google_api_key = GOOGLE_API_KEY
        self.google_cx = GOOGLE_CX

    @classmethod
    def get_instance(cls) -> "SearchConfig":
        if cls._instance is None:
            cls._instance = SearchConfig()
        return cls._instance

    @classmethod
    async def initialize_from_storage(cls) -> "SearchConfig":
        """Initialize configuration from database, fallback to environment variables."""
        instance = cls.get_instance()

        if cls._initialized:
            return instance

        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            # Load from database
            saved_config = await storage.load_config("search")

            if saved_config:
                logger.info("Loading search config from database")
                instance.provider = saved_config.get("provider", instance.provider)
                instance.searxng_base_url = saved_config.get("searxng_base_url", instance.searxng_base_url)
                instance.serper_api_key = saved_config.get("serper_api_key", instance.serper_api_key)
                instance.brave_api_key = saved_config.get("brave_api_key", instance.brave_api_key)
                instance.bing_api_key = saved_config.get("bing_api_key", instance.bing_api_key)
                instance.tavily_api_key = saved_config.get("tavily_api_key", instance.tavily_api_key)
                instance.google_api_key = saved_config.get("google_api_key", instance.google_api_key)
                instance.google_cx = saved_config.get("google_cx", instance.google_cx)
            else:
                logger.info("No saved search config found, using environment variables")
        except Exception as e:
            logger.warning(f"Failed to load search config from storage: {e}, using environment variables")

        cls._initialized = True
        return instance

    async def update(
        self,
        provider: Optional[str] = None,
        searxng_base_url: Optional[str] = None,
        serper_api_key: Optional[str] = None,
        brave_api_key: Optional[str] = None,
        bing_api_key: Optional[str] = None,
        tavily_api_key: Optional[str] = None,
        google_api_key: Optional[str] = None,
        google_cx: Optional[str] = None,
    ) -> None:
        """Update search configuration and save to database."""
        if provider is not None:
            self.provider = provider.lower()
        if searxng_base_url is not None:
            self.searxng_base_url = searxng_base_url
        if serper_api_key is not None:
            self.serper_api_key = serper_api_key
        if brave_api_key is not None:
            self.brave_api_key = brave_api_key
        if bing_api_key is not None:
            self.bing_api_key = bing_api_key
        if tavily_api_key is not None:
            self.tavily_api_key = tavily_api_key
        if google_api_key is not None:
            self.google_api_key = google_api_key
        if google_cx is not None:
            self.google_cx = google_cx

        logger.info(f"Search config updated: provider={self.provider}")

        # Save to database after update
        await self.save_to_storage()

    async def save_to_storage(self) -> None:
        """Save current configuration to database."""
        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            config_data = {
                "provider": self.provider,
                "searxng_base_url": self.searxng_base_url,
                "serper_api_key": self.serper_api_key,
                "brave_api_key": self.brave_api_key,
                "bing_api_key": self.bing_api_key,
                "tavily_api_key": self.tavily_api_key,
                "google_api_key": self.google_api_key,
                "google_cx": self.google_cx,
            }

            await storage.save_config("search", config_data)
            logger.info("Search config saved to database")
        except Exception as e:
            logger.error(f"Failed to save search config to storage: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Get current configuration (masks API keys)."""
        return {
            "provider": self.provider,
            "searxng_base_url": self.searxng_base_url,
            "searxng_configured": bool(self.searxng_base_url),
            "serper_configured": bool(self.serper_api_key),
            "serper_api_key_preview": f"{self.serper_api_key[:8]}..." if self.serper_api_key and len(self.serper_api_key) > 8 else None,
            "brave_configured": bool(self.brave_api_key),
            "brave_api_key_preview": f"{self.brave_api_key[:8]}..." if self.brave_api_key and len(self.brave_api_key) > 8 else None,
            "bing_configured": bool(self.bing_api_key),
            "bing_api_key_preview": f"{self.bing_api_key[:8]}..." if self.bing_api_key and len(self.bing_api_key) > 8 else None,
            "tavily_configured": bool(self.tavily_api_key),
            "tavily_api_key_preview": f"{self.tavily_api_key[:8]}..." if self.tavily_api_key and len(self.tavily_api_key) > 8 else None,
            "google_configured": bool(self.google_api_key and self.google_cx),
            "available_providers": self.get_available_providers(),
        }

    def get_available_providers(self) -> List[Dict[str, Any]]:
        """Get list of all providers with their status."""
        return [
            {
                "id": "bing",
                "name": "Bing 搜索",
                "description": "微软必应搜索，中国可用，无需 API 密钥",
                "configured": True,  # Always available via scraping
                "requires_api_key": False,
                "china_accessible": True,
            },
            {
                "id": "searxng",
                "name": "SearXNG",
                "description": "开源元搜索引擎，需自建服务",
                "configured": bool(self.searxng_base_url),
                "requires_api_key": False,
                "requires_base_url": True,
                "china_accessible": True,
            },
            {
                "id": "serper",
                "name": "Serper (Google)",
                "description": "Google 搜索 API，高质量结果",
                "configured": bool(self.serper_api_key),
                "requires_api_key": True,
                "china_accessible": False,
            },
            {
                "id": "brave",
                "name": "Brave 搜索",
                "description": "隐私友好的搜索引擎",
                "configured": bool(self.brave_api_key),
                "requires_api_key": True,
                "china_accessible": False,
            },
            {
                "id": "tavily",
                "name": "Tavily Search",
                "description": "深度搜索与聚合（需 API Key）",
                "configured": bool(self.tavily_api_key),
                "requires_api_key": True,
                "china_accessible": True,
            },
            {
                "id": "google",
                "name": "Google 自定义搜索",
                "description": "Google Custom Search API",
                "configured": bool(self.google_api_key and self.google_cx),
                "requires_api_key": True,
                "china_accessible": False,
            },
            {
                "id": "duckduckgo",
                "name": "DuckDuckGo",
                "description": "免费搜索，隐私友好",
                "configured": True,  # Always available
                "requires_api_key": False,
                "china_accessible": False,  # May be blocked
            },
        ]


def get_search_config() -> SearchConfig:
    """Get the global search configuration instance."""
    return SearchConfig.get_instance()


# ============== Search Provider Implementations ==============

class SearchProvider(ABC):
    """Base class for search providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @abstractmethod
    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        """Perform search and return formatted results."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        pass


class SearXNGProvider(SearchProvider):
    """
    SearXNG - Free, self-hosted meta-search engine.

    Best for: Self-hosted deployments, China users, privacy-focused users.
    Setup: docker run -p 8080:8080 searxng/searxng
    """

    @property
    def name(self) -> str:
        return "SearXNG"

    def is_available(self) -> bool:
        config = get_search_config()
        return bool(config.searxng_base_url)

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        if not config.searxng_base_url:
            return "Error: SEARXNG_BASE_URL not configured"

        # Build SearXNG search URL
        base_url = config.searxng_base_url.rstrip("/")
        url = f"{base_url}/search"

        params = {
            "q": query,
            "format": "json",
            "language": locale,
            "categories": "general",
            # Use multiple engines for better results
            "engines": "google,bing,duckduckgo,brave",
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: SearXNG returned status {resp.status}"

                    data = await resp.json()
                    results = data.get("results", [])

                    if not results:
                        return "No results found"

                    output = []
                    for i, result in enumerate(results[:count], 1):
                        title = result.get("title", "No title")
                        result_url = result.get("url", "")
                        snippet = result.get("content", result.get("snippet", "No description"))
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)

        except aiohttp.ClientTimeout:
            return "Error: SearXNG request timed out"
        except Exception as e:
            logger.error(f"SearXNG search error: {e}")
            return f"Error: SearXNG search failed: {e}"


class SerperProvider(SearchProvider):
    """
    Serper.dev - Google Search API wrapper.

    Best for: High quality Google results, knowledge graphs.
    Pricing: Free tier available (2,500 queries/month).
    """

    @property
    def name(self) -> str:
        return "Serper"

    def is_available(self) -> bool:
        config = get_search_config()
        return bool(config.serper_api_key)

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        if not config.serper_api_key:
            return "Error: SERPER_API_KEY not configured"

        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": config.serper_api_key,
            "Content-Type": "application/json",
        }

        # Map locale to Google language code
        gl = "cn" if locale.startswith("zh") else locale.split("-")[0]
        hl = "zh-CN" if locale.startswith("zh") else locale

        payload = {
            "q": query,
            "num": count,
            "gl": gl,
            "hl": hl,
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return f"Error: Serper API returned status {resp.status}: {error_text}"

                    data = await resp.json()

                    output = []

                    # Add answer box if available
                    if "answerBox" in data:
                        answer = data["answerBox"]
                        if "answer" in answer:
                            output.append(f"Quick Answer: {answer['answer']}\n")
                        elif "snippet" in answer:
                            output.append(f"Quick Answer: {answer['snippet']}\n")

                    # Add organic results
                    results = data.get("organic", [])
                    if not results and not output:
                        return "No results found"

                    for i, result in enumerate(results[:count], 1):
                        title = result.get("title", "No title")
                        result_url = result.get("link", "")
                        snippet = result.get("snippet", "No description")
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)

        except aiohttp.ClientTimeout:
            return "Error: Serper request timed out"
        except Exception as e:
            logger.error(f"Serper search error: {e}")
            return f"Error: Serper search failed: {e}"


class BraveProvider(SearchProvider):
    """
    Brave Search API.

    Best for: High quality results, privacy-focused.
    Pricing: Free tier available (2,000 queries/month).
    """

    @property
    def name(self) -> str:
        return "Brave"

    def is_available(self) -> bool:
        config = get_search_config()
        return bool(config.brave_api_key)

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        if not config.brave_api_key:
            return "Error: BRAVE_API_KEY not configured"

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": config.brave_api_key,
        }
        params = {
            "q": query,
            "count": min(count, 10),
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: Brave API returned status {resp.status}"

                    data = await resp.json()
                    results = data.get("web", {}).get("results", [])

                    if not results:
                        return "No results found"

                    output = []
                    for i, result in enumerate(results[:count], 1):
                        title = result.get("title", "No title")
                        result_url = result.get("url", "")
                        snippet = result.get("description", "No description")
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)

        except Exception as e:
            logger.error(f"Brave search error: {e}")
            return f"Error: Brave search failed: {e}"


class BingProvider(SearchProvider):
    """
    Bing Search API.

    Best for: China users (accessible without VPN), good Chinese content.
    Pricing: Free tier available (1,000 queries/month).
    Note: Also works without API key using web scraping (slower but free).
    """

    @property
    def name(self) -> str:
        return "Bing"

    def is_available(self) -> bool:
        # Bing is always available (can fallback to web scraping)
        return True

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        # Try API first if configured
        if config.bing_api_key:
            result = await self._search_api(query, count, locale, config.bing_api_key)
            if not result.startswith("Error"):
                return result

        # Fallback to web scraping
        return await self._search_scrape(query, count, locale)

    async def _search_api(self, query: str, count: int, locale: str, api_key: str) -> str:
        """Search using Bing Web Search API."""
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
        }
        params = {
            "q": query,
            "count": count,
            "mkt": locale,
            "responseFilter": "Webpages",
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: Bing API returned status {resp.status}"

                    data = await resp.json()
                    results = data.get("webPages", {}).get("value", [])

                    if not results:
                        return "No results found"

                    output = []
                    for i, result in enumerate(results[:count], 1):
                        title = result.get("name", "No title")
                        result_url = result.get("url", "")
                        snippet = result.get("snippet", "No description")
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)

        except Exception as e:
            logger.error(f"Bing API search error: {e}")
            return f"Error: Bing API search failed: {e}"

    async def _search_scrape(self, query: str, count: int, locale: str) -> str:
        """Search by scraping Bing web interface (no API key needed)."""
        # Use cn.bing.com for Chinese users
        if locale.startswith("zh"):
            url = "https://cn.bing.com/search"
        else:
            url = "https://www.bing.com/search"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params = {
            "q": query,
            "count": count,
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: Bing returned status {resp.status}"

                    html = await resp.text()

                    # Parse results
                    results = []

                    # Extract result blocks
                    # Bing uses <li class="b_algo"> for each result
                    result_pattern = re.compile(
                        r'<li class="b_algo"[^>]*>.*?<h2><a[^>]+href="([^"]+)"[^>]*>(.+?)</a></h2>.*?<p[^>]*>(.+?)</p>',
                        re.DOTALL | re.IGNORECASE
                    )

                    matches = result_pattern.findall(html)

                    for i, (result_url, title, snippet) in enumerate(matches[:count], 1):
                        # Clean HTML tags
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                        results.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    if not results:
                        # Try alternative parsing
                        return await self._search_scrape_alt(html, count)

                    return "\n\n".join(results)

        except Exception as e:
            logger.error(f"Bing scrape error: {e}")
            return f"Error: Bing search failed: {e}"

    async def _search_scrape_alt(self, html: str, count: int) -> str:
        """Alternative parsing method for Bing results."""
        results = []

        # Try to find links with cite elements
        link_pattern = re.compile(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>',
            re.IGNORECASE
        )

        links = link_pattern.findall(html)
        seen_urls = set()

        for result_url, title in links:
            # Filter out Bing internal URLs and duplicates
            if "bing.com" in result_url or "microsoft.com" in result_url:
                continue
            if result_url in seen_urls:
                continue
            seen_urls.add(result_url)

            if len(results) >= count:
                break

            results.append(f"{len(results)+1}. {title.strip()}\n   URL: {result_url}")

        if not results:
            return "No results found"

        return "\n\n".join(results)


class GoogleProvider(SearchProvider):
    """
    Google Custom Search API.

    Best for: Comprehensive results.
    Pricing: 100 queries/day free, then $5 per 1,000 queries.
    Note: May not be accessible in China without VPN.
    """

    @property
    def name(self) -> str:
        return "Google"

    def is_available(self) -> bool:
        config = get_search_config()
        return bool(config.google_api_key and config.google_cx)

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        if not config.google_api_key or not config.google_cx:
            return "Error: GOOGLE_API_KEY or GOOGLE_CX not configured"

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": config.google_api_key,
            "cx": config.google_cx,
            "q": query,
            "num": min(count, 10),
            "lr": f"lang_{locale.split('-')[0]}",
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: Google API returned status {resp.status}"

                    data = await resp.json()
                    results = data.get("items", [])

                    if not results:
                        return "No results found"

                    output = []
                    for i, result in enumerate(results[:count], 1):
                        title = result.get("title", "No title")
                        result_url = result.get("link", "")
                        snippet = result.get("snippet", "No description")
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)

        except Exception as e:
            logger.error(f"Google search error: {e}")
            return f"Error: Google search failed: {e}"


class DuckDuckGoProvider(SearchProvider):
    """
    DuckDuckGo - Free search with no API key.

    Best for: Free fallback, privacy-focused.
    Note: Uses web scraping, may be slower and less reliable.
    """

    @property
    def name(self) -> str:
        return "DuckDuckGo"

    def is_available(self) -> bool:
        return True  # Always available as fallback

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        data = {
            "q": query,
            "b": "",
            "kl": "cn-zh" if locale.startswith("zh") else "us-en",
        }

        try:
            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=data, timeout=30, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: DuckDuckGo returned status {resp.status}"

                    html = await resp.text()
                    results = []

                    # Parse links and snippets
                    link_pattern = re.compile(
                        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
                        re.IGNORECASE
                    )
                    snippet_pattern = re.compile(
                        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                        re.DOTALL | re.IGNORECASE
                    )

                    links = link_pattern.findall(html)
                    snippets = snippet_pattern.findall(html)

                    for i, (link_url, title) in enumerate(links[:count]):
                        snippet = ""
                        if i < len(snippets):
                            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()

                        # Extract actual URL from DuckDuckGo redirect
                        if "uddg=" in link_url:
                            try:
                                params = parse_qs(link_url.split("?")[1] if "?" in link_url else "")
                                actual_url = unquote(params.get("uddg", [link_url])[0])
                            except:
                                actual_url = link_url
                        else:
                            actual_url = link_url

                        results.append(f"{i+1}. {title.strip()}\n   URL: {actual_url}\n   {snippet}")

                    if not results:
                        return "No results found"

                    return "\n\n".join(results)

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            return f"Error: DuckDuckGo search failed: {e}"


class TavilyProvider(SearchProvider):
    @property
    def name(self) -> str:
        return "Tavily"

    def is_available(self) -> bool:
        config = get_search_config()
        return bool(getattr(config, "tavily_api_key", ""))

    async def search(self, query: str, count: int = 5, locale: str = "zh-CN") -> str:
        config = get_search_config()
        api_key = getattr(config, "tavily_api_key", "")
        if not api_key:
            return "Error: Tavily API key not configured"

        url = "https://api.tavily.com/search"
        payload: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": min(count, 10),
            "search_depth": "advanced",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
        }
        if locale.startswith("zh"):
            payload["include_domains"] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=30) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return f"Error: Tavily returned status {resp.status}: {text[:200]}"

                    data = await resp.json()
                    results = data.get("results", []) or []
                    if not results:
                        return "No results found"

                    output = []
                    for i, r in enumerate(results[:count], 1):
                        title = r.get("title") or "No title"
                        result_url = r.get("url") or ""
                        snippet = (r.get("content") or "").strip()
                        output.append(f"{i}. {title}\n   URL: {result_url}\n   {snippet}")

                    return "\n\n".join(output)
        except Exception as e:
            logger.error(f"Tavily search error: {e}")
            return f"Error: Tavily search failed: {e}"


# ============== Helper Functions ==============

def _get_ssl_context():
    """Get SSL context based on environment."""
    import ssl
    import os
    
    if os.environ.get("FLASK_ENV") == "development" or os.environ.get("DEBUG") == "True":
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context
    return None


# ============== Provider Registry ==============

# All available providers in priority order (Bing first for China users)
SEARCH_PROVIDERS: List[SearchProvider] = [
    BingProvider(),       # Default: works in China, no API key needed
    SearXNGProvider(),    # Self-hosted, recommended for quality
    SerperProvider(),     # Google API (paid)
    BraveProvider(),      # Brave API (paid)
    TavilyProvider(),     # Deep search (paid)
    GoogleProvider(),     # Google Custom Search (may not work in China)
    DuckDuckGoProvider(), # Free fallback
]

# Provider name to instance mapping
PROVIDER_MAP: Dict[str, SearchProvider] = {
    "bing": BingProvider(),
    "searxng": SearXNGProvider(),
    "serper": SerperProvider(),
    "brave": BraveProvider(),
    "tavily": TavilyProvider(),
    "google": GoogleProvider(),
    "duckduckgo": DuckDuckGoProvider(),
}


def get_search_provider() -> SearchProvider:
    """Get the best available search provider."""
    config = get_search_config()

    # Check if user specified a preferred provider
    if config.provider and config.provider in PROVIDER_MAP:
        provider = PROVIDER_MAP[config.provider]
        if provider.is_available():
            return provider
        logger.warning(f"Preferred search provider '{config.provider}' is not configured, falling back...")

    # Find first available provider
    for provider in SEARCH_PROVIDERS:
        if provider.is_available():
            return provider

    # Ultimate fallback is Bing (always available)
    return BingProvider()


def get_available_providers() -> List[str]:
    """Get list of available (configured) search provider names."""
    return [p.name for p in SEARCH_PROVIDERS if p.is_available()]


# ============== System Tools ==============

class WebSearchTool(SystemTool):
    """Search the web using the best available provider."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        providers = get_available_providers()
        provider_list = ", ".join(providers) if providers else "DuckDuckGo (fallback)"
        return (
            f"Search the web for information. Returns search results with titles, URLs, and snippets. "
            f"Available providers: {provider_list}. "
            f"Current: {get_search_provider().name}. "
            f"Supports Chinese and English queries."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="query",
                type="string",
                description="The search query (supports Chinese and English)",
                required=True,
            ),
            ToolParameterSchema(
                name="count",
                type="integer",
                description="Number of results to return (default: 5, max: 10)",
                required=False,
                default=5,
            ),
            ToolParameterSchema(
                name="locale",
                type="string",
                description="Search locale (default: zh-CN for Chinese, en-US for English)",
                required=False,
                default="zh-CN",
            ),
            ToolParameterSchema(
                name="provider",
                type="string",
                description="Specific provider to use (searxng/serper/brave/bing/tavily/google/duckduckgo)",
                required=False,
                enum=["searxng", "serper", "brave", "bing", "tavily", "google", "duckduckgo"],
            ),
        ]

    @property
    def category(self) -> str:
        return "web"

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        count = min(kwargs.get("count", 5), 10)
        locale = kwargs.get("locale", "zh-CN")
        provider_name = kwargs.get("provider", "")

        if not query:
            return "Error: query is required"

        try:
            if provider_name and provider_name in PROVIDER_MAP:
                provider = PROVIDER_MAP[provider_name]
                if not provider.is_available():
                    return f"Error: Provider '{provider_name}' is not configured"
                logger.info(f"Using search provider: {provider.name}")
                result = await provider.search(query, count, locale)
                return f"[{provider.name}]\n\n{result}"

            agent_def = kwargs.get("__agent_definition")
            use_global = True
            strategy_mode = "bing_then_tavily"
            deep_trigger = "auto"
            bing_count = count
            tavily_count = min(max(count, 5), 10)
            strategy_locale = locale

            if agent_def is not None:
                try:
                    use_global = bool(getattr(agent_def, "use_global_search_config", True))
                    if not use_global and getattr(agent_def, "search_strategy", None):
                        cfg = getattr(agent_def, "search_strategy")
                        strategy_mode = getattr(cfg, "strategy_mode", strategy_mode)
                        deep_trigger = getattr(cfg, "deep_search_trigger", deep_trigger)
                        strategy_locale = getattr(cfg, "locale", strategy_locale)
                        bing_count = int(getattr(cfg, "bing_count", bing_count))
                        tavily_count = int(getattr(cfg, "tavily_count", tavily_count))
                except Exception:
                    pass

            strategy_locale = strategy_locale or locale
            bing_count = min(max(bing_count, 1), 10)
            tavily_count = min(max(tavily_count, 1), 10)

            bing_provider = PROVIDER_MAP["bing"]
            bing_result = await bing_provider.search(query, bing_count, strategy_locale)

            def _result_count(text: str) -> int:
                return text.count("\n   URL:") + (1 if "URL:" in text else 0)

            should_deep = False
            if strategy_mode in ("bing_then_tavily", "auto"):
                if strategy_mode == "bing_then_tavily":
                    should_deep = True
                else:
                    if deep_trigger == "always":
                        should_deep = True
                    elif deep_trigger == "insufficient_results":
                        should_deep = _result_count(bing_result) < min(3, bing_count)
                    elif deep_trigger == "conflict_detected":
                        should_deep = False
                    elif deep_trigger == "needs_citation":
                        should_deep = _result_count(bing_result) < min(5, bing_count)
                    else:
                        should_deep = _result_count(bing_result) < min(3, bing_count) or "No results found" in bing_result

            sections = [f"[Bing]\n\n{bing_result}"]

            if should_deep:
                tavily_provider = PROVIDER_MAP.get("tavily")
                if tavily_provider and tavily_provider.is_available():
                    tavily_result = await tavily_provider.search(query, tavily_count, strategy_locale)
                    sections.append(f"[Tavily]\n\n{tavily_result}")
                else:
                    sections.append("[Tavily]\n\nError: Tavily is not configured (set TAVILY_API_KEY or /api/search/config)")

            return "\n\n".join(sections)

        except Exception as e:
            logger.error(f"Web search error: {e}")
            return f"Error: Web search failed: {e}"


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
        import html as html_module
        text = html_module.unescape(text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:max_length]

    async def _browser_fetch_text(self, url: str, max_length: int) -> str:
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return "Error: Browser automation not available (install playwright)"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=45000)
                text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                await browser.close()
                text = (text or "").strip()
                if not text:
                    return "Error: Browser automation could not extract content"
                return text[:max_length]
        except Exception as e:
            logger.error(f"Browser fetch error: {e}")
            return f"Error: Browser automation failed: {e}"

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
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

            agent_def = kwargs.get("__agent_definition")
            use_browser_fallback = False
            if agent_def is not None:
                try:
                    if not bool(getattr(agent_def, "use_global_search_config", True)) and getattr(agent_def, "search_strategy", None):
                        cfg = getattr(agent_def, "search_strategy")
                        use_browser_fallback = bool(getattr(cfg, "use_browser_fallback", False))
                except Exception:
                    pass

            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30, allow_redirects=True, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        if use_browser_fallback and resp.status in (401, 403, 429):
                            text = await self._browser_fetch_text(url, max_length)
                            return f"Content from {url}:\n\n{text}"
                        return f"Error: HTTP {resp.status} - {resp.reason}"

                    content_type = resp.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return f"Error: URL does not return HTML content (got {content_type})"

                    html = await resp.text()
                    if use_browser_fallback:
                        lowered = html.lower()
                        if "captcha" in lowered or "verify you are human" in lowered or "access denied" in lowered:
                            text = await self._browser_fetch_text(url, max_length)
                            return f"Content from {url}:\n\n{text}"
                    text = self._extract_text(html, max_length)

                    if not text:
                        if use_browser_fallback:
                            browser_text = await self._browser_fetch_text(url, max_length)
                            return f"Content from {url}:\n\n{browser_text}"
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

            ssl_context = _get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=120, ssl=ssl_context) as resp:
                    if resp.status != 200:
                        return f"Error: HTTP {resp.status} - {resp.reason}"

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
