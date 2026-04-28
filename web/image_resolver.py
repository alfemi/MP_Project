import logging
from urllib.parse import urljoin, urlparse

from django.conf import settings

from .image_search import ExternalTitleImageSearchService
from .models import MovieImageOverride


logger = logging.getLogger(__name__)


class ContentImageService:
    EXTERNAL_IMAGE_KEYS = (
        'image_url',
        'poster_url',
        'poster',
        'image',
        'thumbnail_url',
        'cover_url',
        'poster_path',
        'backdrop_path',
        'backdrop_url',
    )
    NESTED_IMAGE_KEYS = ('url', 'href', 'src', 'path', 'image_url', 'poster_url')
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500/"

    @classmethod
    def build_override_map(cls, items):
        item_ids = {
            str(item.get('id') or item.get('movie_id')).strip()
            for item in items
            if isinstance(item, dict) and (item.get('id') or item.get('movie_id'))
        }
        if not item_ids:
            return {}
        return {
            override.movie_id: override
            for override in MovieImageOverride.objects.filter(movie_id__in=item_ids)
        }

    @classmethod
    def resolve_image(cls, item, overrides_map):
        item_id = str(item.get('id') or item.get('movie_id') or "").strip()
        override = overrides_map.get(item_id)
        if override and override.manual_image:
            logger.debug(
                "Resolved manual image override for content %s: %s",
                item_id,
                override.manual_image.url,
            )
            return {'url': override.manual_image.url, 'source': 'manual'}

        for key in cls.EXTERNAL_IMAGE_KEYS:
            url = cls._normalize_external_image_url(item, item.get(key), source_key=key)
            if url:
                logger.debug(
                    "Resolved external image for content %s using key '%s': %s",
                    item_id,
                    key,
                    url,
                )
                return {'url': url, 'source': 'external'}

        for key in ('images', 'media', 'assets'):
            image_bucket = item.get(key)
            if isinstance(image_bucket, dict):
                for nested_key in ('poster', 'cover', 'thumbnail', 'backdrop'):
                    url = cls._normalize_external_image_url(
                        item,
                        image_bucket.get(nested_key),
                        source_key=f"{key}.{nested_key}",
                    )
                    if url:
                        logger.debug(
                            "Resolved nested image for content %s from '%s.%s': %s",
                            item_id,
                            key,
                            nested_key,
                            url,
                        )
                        return {'url': url, 'source': 'external'}

        title_fallback = ExternalTitleImageSearchService.search_movie_image(
            item.get("title") or item.get("name") or ""
        )
        if title_fallback:
            logger.info(
                "Resolved title-search fallback image for content %s (%s): %s",
                item_id or "unknown",
                item.get("title") or item.get("name") or "Untitled",
                title_fallback,
            )
            return {'url': title_fallback, 'source': 'search'}

        logger.warning(
            "No image resolved for content %s. Checked fields=%s available_keys=%s",
            item_id or "unknown",
            ", ".join(cls.EXTERNAL_IMAGE_KEYS),
            ", ".join(sorted(item.keys())),
        )
        return {'url': '', 'source': 'placeholder'}

    @classmethod
    def _normalize_external_image_url(cls, item, value, source_key=""):
        if not value:
            return ""

        if isinstance(value, dict):
            for nested_key in cls.NESTED_IMAGE_KEYS:
                nested_value = value.get(nested_key)
                normalized = cls._normalize_external_image_url(
                    item,
                    nested_value,
                    source_key=f"{source_key}.{nested_key}" if source_key else nested_key,
                )
                if normalized:
                    return normalized
            return ""

        if not isinstance(value, str):
            return ""

        candidate = value.strip()
        if not candidate:
            return ""

        if candidate.startswith("//"):
            return f"https:{candidate}"

        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            return candidate

        if cls._looks_like_tmdb_path(candidate, source_key):
            return urljoin(cls.TMDB_IMAGE_BASE, candidate.lstrip("/"))

        base_url = (item.get("_api_base_url") or settings.STREAM_APIS[0]["url"]).rstrip("/") + "/"
        return urljoin(base_url, candidate.lstrip("/"))

    @classmethod
    def _looks_like_tmdb_path(cls, candidate, source_key=""):
        normalized = candidate.strip()
        if not normalized:
            return False
        return (
            source_key in {"poster_path", "backdrop_path"}
            and normalized.startswith("/")
            and "." in normalized.split("/")[-1]
        )
