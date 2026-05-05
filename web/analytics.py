from collections import Counter, defaultdict
from datetime import datetime

from django.db.models import Count
from django.utils import timezone

from .content_service import ContentCatalogService
from .image_resolver import ContentImageService
from .models import ContentInteraction, FavoriteContent, FunctionalUser, InfoUser
from .services import StreamApiService


PERIOD_OPTIONS = {
    "7d": ("Últims 7 dies", 7),
    "30d": ("Últim mes", 30),
    "90d": ("Últim trimestre", 90),
    "total": ("Tot", None),
}
OBJECTIVE_OPTIONS = {
    "growth": "Creixement",
    "retention": "Retenció",
    "diversification": "Diversificació",
}
STATUS_LABELS = {
    "complete": "Complet",
    "success": "Complet",
    "partial": "Parcial",
    "provisional": "Provisional",
    "unavailable": "No disponible",
    "not_reliable": "No fiable",
    "warning": "Avís",
    "danger": "Risc",
}
AGE_RATING_MAP = {1: 0, 2: 7, 3: 13, 4: 16, 5: 18}

# Dashboard data notes:
# Real metrics: FunctionalUser totals, InfoUser age/gender/preferences, favorites,
# ContentInteraction timestamps/actions, catalog provider/rating/image/link fields.
# Approximations: platform market share falls back to catalog provider distribution
# because user subscription declarations are not currently stored.
# Unavailable: nationality/country/region, unless a future profile field is added.


def _period_cutoff(period):
    days = PERIOD_OPTIONS.get(period, PERIOD_OPTIONS["total"])[1]
    if days is None:
        return None
    return timezone.now() - timezone.timedelta(days=days)


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _content_rating(item):
    for key in ("rating", "popularity_score", "popularity"):
        rating = _safe_float(item.get(key))
        if rating is not None and rating > 0:
            return rating
    return None


def _normalize_catalog_items(items, content_type, director_dict, genre_dict, overrides_map):
    normalized_items = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        normalized = ContentCatalogService.normalize_item(
            item,
            content_type,
            director_dict,
            genre_dict,
            overrides_map,
            AGE_RATING_MAP,
        )
        normalized_items.append(normalized)
    return normalized_items


def _load_catalog():
    genres_list = StreamApiService.get_genres()
    directors_list = StreamApiService.get_directors()
    movies = StreamApiService.get_movies()
    series = StreamApiService.get_series()
    genre_dict = {str(gid): gname for gid, gname in genres_list}
    director_dict = {str(did): dname for did, dname in directors_list}
    overrides_map = ContentImageService.build_override_map([*movies, *series])
    normalized_movies = _normalize_catalog_items(
        movies,
        "movie",
        director_dict,
        genre_dict,
        overrides_map,
    )
    normalized_series = _normalize_catalog_items(
        series,
        "series",
        director_dict,
        genre_dict,
        overrides_map,
    )
    return normalized_movies, normalized_series, [*normalized_movies, *normalized_series]


def _chart(labels, values, *, status, explanation, source, extra=None):
    payload = {
        "labels": labels,
        "values": values,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "explanation": explanation,
        "source": source,
    }
    if extra:
        payload.update(extra)
    return payload


def _count_items_by(items, key, fallback):
    counter = Counter((item.get(key) or fallback) for item in items)
    return [{"label": label, "total": total} for label, total in counter.most_common()]


def _querysets_for_period(period):
    cutoff = _period_cutoff(period)
    interactions = ContentInteraction.objects.all()
    favorites = FavoriteContent.objects.all()
    if cutoff:
        interactions = interactions.filter(timestamp__gte=cutoff)
        favorites = favorites.filter(created_at__gte=cutoff)
    return interactions, favorites


def build_demographic_chart_data():
    return _chart(
        [],
        [],
        status="unavailable",
        explanation="No disponible: el perfil d'usuari encara no registra nacionalitat o país/regió.",
        source="FunctionalUser/InfoUser",
    )


