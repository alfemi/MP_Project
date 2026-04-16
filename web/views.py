import csv
import logging

from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

from .content_service import ContentCatalogService
from .image_resolver import ContentImageService
from .models import (
    ApiFailureEvent,
    ContentInteraction,
    FavoriteContent,
    FailedLoginAttempt,
    FunctionalUser,
    InfoUser,
    normalize_email,
    normalize_user_name,
)
from .services import StreamApiService

logger = logging.getLogger(__name__)

AGE_RATING_MAP = {
    1: 0,
    2: 7,
    3: 13,
    4: 16,
    5: 18,
}

LOGIN_FAILURE_WINDOW_MINUTES = 15
LOGIN_FAILURE_LIMIT = 5
API_PARTIAL_WINDOW_MINUTES = 10
VALID_CONTENT_TYPES = {'movie', 'series'}
GENRE_CHOICES = InfoUser.GENRE_CHOICES
LANGUAGE_CHOICES = InfoUser.LANGUAGE_CHOICES
SEX_CHOICES = InfoUser.SEX_CHOICES


# --- HELPER ---

def _get_client_ip(request):
    """Extreu la IP real del client, tenint en compte proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _register_context(form_data=None, error=None):
    return {
        'error': error,
        'genres': GENRE_CHOICES,
        'languages': LANGUAGE_CHOICES,
        'sex_choices': SEX_CHOICES,
        'form_data': form_data or {},
    }


def _extract_error_message(exc):
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return messages[0]
    if hasattr(exc, "messages") and exc.messages:
        return exc.messages[0]
    return "Revisa los datos introducidos."


def _get_current_user(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    try:
        return FunctionalUser.objects.get(id=user_id)
    except FunctionalUser.DoesNotExist:
        return None


def _get_logged_in_user_or_redirect(request):
    user = _get_current_user(request)
    if not user:
        return None, redirect('login')
    if not user.is_active:
        request.session.flush()
        return None, redirect('login')
    return user, None


def _is_internal_user(request, functional_user):
    return bool(functional_user and functional_user.rank == 'sysadmin') or bool(getattr(request.user, 'is_superuser', False))


def _get_user_profile_or_redirect(request):
    user, redirect_response = _get_logged_in_user_or_redirect(request)
    if redirect_response:
        return None, None, redirect_response
    try:
        return user, InfoUser.objects.get(user=user), None
    except InfoUser.DoesNotExist:
        return None, None, redirect('login')


def _parse_preferences(info_user):
    return InfoUser.parse_preferences(info_user.preferences)


def _apply_age_gate(normalized_item, user_age, age_rating_id):
    min_age_required = AGE_RATING_MAP.get(age_rating_id or 1, 0)
    normalized_item['is_blocked'] = user_age < min_age_required
    if normalized_item['is_blocked']:
        normalized_item['block_message'] = f"Contenido para +{min_age_required} años"
    return normalized_item


def _normalize_catalog_items(items, item_type, info_user, director_dict, genre_dict, overrides_map, favorites):
    if not items or not isinstance(items, list):
        return []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue

        normalized = ContentCatalogService.normalize_item(
            item,
            item_type,
            director_dict,
            genre_dict,
            overrides_map,
            AGE_RATING_MAP,
        )
        _apply_age_gate(normalized, info_user.age, item.get('age_rating_id'))
        normalized['is_favorite'] = (item_type, normalized['content_id']) in favorites
        result.append(normalized)
    return result


def _build_catalog_context(
    user,
    info_user,
    movies,
    series,
    genres_list,
    directors_list,
    selected_genre,
    selected_director,
    content_type,
    search_query,
):
    genre_dict = {str(gid): gname for gid, gname in genres_list}
    director_dict = {str(did): dname for did, dname in directors_list}
    overrides_map = ContentImageService.build_override_map([*movies, *series])
    favorites = {
        (favorite.content_type, favorite.content_id)
        for favorite in FavoriteContent.objects.filter(user=user)
    }

    return {
        'user': user,
        'user_age': info_user.age,
        'movies': _normalize_catalog_items(
            movies,
            'movie',
            info_user,
            director_dict,
            genre_dict,
            overrides_map,
            favorites,
        ),
        'series': _normalize_catalog_items(
            series,
            'series',
            info_user,
            director_dict,
            genre_dict,
            overrides_map,
            favorites,
        ),
        'genres': genres_list,
        'directors': directors_list,
        'selected_genre': selected_genre,
        'selected_director': selected_director,
        'content_type': content_type,
        'search_query': search_query,
    }


def _record_interaction(user, content_type, content_id, interaction_type, title="", genre="", platform_name=""):
    ContentInteraction.objects.create(
        user=user,
        content_type=content_type,
        content_id=str(content_id),
        interaction_type=interaction_type,
        title=title,
        genre=genre,
        platform_name=platform_name,
    )


def _recent_api_partial_state():
    return ApiFailureEvent.objects.filter(
        is_resolved=False,
        last_seen__gte=timezone.now() - timezone.timedelta(minutes=API_PARTIAL_WINDOW_MINUTES),
    ).exists()


def _get_recent_failed_attempts(user_name, ip):
    cutoff = timezone.now() - timezone.timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES)
    subject_filter = Q()
    has_subject = False
    if user_name:
        subject_filter |= Q(user_name_attempted__iexact=user_name)
        has_subject = True
    if ip:
        subject_filter |= Q(ip_address=ip)
        has_subject = True
    if not has_subject:
        return FailedLoginAttempt.objects.none()
    return FailedLoginAttempt.objects.filter(Q(timestamp__gte=cutoff) & subject_filter)


def _build_api_filters(selected_genre="", selected_director="", search_query=""):
    return {
        key: value
        for key, value in {
            'genre': selected_genre,
            'director': selected_director,
            'title': search_query,
        }.items()
        if value
    }


def _fetch_catalog_content(content_type, api_filters):
    movies = []
    series = []
    try:
        if content_type in ['all', 'movies']:
            movies = StreamApiService.get_movies(api_filters)
        if content_type in ['all', 'series']:
            series = StreamApiService.get_series(api_filters)
    except Exception as exc:
        logger.warning("Error fetching content from Stream APIs: %s", exc)
    return movies, series


def _get_detail_reference_data(item):
    genres_list = StreamApiService.get_genres()
    directors_list = StreamApiService.get_directors()
    return (
        {str(gid): gname for gid, gname in genres_list},
        {str(did): dname for did, dname in directors_list},
        ContentImageService.build_override_map([item]),
    )


def _build_recommendations(content_type, item, info_user, genre_dict, director_dict):
    genre_filter = {'genre': item.get('genre_id')}
    candidates = (
        StreamApiService.get_movies(genre_filter)
        if content_type == 'movie'
        else StreamApiService.get_series(genre_filter)
    )
    recommendation_overrides = ContentImageService.build_override_map(candidates)
    normalized_candidates = [
        ContentCatalogService.normalize_item(
            candidate,
            content_type,
            director_dict,
            genre_dict,
            recommendation_overrides,
            AGE_RATING_MAP,
        )
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    return ContentCatalogService.build_recommendations(
        item,
        normalized_candidates,
        _parse_preferences(info_user),
    )


def _dashboard_cutoff(window):
    now = timezone.now()
    if window == '7d':
        return now - timezone.timedelta(days=7)
    if window == '30d':
        return now - timezone.timedelta(days=30)
    return None


# --- VISTES DE NAVEGACIÓ ---

def root_redirect(request):
    return redirect('home')


# --- VISTES D'USUARI ---

@never_cache
@ensure_csrf_cookie
def register(request):
    if request.method == 'POST':
        user_name = normalize_user_name(request.POST.get('user_name'))
        email = normalize_email(request.POST.get('email'))
        password = request.POST.get('password')
        address = (request.POST.get('address') or '').strip()
        language = (request.POST.get('language') or '').strip()
        age = (request.POST.get('age') or '').strip()
        sex = (request.POST.get('sex') or '').strip()
        selected_genres = [genre.strip() for genre in request.POST.getlist('genres') if genre.strip()]

        form_data = {
            'user_name': user_name,
            'email': email,
            'address': address,
            'language': language,
            'age': age,
            'sex': sex,
            'genres': selected_genres,
        }

        if not all([user_name, email, password, language, age, sex]):
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Completa todos los campos obligatorios.'),
            )

        if language not in {value for value, _ in LANGUAGE_CHOICES}:
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Selecciona un idioma válido.'),
            )

        if sex not in {value for value, _ in SEX_CHOICES}:
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Selecciona una opción válida para el género.'),
            )

        if len(set(selected_genres)) < 5:
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Selecciona al menos 5 géneros distintos.'),
            )

        invalid_genres = [genre for genre in selected_genres if genre not in InfoUser.valid_genre_values()]
        if invalid_genres:
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Se han enviado géneros no válidos.'),
            )

        if FunctionalUser.objects.filter(user_name__iexact=user_name).exists():
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Ese nombre de usuario ya está en uso.'),
            )

        if FunctionalUser.objects.filter(email__iexact=email).exists():
            return render(
                request,
                'web/register.html',
                _register_context(form_data, 'Ese email ya está registrado.'),
            )

        try:
            validate_password(password)
            with transaction.atomic():
                user = FunctionalUser.objects.create(
                    user_name=user_name,
                    email=email,
                    password=make_password(password),
                    rank='final-user',
                )

                InfoUser.objects.create(
                    user=user,
                    address=address,
                    language=language,
                    age=age,
                    sex=sex,
                    preferences=','.join(selected_genres),
                )
        except ValidationError as exc:
            return render(
                request,
                'web/register.html',
                _register_context(form_data, _extract_error_message(exc)),
            )

        return redirect('login')

    return render(request, 'web/register.html', _register_context())


@never_cache
@ensure_csrf_cookie
def login_view(request):
    if request.method == 'POST':
        user_name = normalize_user_name(request.POST.get('user_name', ''))
        password = request.POST.get('password', '')
        ip = _get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:512]
        invalid_credentials_message = 'Credenciales no válidas.'

        if _get_recent_failed_attempts(user_name, ip).count() >= LOGIN_FAILURE_LIMIT:
            return render(
                request,
                'web/login.html',
                {'error': 'Demasiados intentos fallidos. Espera unos minutos antes de volver a intentarlo.'},
            )

        try:
            user = FunctionalUser.objects.get(user_name__iexact=user_name)

            if not user.is_active:
                FailedLoginAttempt.objects.create(
                    user_name_attempted=user_name,
                    ip_address=ip,
                    user_agent=user_agent,
                    reason='account_inactive',
                )
                return render(request, 'web/login.html', {'error': invalid_credentials_message})

            if check_password(password, user.password):
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                request.session['user_id'] = user.id
                request.session.set_expiry(60 * 60 * 12)
                return redirect('home')

            FailedLoginAttempt.objects.create(
                user_name_attempted=user_name,
                ip_address=ip,
                user_agent=user_agent,
                reason='wrong_password',
            )
            return render(request, 'web/login.html', {'error': invalid_credentials_message})

        except FunctionalUser.DoesNotExist:
            FailedLoginAttempt.objects.create(
                user_name_attempted=user_name,
                ip_address=ip,
                user_agent=user_agent,
                reason='user_not_found',
            )
            return render(request, 'web/login.html', {'error': invalid_credentials_message})

    return render(request, 'web/login.html')


def home(request):
    user, info_user, redirect_response = _get_user_profile_or_redirect(request)
    if redirect_response:
        return redirect_response

    selected_genre = request.GET.get('genre', '')
    selected_director = request.GET.get('director', '')
    content_type = request.GET.get('type', 'all')
    search_query = request.GET.get('title', '')
    api_filters = _build_api_filters(selected_genre, selected_director, search_query)

    genres_list = StreamApiService.get_genres()
    directors_list = StreamApiService.get_directors()
    movies, series = _fetch_catalog_content(content_type, api_filters)

    context = _build_catalog_context(
        user,
        info_user,
        movies,
        series,
        genres_list,
        directors_list,
        selected_genre,
        selected_director,
        content_type,
        search_query,
    )
    context['api_partial'] = _recent_api_partial_state()
    return render(request, 'web/home.html', context)


def content_detail(request, content_type, content_id):
    user, info_user, redirect_response = _get_user_profile_or_redirect(request)
    if redirect_response:
        return redirect_response

    if content_type not in VALID_CONTENT_TYPES:
        return redirect('home')

    item = StreamApiService.get_content_detail(content_type, content_id)
    if not item:
        return render(request, 'web/content_detail.html', {'user': user, 'content': None}, status=404)

    genre_dict, director_dict, overrides_map = _get_detail_reference_data(item)
    content = ContentCatalogService.normalize_item(
        item,
        content_type,
        director_dict,
        genre_dict,
        overrides_map,
        AGE_RATING_MAP,
    )
    _apply_age_gate(content, info_user.age, item.get('age_rating_id'))

    content['is_favorite'] = FavoriteContent.objects.filter(
        user=user,
        content_type=content_type,
        content_id=str(content_id),
    ).exists()
    content['recommendations'] = _build_recommendations(
        content_type,
        item,
        info_user,
        genre_dict,
        director_dict,
    )

    _record_interaction(
        user,
        content_type,
        content_id,
        'view',
        title=content['title'],
        genre=content['genre_description'],
        platform_name=content['platform_name'],
    )
    return render(request, 'web/content_detail.html', {'user': user, 'content': content, 'api_partial': _recent_api_partial_state()})


def toggle_favorite(request, content_type, content_id):
    user, redirect_response = _get_logged_in_user_or_redirect(request)
    if redirect_response:
        return redirect_response
    if request.method != 'POST' or content_type not in VALID_CONTENT_TYPES:
        return redirect('home')

    favorite = FavoriteContent.objects.filter(user=user, content_type=content_type, content_id=str(content_id)).first()
    next_url = request.POST.get('next') or reverse('favorites')
    if favorite:
        title = favorite.title
        genre = favorite.genre
        platform_name = favorite.platform_name
        favorite.delete()
        _record_interaction(user, content_type, content_id, 'favorite_remove', title=title, genre=genre, platform_name=platform_name)
        return redirect(next_url)

    FavoriteContent.objects.create(
        user=user,
        content_type=content_type,
        content_id=str(content_id),
        title=request.POST.get('title') or 'Sin título',
        genre=request.POST.get('genre') or '',
        platform_name=request.POST.get('platform_name') or '',
        platform_url=request.POST.get('platform_url') or '',
        content_image_url=request.POST.get('image_url') or '',
    )
    _record_interaction(
        user,
        content_type,
        content_id,
        'favorite_add',
        title=request.POST.get('title') or 'Sin título',
        genre=request.POST.get('genre') or '',
        platform_name=request.POST.get('platform_name') or '',
    )
    return redirect(next_url)


def favorites(request):
    user, redirect_response = _get_logged_in_user_or_redirect(request)
    if redirect_response:
        return redirect_response

    favorites_qs = FavoriteContent.objects.filter(user=user).order_by('-created_at')
    return render(request, 'web/favorites.html', {'user': user, 'favorites': favorites_qs, 'api_partial': _recent_api_partial_state()})


def dashboard(request):
    user, redirect_response = _get_logged_in_user_or_redirect(request)
    if redirect_response:
        return redirect_response
    if not _is_internal_user(request, user):
        return redirect('home')

    window = request.GET.get('window', 'total')
    cutoff = _dashboard_cutoff(window)

    interactions = ContentInteraction.objects.all()
    favorites_qs = FavoriteContent.objects.all()
    api_failures = ApiFailureEvent.objects.filter(is_resolved=False)
    if cutoff:
        interactions = interactions.filter(timestamp__gte=cutoff)
        favorites_qs = favorites_qs.filter(created_at__gte=cutoff)
        api_failures = api_failures.filter(last_seen__gte=cutoff)

    user_languages = list(
        InfoUser.objects.values('language').annotate(total=Count('user')).order_by('-total')
    )
    genre_metrics = list(
        interactions.exclude(genre='').values('genre').annotate(total=Count('id')).order_by('-total')[:8]
    )
    platform_metrics = list(
        favorites_qs.exclude(platform_name='').values('platform_name').annotate(total=Count('id')).order_by('-total')[:8]
    )

    unresolved_count = api_failures.count()
    if unresolved_count == 0:
        service_status = ('green', 'Operativo')
    elif unresolved_count <= 3:
        service_status = ('yellow', 'Con incidencias')
    else:
        service_status = ('red', 'Degradado')

    context = {
        'user': user,
        'window': window,
        'user_languages': user_languages,
        'genre_metrics': genre_metrics,
        'platform_metrics': platform_metrics,
        'service_status': service_status,
        'unresolved_api_failures': unresolved_count,
        'recent_api_failures': api_failures.order_by('-last_seen')[:10],
        'favorite_total': favorites_qs.count(),
        'interaction_total': interactions.count(),
    }
    return render(request, 'web/dashboard.html', context)


def dashboard_export_csv(request, dataset):
    user, redirect_response = _get_logged_in_user_or_redirect(request)
    if redirect_response:
        return redirect_response
    if not _is_internal_user(request, user):
        return redirect('home')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{dataset}.csv"'
    writer = csv.writer(response)

    if dataset == 'favorites':
        writer.writerow(['user_name', 'content_type', 'content_id', 'title', 'genre', 'platform_name', 'created_at'])
        for item in FavoriteContent.objects.select_related('user').order_by('-created_at'):
            writer.writerow([item.user.user_name, item.content_type, item.content_id, item.title, item.genre, item.platform_name, item.created_at.isoformat()])
        return response

    if dataset == 'interactions':
        writer.writerow(['user_name', 'interaction_type', 'content_type', 'content_id', 'title', 'genre', 'platform_name', 'timestamp'])
        for item in ContentInteraction.objects.select_related('user').order_by('-timestamp'):
            writer.writerow([item.user.user_name, item.interaction_type, item.content_type, item.content_id, item.title, item.genre, item.platform_name, item.timestamp.isoformat()])
        return response

    writer.writerow(['user_name', 'language', 'age', 'rank', 'is_active'])
    for profile in InfoUser.objects.select_related('user').order_by('user__user_name'):
        writer.writerow([profile.user.user_name, profile.language, profile.age, profile.user.rank, profile.user.is_active])
    return response
