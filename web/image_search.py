import logging
from functools import lru_cache

import requests


logger = logging.getLogger(__name__)


class ExternalTitleImageSearchService:
    WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
    TIMEOUT_SECONDS = 2
    DEFAULT_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "StreamSync/1.0 (image fallback lookup)",
    }

    @classmethod
    @lru_cache(maxsize=256)
    def search_movie_image(cls, title):
        normalized_title = (title or "").strip()
        if not normalized_title:
            return ""

        wikipedia_image = cls._search_wikipedia_image(normalized_title)
        if wikipedia_image:
            return wikipedia_image

        return cls._search_itunes_image(normalized_title)

    @classmethod
    def _search_wikipedia_image(cls, normalized_title):
        try:
            response = requests.get(
                cls.WIKIPEDIA_SUMMARY_URL.format(title=normalized_title.replace(" ", "_")),
                headers=cls.DEFAULT_HEADERS,
                timeout=cls.TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                logger.warning(
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
            if image_url:
                logger.info(
                    "Resolved Wikipedia image for '%s': %s",
                    normalized_title,
                    image_url,
                )
            return image_url
        except requests.RequestException as exc:
            logger.warning("Wikipedia lookup failed for '%s': %s", normalized_title, exc)
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
                logger.warning(
                    "iTunes image lookup failed for '%s' with status %s",
                    normalized_title,
                    response.status_code,
                )
                return ""

            payload = response.json()
            results = payload.get("results") or []
            if not results:
                logger.info("No iTunes image result for title '%s'", normalized_title)
                return ""

            artwork_url = (
                results[0].get("artworkUrl600")
                or results[0].get("artworkUrl100")
                or results[0].get("artworkUrl60")
                or ""
            )
            if artwork_url and "100x100bb" in artwork_url:
                artwork_url = artwork_url.replace("100x100bb", "600x600bb")

            if artwork_url:
                logger.info(
                    "Resolved iTunes image for '%s': %s",
                    normalized_title,
                    artwork_url,
                )
            return artwork_url
        except requests.RequestException as exc:
            logger.warning("iTunes lookup failed for '%s': %s", normalized_title, exc)
            return ""
