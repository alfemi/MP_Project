import json
import logging
from functools import lru_cache
from urllib.parse import urlparse


import requests

logger = logging.getLogger(__name__)


class ExternalTitleImageSearchService:
    """
    Demo-only image resolver.

    Best-effort fallback for an educational local demo. It first tries a search
    package if installed, then Wikipedia, then iTunes. It must never crash the
    Django app if external search is blocked or rate-limited.
    """

    WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
    TIMEOUT_SECONDS = 4

    DEFAULT_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "StreamSync/1.0 demo image fallback",
    }

    @classmethod
    @lru_cache(maxsize=512)
    def search_movie_image(cls, title):
        normalized_title = (title or "").strip()
        if not normalized_title:
            return ""

        search_image = cls._search_duckduckgo_image(normalized_title)
        if search_image:
            return search_image

        wikipedia_image = cls._search_wikipedia_image(normalized_title)
        if wikipedia_image:
            return wikipedia_image

        return cls._search_itunes_image(normalized_title)

    @classmethod
    def _get_ddgs_class(cls):
        try:
            from ddgs import DDGS
            return DDGS
        except ImportError:
            pass

        try:
            from duckduckgo_search import DDGS
            return DDGS
        except ImportError:
            return None

    @classmethod
    def _search_duckduckgo_image(cls, normalized_title):
        DDGS = cls._get_ddgs_class()
        if DDGS is None:
            logger.debug("No DDGS package installed; skipping DuckDuckGo image lookup")
            return ""

        queries = (
            f"{normalized_title} movie poster",
            f"{normalized_title} film poster",
            f"{normalized_title} official poster",
        )

        for query in queries:
            try:
                with DDGS() as ddgs:
                    results = ddgs.images(
                        query,
                        region="wt-wt",
                        safesearch="moderate",
                        max_results=8,
                    )

                    for result in results:
                        image_url = (
                            result.get("image")
                            or result.get("thumbnail")
                            or result.get("url")
                            or ""
                        )
                        if cls._is_usable_image_url(image_url):
                            logger.info(
                                "Resolved search image for '%s' using query '%s': %s",
                                normalized_title,
                                query,
                                image_url,
                            )
                            return image_url

            except Exception as exc:
                logger.debug(
                    "Image search skipped for '%s' with query '%s': %s",
                    normalized_title,
                    query,
                    exc,
                )
                continue

        return ""

    @classmethod
    def _is_usable_image_url(cls, url):
        if not url or not isinstance(url, str):
            return False

        candidate = url.strip()
        if not candidate or candidate.lower().startswith("data:"):
            return False

        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.lower()

        blocked_hosts = {
            "duckduckgo.com",
            "google.com",
        }
        if host in blocked_hosts:
            return False

        image_extensions = (".jpg", ".jpeg", ".png", ".webp")
        if any(path.endswith(ext) or ext in path for ext in image_extensions):
            return True

        imageish_host_tokens = (
            "image",
            "img",
            "poster",
            "media",
            "static",
            "cdn",
            "amazon",
            "tmdb",
            "wikimedia",
            "gstatic",
            "mzstatic",
            "ssl-images",
        )
        return any(token in host for token in imageish_host_tokens)

    @classmethod
    def _search_wikipedia_image(cls, normalized_title):
        try:
            response = requests.get(
                cls.WIKIPEDIA_SUMMARY_URL.format(
                    title=normalized_title.replace(" ", "_")
                ),
                headers=cls.DEFAULT_HEADERS,
                timeout=cls.TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                logger.debug(
                    "Wikipedia image lookup failed for '%s' with status %s",
                    normalized_title,
                    response.status_code,
                )
                return ""

            payload = response.json()
            image_url = (
                (payload.get("originalimage") or {}).get("source")
                or (payload.get("thumbnail") or {}).get("source")
                or ""
            )

            if cls._is_usable_image_url(image_url):
                logger.info(
                    "Resolved Wikipedia image for '%s': %s",
                    normalized_title,
                    image_url,
                )
                return image_url

            return ""

        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Wikipedia lookup failed for '%s': %s", normalized_title, exc)
            return ""

    @classmethod
    def _search_itunes_image(cls, normalized_title):
        try:
            response = requests.get(
                cls.ITUNES_SEARCH_URL,
                params={"term": normalized_title, "media": "movie", "limit": 1},
                headers=cls.DEFAULT_HEADERS,
                timeout=cls.TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                logger.debug(
                    "iTunes image lookup failed for '%s' with status %s",
                    normalized_title,
                    response.status_code,
                )
                return ""

            payload = response.json()
            results = payload.get("results") or []
            if not results:
                logger.debug("No iTunes image result for title '%s'", normalized_title)
                return ""

            artwork_url = (
                results[0].get("artworkUrl600")
                or results[0].get("artworkUrl100")
                or results[0].get("artworkUrl60")
                or ""
            )

            if artwork_url and "100x100bb" in artwork_url:
                artwork_url = artwork_url.replace("100x100bb", "600x600bb")

            if cls._is_usable_image_url(artwork_url):
                logger.info(
                    "Resolved iTunes image for '%s': %s",
                    normalized_title,
                    artwork_url,
                )
                return artwork_url

            return ""

        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            logger.debug("iTunes lookup failed for '%s': %s", normalized_title, exc)
            return ""
