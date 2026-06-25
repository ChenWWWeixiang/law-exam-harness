"""WebSearch 抽象与 Tavily 实现。

MVP 仅内置 Tavily,接口预留以便后续接入 Bing/Google/SerpAPI 等。
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests

log = logging.getLogger(__name__)


class WebSearchProvider(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """返回 [{title, url, snippet}, ...]"""


class TavilyProvider:
    """Tavily Search API (https://docs.tavily.com)."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.tavily.com/search"

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            resp = requests.post(
                self.endpoint,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("Tavily 搜索失败: %s", e)
            return []

        data = resp.json()
        results = data.get("results", []) or []
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in results
        ]


def make_provider(provider_name: str, api_key: str) -> WebSearchProvider | None:
    """工厂方法:根据名字返回对应 provider 实例;未配置或不支持则返回 None。"""
    if not provider_name or not api_key:
        return None
    name = provider_name.strip().lower()
    if name == "tavily":
        return TavilyProvider(api_key)
    log.warning("未知的 WebSearch provider: %s (目前仅支持 tavily)", name)
    return None


def do_search(provider_name: str, api_key: str, query: str, max_results: int = 5) -> list[dict]:
    """便捷封装:返回空列表表示未启用或失败。"""
    provider = make_provider(provider_name, api_key)
    if provider is None:
        return []
    return provider.search(query, max_results=max_results)