def build_genre_trend_data(interactions, favorites):
    genre_counter = Counter()
    temporal = defaultdict(Counter)

    for row in interactions.exclude(genre="").values("genre", "timestamp"):
        genre = row["genre"]
        genre_counter[genre] += 1
        timestamp = row.get("timestamp")
        if timestamp:
            temporal[timestamp.date().isoformat()][genre] += 1

    if not genre_counter:
        for row in favorites.exclude(genre="").values("genre"):
            genre_counter[row["genre"]] += 1
        if genre_counter:
            rows = genre_counter.most_common(8)
            return _chart(
                [label for label, _ in rows],
                [value for _, value in rows],
                status="partial",
                explanation="Distribució actual basada en favorits; tendència temporal no disponible perquè no hi ha visualitzacions suficients.",
                source="FavoriteContent.genre",
            )
        return _chart(
            [],
            [],
            status="unavailable",
            explanation="No disponible: encara no hi ha interaccions ni favorits amb gènere.",
            source="ContentInteraction/FavoriteContent",
        )

    rows = genre_counter.most_common(8)
    top_genres = [label for label, _ in rows[:5]]
    temporal_labels = sorted(temporal)
    datasets = [
        {
            "label": genre,
            "values": [temporal[date].get(genre, 0) for date in temporal_labels],
        }
        for genre in top_genres
    ]
    return _chart(
        [label for label, _ in rows],
        [value for _, value in rows],
        status="complete" if len(temporal_labels) > 1 else "partial",
        explanation=(
            "Tendència temporal calculada amb visualitzacions registrades."
            if len(temporal_labels) > 1
            else "Tendència temporal no disponible: encara no hi ha històric suficient."
        ),
        source="ContentInteraction.genre/timestamp",
        extra={"temporal_labels": temporal_labels, "temporal_datasets": datasets},
    )


def build_platform_share_data(catalog_items):
    rows = _count_items_by(catalog_items, "platform_name", "Proveedor no disponible")
    rows = [row for row in rows if row["label"]]
    if not rows:
        return _chart(
            [],
            [],
            status="unavailable",
            explanation="No disponible: no hi ha dades de subscripcions declarades ni proveïdors de catàleg.",
            source="No disponible",
        )
    top_rows = rows[:8]
    return _chart(
        [row["label"] for row in top_rows],
        [row["total"] for row in top_rows],
        status="partial",
        explanation="Distribució del catàleg per proveïdor, no subscripcions d'usuari.",
        source="StreamApiService platform/provider fields",
    )


def build_catalog_quality_data(catalog_items):
    total = len(catalog_items)
    with_image = sum(1 for item in catalog_items if item.get("image_url") and item.get("image_source") != "placeholder")
    with_provider = sum(1 for item in catalog_items if item.get("platform_url"))
    with_rating = sum(1 for item in catalog_items if _content_rating(item) is not None)
    missing_image = total - with_image
    missing_provider = total - with_provider
    missing_rating = total - with_rating
    possible_checks = total * 3
    passed_checks = with_image + with_provider + with_rating
    score = round((passed_checks / possible_checks) * 100) if possible_checks else 0
    status = "success" if score >= 80 else "warning" if score >= 50 else "danger"
    return {
        "status": status,
        "score": score,
        "items": [
            {"label": "Amb imatge", "value": with_image},
            {"label": "Sense imatge", "value": missing_image},
            {"label": "Amb enllaç", "value": with_provider},
            {"label": "Sense enllaç", "value": missing_provider},
            {"label": "Amb rating", "value": with_rating},
            {"label": "Sense rating", "value": missing_rating},
        ],
        "chart": _chart(
            ["Amb imatge", "Sense imatge", "Amb enllaç", "Sense enllaç", "Amb rating", "Sense rating"],
            [with_image, missing_image, with_provider, missing_provider, with_rating, missing_rating],
            status="complete" if total else "unavailable",
            explanation="Qualitat operativa calculada amb camps disponibles del catàleg.",
            source="StreamApiService normalized catalog",
        ),
    }


def build_top_content_data(catalog_items, interactions, favorites):
    favorite_counts = {
        (row["content_type"], row["content_id"]): row["total"]
        for row in favorites.values("content_type", "content_id").annotate(total=Count("id"))
    }
    view_counts = {
        (row["content_type"], row["content_id"]): row["total"]
        for row in interactions.filter(interaction_type="view")
        .values("content_type", "content_id")
        .annotate(total=Count("id"))
    }
    rows = []
    for item in catalog_items:
        key = (item.get("content_type"), str(item.get("content_id")))
        rating = _content_rating(item)
        rows.append(
            {
                "content_id": item.get("content_id"),
                "content_type": item.get("content_type"),
                "title": item.get("title") or "Sin título",
                "genre": item.get("genre_description") or "General",
                "platform": item.get("platform_name") or "Proveedor no disponible",
                "rating": rating,
                "favorite_count": favorite_counts.get(key, 0),
                "view_count": view_counts.get(key, 0),
                "quality_flags": ", ".join(
                    flag
                    for flag, active in {
                        "sense imatge": not item.get("image_url") or item.get("image_source") == "placeholder",
                        "sense enllaç": not item.get("platform_url"),
                        "sense rating": rating is None,
                    }.items()
                    if active
                )
                or "OK",
            }
        )
    rows.sort(
        key=lambda row: (
            row["view_count"],
            row["favorite_count"],
            row["rating"] or 0,
        ),
        reverse=True,
    )
    return rows[:12]


