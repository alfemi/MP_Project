from .image_resolver import ContentImageService


class ContentCatalogService:
    PLATFORM_NAME_KEYS = ('platform_name', 'platform', 'provider_name', 'provider', 'streaming_service')
    PLATFORM_URL_KEYS = ('platform_url', 'watch_url', 'redirect_url', 'url')
    SYNOPSIS_KEYS = ('synopsis', 'overview', 'description', 'plot', 'summary')

    @classmethod
    def get_platform_info(cls, item):
        for key in cls.PLATFORM_NAME_KEYS:
            value = item.get(key)
            if value:
                return value, cls._get_platform_url(item)

        platforms = item.get('platforms')
        if isinstance(platforms, list) and platforms:
            first_platform = platforms[0]
            if isinstance(first_platform, dict):
                name = first_platform.get('name') or first_platform.get('platform_name') or 'Plataforma externa'
                return name, first_platform.get('url') or first_platform.get('platform_url', '')
            if isinstance(first_platform, str):
                return first_platform, cls._get_platform_url(item)

        return "", cls._get_platform_url(item)

    @classmethod
    def _get_platform_url(cls, item):
        for key in cls.PLATFORM_URL_KEYS:
            value = item.get(key)
            if value:
                return value
        return ""

    @classmethod
    def get_synopsis(cls, item):
        for key in cls.SYNOPSIS_KEYS:
            value = item.get(key)
            if value:
                return value
        return ""

    @classmethod
    def normalize_item(cls, item, content_type, director_dict, genre_dict, overrides_map, age_rating_map):
        normalized = dict(item)
        normalized['content_type'] = content_type
        normalized['content_id'] = str(item.get('id') or item.get('movie_id') or "")
        normalized['title'] = item.get('title') or item.get('name') or "Sin título"
        normalized['genre_key'] = str(item.get('genre_id') or "")
        normalized['director_name'] = director_dict.get(str(item.get('director_id')), "Director desconocido")
        normalized['genre_description'] = genre_dict.get(str(item.get('genre_id')), "General")
        normalized['synopsis'] = cls.get_synopsis(item) or "Sin sinopsis disponible."
        normalized['platform_name'], normalized['platform_url'] = cls.get_platform_info(item)
        image_data = ContentImageService.resolve_image(item, overrides_map)
        normalized['image_url'] = image_data['url']
        normalized['image_source'] = image_data['source']
        min_age = age_rating_map.get(item.get('age_rating_id', 1), 0)
        normalized['age_rating_label'] = f"+{min_age}" if min_age else "TP"
        normalized['popularity_score'] = float(item.get('popularity') or item.get('rating') or 0)
        return normalized

    @classmethod
    def build_recommendations(cls, current_item, candidates, user_preferences, limit=6):
        preferred_genres = set(user_preferences)
        current_genre = current_item.get('genre_key')

        def score(item):
            item_genre = item.get('genre_key')
            genre_match = 3 if item_genre == current_genre else 0
            preference_match = 2 if item_genre in preferred_genres else 0
            popularity = item.get('popularity_score', 0)
            return (genre_match + preference_match, popularity)

        filtered = [
            item for item in candidates
            if item.get('content_id') != current_item.get('content_id')
        ]
        filtered.sort(key=score, reverse=True)
        return filtered[:limit]
