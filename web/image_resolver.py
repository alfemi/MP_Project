from .models import MovieImageOverride


class ContentImageService:
    EXTERNAL_IMAGE_KEYS = ('image_url', 'poster_url', 'poster', 'image', 'thumbnail_url', 'cover_url')

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
            return {'url': override.manual_image.url, 'source': 'manual'}

        for key in cls.EXTERNAL_IMAGE_KEYS:
            value = item.get(key)
            if value:
                return {'url': value, 'source': 'external'}

        return {'url': '', 'source': 'placeholder'}
