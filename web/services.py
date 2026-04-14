import concurrent.futures
import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


class StreamApiService:
    @staticmethod
    def _fetch_from_api(api_config, endpoint, params=None):
        """
        Petición base a las réplicas de la API.
        """
        url = f"{api_config['url'].rstrip('/')}/{endpoint.lstrip('/')}"
        
        # Limpieza de parámetros para evitar errores 500
        clean_params = {k: v for k, v in (params or {}).items() if v}
        
        headers = {
            'X-API-KEY': api_config['api_key'],
            'Accept': 'application/json',
            'User-Agent': 'curl/7.81.0'
        }

        try:
            response = requests.get(url, headers=headers, params=clean_params, timeout=5)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.warning("Error calling Stream API %s: %s", url, e)
            return []

    @classmethod
    def get_all_data(cls, endpoint, params=None):
        """
        Consulta las 3 APIs en paralelo y elimina duplicados por ID.
        """
        all_results = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_api = {
                executor.submit(cls._fetch_from_api, api, endpoint, params): api 
                for api in settings.STREAM_APIS
            }
            for future in concurrent.futures.as_completed(future_to_api):
                data = future.result()
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
        # Asumiendo que devuelve {'id': X, 'name': 'Nombre'}
        # Si la API devuelve 'full_name' o similar, ajusta la clave aquí
        return [(str(d['id']), d.get('name') or d.get('full_name', 'Desconocido')) 
                for d in data if 'id' in d]
