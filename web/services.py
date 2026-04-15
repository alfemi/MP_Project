import concurrent.futures
import logging
from json import JSONDecodeError
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import connection

from .models import ApiFailureEvent


logger = logging.getLogger(__name__)


class StreamApiService:
    REQUEST_TIMEOUT_SECONDS = 2
    DEFAULT_HEADERS = {
        'Accept': 'application/json',
        'User-Agent': 'curl/7.81.0',
    }

    @staticmethod
    def _provider_name_from_config(api_config):
        parsed = urlparse(api_config['url'])
        return parsed.netloc or api_config['url']

    @classmethod
    def _record_api_failure(
        cls,
        api_config,
        endpoint,
        *,
        status_code=None,
        error_type,
        severity='medium',
        error_message="",
        response_excerpt="",
    ):
        ApiFailureEvent.record_failure(
            provider_name=cls._provider_name_from_config(api_config),
            base_url=api_config['url'],
            operation=endpoint,
            status_code=status_code,
            error_type=error_type,
            severity=severity,
            error_message=error_message,
            response_excerpt=response_excerpt,
        )

    @staticmethod
    def _extract_response_excerpt(response):
        if response is None:
            return ""
        return (response.text or "")[:500]

    @classmethod
    def _build_headers(cls, api_config):
        return {
            **cls.DEFAULT_HEADERS,
            'X-API-KEY': api_config['api_key'],
        }

    @classmethod
    def _fetch_from_api(cls, api_config, endpoint, params=None):
        """
        Petición base a las réplicas de la API.
        """
        url = f"{api_config['url'].rstrip('/')}/{endpoint.lstrip('/')}"

        # Limpieza de parámetros para evitar errores 500
        clean_params = {k: v for k, v in (params or {}).items() if v}

        try:
            response = requests.get(
                url,
                headers=cls._build_headers(api_config),
                params=clean_params,
                timeout=cls.REQUEST_TIMEOUT_SECONDS,
            )
            if 400 <= response.status_code:
                cls._record_api_failure(
                    api_config,
                    endpoint,
                    status_code=response.status_code,
                    error_type='http_error',
                    severity='critical' if response.status_code >= 500 else 'medium',
                    error_message=f"HTTP {response.status_code} returned by provider.",
                    response_excerpt=cls._extract_response_excerpt(response),
                )
                return []
            try:
                return response.json()
            except (ValueError, JSONDecodeError) as exc:
                cls._record_api_failure(
                    api_config,
                    endpoint,
                    status_code=response.status_code,
                    error_type='invalid_json',
                    severity='high',
                    error_message=str(exc),
                    response_excerpt=cls._extract_response_excerpt(response),
                )
                logger.warning("Invalid JSON from Stream API %s: %s", url, exc)
                return []
        except requests.exceptions.Timeout as exc:
            cls._record_api_failure(
                api_config,
                endpoint,
                error_type='timeout',
                severity='high',
                error_message=str(exc),
            )
            logger.warning("Timeout calling Stream API %s: %s", url, exc)
            return []
        except requests.exceptions.ConnectionError as exc:
            cls._record_api_failure(
                api_config,
                endpoint,
                error_type='connection_error',
                severity='critical',
                error_message=str(exc),
            )
            logger.warning("Connection error calling Stream API %s: %s", url, exc)
            return []
        except requests.exceptions.RequestException as exc:
            response = getattr(exc, 'response', None)
            cls._record_api_failure(
                api_config,
                endpoint,
                status_code=getattr(response, 'status_code', None),
                error_type='request_exception',
                severity='high',
                error_message=str(exc),
                response_excerpt=cls._extract_response_excerpt(response),
            )
            logger.warning("Request error calling Stream API %s: %s", url, exc)
            return []
        except Exception as exc:
            cls._record_api_failure(
                api_config,
                endpoint,
                error_type='unexpected_error',
                severity='critical',
                error_message=str(exc),
            )
            logger.exception("Unexpected error calling Stream API %s", url)
            return []

    @classmethod
    def _iter_data_sources(cls, endpoint, params=None):
        if connection.vendor == 'sqlite':
            for api in settings.STREAM_APIS:
                yield cls._fetch_from_api(api, endpoint, params)
            return

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(cls._fetch_from_api, api, endpoint, params)
                for api in settings.STREAM_APIS
            ]
            for future in concurrent.futures.as_completed(futures):
                yield future.result()

    @classmethod
    def get_all_data(cls, endpoint, params=None):
        """
        Consulta las 3 APIs en paralelo y elimina duplicados por ID.
        """
        all_results = []
        for data in cls._iter_data_sources(endpoint, params):
            if isinstance(data, list):
                all_results.extend(data)
            elif data:
                all_results.append(data)

        # DEDUPLICACIÓN REFORZADA
        unique_results = []
        seen_ids = set()
        for item in all_results:
            if isinstance(item, dict) and 'id' in item:
                item_id = str(item['id'])
                if item_id not in seen_ids:
                    unique_results.append(item)
                    seen_ids.add(item_id)
            else:
                unique_results.append(item)

        return unique_results

    @classmethod
    def get_movies(cls, filters=None):
        return cls.get_all_data('movies', params=filters)

    @classmethod
    def get_series(cls, filters=None):
        return cls.get_all_data('series', params=filters)

    @classmethod
    def get_genres(cls):
        """
        Obtiene géneros y los formatea para el <select> de Django.
        """
        data = cls.get_all_data('genres')
        # Formato: [(id, nombre), (id, nombre)...]
        return [(str(g['id']), g['description']) for g in data if 'id' in g]

    @classmethod
    def get_directors(cls):
        """
        Obtiene directores del nuevo endpoint /directors.
        """
        data = cls.get_all_data('directors')
        return [
            (str(d['id']), d.get('name') or d.get('full_name', 'Desconocido'))
            for d in data
            if 'id' in d
        ]

    @classmethod
    def get_content_detail(cls, content_type, content_id):
        endpoint = 'movies' if content_type == 'movie' else 'series'
        candidates = cls.get_all_data(endpoint)
        wanted_id = str(content_id)
        for item in candidates:
            if isinstance(item, dict) and str(item.get('id') or item.get('movie_id')) == wanted_id:
                return item
        return None