def build_periodic_report_summary(period, interactions, favorites, quality_data):
    has_history = interactions.exists()
    warnings = []
    if quality_data["score"] < 80:
        warnings.append("La qualitat del catàleg requereix revisió operativa.")
    if not has_history:
        warnings.append("Evolució temporal no disponible fins que es registrin snapshots periòdics.")
    return {
        "period": PERIOD_OPTIONS.get(period, PERIOD_OPTIONS["total"])[0],
        "generated_at": timezone.now(),
        "status": "partial" if has_history else "provisional",
        "status_label": "Parcial" if has_history else "Provisional",
        "deviations": warnings,
        "summary": [
            {"label": "Interaccions del període", "value": interactions.count()},
            {"label": "Favorits del període", "value": favorites.count()},
            {"label": "Qualitat de dades", "value": f"{quality_data['score']}%"},
        ],
    }


def build_strategic_report_summary(objective, period, genre_chart, platform_chart, quality_data):
    objective_label = OBJECTIVE_OPTIONS.get(objective, OBJECTIVE_OPTIONS["growth"])
    most_relevant_genre = genre_chart["labels"][0] if genre_chart["labels"] else "No disponible"
    main_platform = platform_chart["labels"][0] if platform_chart["labels"] else "No disponible"
    quality_score = quality_data["score"]
    return {
        "objective": objective,
        "objective_label": objective_label,
        "period": PERIOD_OPTIONS.get(period, PERIOD_OPTIONS["total"])[0],
        "status": "provisional",
        "note": "Escenaris orientatius basats en les dades disponibles; no són prediccions automàtiques robustes.",
        "evidence": [
            f"Gènere amb més senyals: {most_relevant_genre}.",
            f"Proveïdor principal segons catàleg: {main_platform}.",
            f"Completitud operativa del catàleg: {quality_score}%.",
        ],
        "opportunities": [
            "Prioritzar contingut i comunicació al voltant dels gèneres amb més interaccions.",
            "Revisar proveïdors amb alta presència per detectar oportunitats B2B.",
        ],
        "risks": [
            "Les conclusions sobre subscripcions són parcials perquè no hi ha subscripcions declarades.",
            "La manca d'imatges, enllaços o ratings redueix la fiabilitat de l'informe.",
        ],
        "scenarios": [
            {"label": "Optimista", "text": "Augment d'interaccions si es reforcen els gèneres dominants i millora la qualitat del catàleg."},
            {"label": "Esperat", "text": "Evolució estable amb lectures parcials mentre creix l'històric d'interaccions."},
            {"label": "Conservador", "text": "Baixa confiança si persisteixen buits de dades o falta d'històric temporal."},
        ],
        "technical_note": "Variables utilitzades: distribució de gèneres, favorits, visualitzacions, proveïdors del catàleg i completitud d'imatge/enllaç/rating.",
    }


def get_director_dashboard_context(params=None, user=None):
    params = params or {}
    period = params.get("period", "30d")
    if period not in PERIOD_OPTIONS:
        period = "30d"
    objective = params.get("objective", "growth")
    if objective not in OBJECTIVE_OPTIONS:
        objective = "growth"

    generated_at = timezone.now()
    normalized_movies, normalized_series, catalog_items = _load_catalog()
    interactions, favorites = _querysets_for_period(period)
    ratings = [rating for rating in (_content_rating(item) for item in catalog_items) if rating is not None]
    genre_chart = build_genre_trend_data(interactions, favorites)
    platform_chart = build_platform_share_data(catalog_items)
    demographic_chart = build_demographic_chart_data()
    quality_data = build_catalog_quality_data(catalog_items)
    top_content = build_top_content_data(catalog_items, interactions, favorites)
    genre_rows = _count_items_by(catalog_items, "genre_description", "General")[:10]
    platform_rows = _count_items_by(catalog_items, "platform_name", "Proveedor no disponible")[:10]
    top_genre = genre_chart["labels"][0] if genre_chart["labels"] else "No disponible"
    top_platform = platform_chart["labels"][0] if platform_chart["labels"] else "No disponible"
    active_users = interactions.values("user").distinct().count()

    overall_status = "complete"
    if any(chart["status"] in {"partial", "provisional", "unavailable"} for chart in [genre_chart, platform_chart, demographic_chart]):
        overall_status = "provisional"
    if quality_data["status"] == "danger":
        overall_status = "partial"

    kpi_cards = [
        {"label": "Usuaris registrats", "value": FunctionalUser.objects.count(), "note": "FunctionalUser totals", "status": "success"},
        {"label": "Usuaris actius", "value": active_users, "note": "Amb interaccions al període", "status": "success" if active_users else "warning"},
        {"label": "Catàleg total", "value": len(catalog_items), "note": f"{len(normalized_movies)} pel·lícules · {len(normalized_series)} sèries", "status": "success" if catalog_items else "warning"},
        {"label": "Interaccions", "value": interactions.count(), "note": PERIOD_OPTIONS[period][0], "status": "success" if interactions.exists() else "warning"},
        {"label": "Favorits", "value": favorites.count(), "note": PERIOD_OPTIONS[period][0], "status": "success" if favorites.exists() else "neutral"},
        {"label": "Rating mitjà", "value": round(sum(ratings) / len(ratings), 2) if ratings else "N/D", "note": "Només contingut amb rating", "status": "success" if ratings else "warning"},
        {"label": "Gènere principal", "value": top_genre, "note": genre_chart["source"], "status": "success" if top_genre != "No disponible" else "warning"},
        {"label": "Plataforma principal", "value": top_platform, "note": platform_chart["explanation"], "status": "warning" if platform_chart["status"] == "partial" else "success"},
        {"label": "Qualitat de dades", "value": f"{quality_data['score']}%", "note": "Imatge, enllaç i rating", "status": quality_data["status"]},
    ]

    strategic_report = build_strategic_report_summary(objective, period, genre_chart, platform_chart, quality_data)
    periodic_report = build_periodic_report_summary(period, interactions, favorites, quality_data)

    return {
        "user": user,
        "period": period,
        "period_options": [{"value": key, "label": label} for key, (label, _) in PERIOD_OPTIONS.items()],
        "objective": objective,
        "objective_options": [{"value": key, "label": label} for key, label in OBJECTIVE_OPTIONS.items()],
        "generated_at": generated_at,
        "data_status": overall_status,
        "data_status_label": STATUS_LABELS.get(overall_status, overall_status),
        "source_summary": "FunctionalUser, InfoUser, FavoriteContent, ContentInteraction i StreamApiService.",
        "movie_total": len(normalized_movies),
        "series_total": len(normalized_series),
        "catalog_total": len(catalog_items),
        "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "favorite_total": favorites.count(),
        "interaction_total": interactions.count(),
        "without_provider_link_total": sum(1 for item in catalog_items if not item.get("platform_url")),
        "without_image_total": sum(1 for item in catalog_items if not item.get("image_url") or item.get("image_source") == "placeholder"),
        "kpi_cards": kpi_cards,
        "demographic_chart": demographic_chart,
        "genre_chart": genre_chart,
        "platform_chart": platform_chart,
        "quality_data": quality_data,
        "catalog_quality_chart": quality_data["chart"],
        "top_content_rows": top_content,
        "top_rated_items": [row for row in top_content if row["rating"] is not None][:8],
        "items_without_provider_link": [item for item in catalog_items if not item.get("platform_url")][:8],
        "items_without_image": [item for item in catalog_items if not item.get("image_url") or item.get("image_source") == "placeholder"][:8],
        "genre_rows": genre_rows,
        "platform_rows": platform_rows,
        "strategic_report": strategic_report,
        "periodic_report": periodic_report,
    }


def build_director_export_rows(context):
    period = context["period"]
    rows = []
    for chart_name, chart in [
        ("demographic", context["demographic_chart"]),
        ("genre", context["genre_chart"]),
        ("platform", context["platform_chart"]),
        ("catalog_quality", context["catalog_quality_chart"]),
    ]:
        if not chart["labels"]:
            rows.append(
                {
                    "dimension": chart_name,
                    "label": chart["explanation"],
                    "count": "",
                    "period": period,
                    "source": chart["source"],
                    "status": chart["status"],
                }
            )
            continue
        for label, value in zip(chart["labels"], chart["values"]):
            rows.append(
                {
                    "dimension": chart_name,
                    "label": label,
                    "count": value,
                    "period": period,
                    "source": chart["source"],
                    "status": chart["status"],
                }
            )
    for row in context["top_content_rows"]:
        rows.append(
            {
                "dimension": "top_content",
                "label": row["title"],
                "count": row["view_count"] + row["favorite_count"],
                "period": period,
                "source": f"{row['genre']} / {row['platform']} / rating={row['rating'] or 'N/D'}",
                "status": row["quality_flags"],
            }
        )
    return rows
