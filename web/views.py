import logging

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils import timezone
from django.shortcuts import render, redirect

from .models import (
    FailedLoginAttempt,
    FunctionalUser,
    InfoUser,
    MovieImageOverride,
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


def _get_item_image_url(item, overrides_map):
    item_id = str(item.get('id') or item.get('movie_id') or "").strip()
    override = overrides_map.get(item_id)
    if override and override.manual_image:
        return override.manual_image.url

    for key in ('image_url', 'poster_url', 'poster', 'image', 'thumbnail_url', 'cover_url'):
        value = item.get(key)
        if value:
            return value
    return ""


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
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = FunctionalUser.objects.get(id=user_id)

        # Bloqueig si l'usuari ha estat desactivat mentre tenia sessió oberta
        if not user.is_active:
            request.session.flush()
            return redirect('login')

        info_user = InfoUser.objects.get(user=user)
        user_age = info_user.age

        selected_genre = request.GET.get('genre', '')
        selected_director = request.GET.get('director', '')
        content_type = request.GET.get('type', 'all')
        search_query = request.GET.get('title', '')

        api_filters = {}
        if selected_genre:
            api_filters['genre'] = selected_genre
        if selected_director:
            api_filters['director'] = selected_director
        if search_query:
            api_filters['title'] = search_query

        genres_list = StreamApiService.get_genres()
        directors_list = StreamApiService.get_directors()

        genre_dict = {str(gid): gname for gid, gname in genres_list}
        director_dict = {str(did): dname for did, dname in directors_list}

        movies = []
        series = []
        try:
            if content_type in ['all', 'movies']:
                movies = StreamApiService.get_movies(api_filters)
            if content_type in ['all', 'series']:
                series = StreamApiService.get_series(api_filters)
        except Exception as e:
            logger.warning("Error fetching content from Stream APIs: %s", e)

        item_ids = {
            str(item.get('id') or item.get('movie_id'))
            for item in [*movies, *series]
            if isinstance(item, dict) and (item.get('id') or item.get('movie_id'))
        }
        overrides_map = {
            override.movie_id: override
            for override in MovieImageOverride.objects.filter(movie_id__in=item_ids).exclude(manual_image='')
        }

        def clean_items(items):
            if not items or not isinstance(items, list):
                return []
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue

                d_id = str(item.get('director_id'))
                item['director_name'] = director_dict.get(d_id, "Director Desconocido")

                g_id = str(item.get('genre_id'))
                item['genre_description'] = genre_dict.get(g_id, "General")

                ar_id = item.get('age_rating_id', 1)
                min_age_required = AGE_RATING_MAP.get(ar_id, 0)

                if user_age < min_age_required:
                    item['is_blocked'] = True
                    item['block_message'] = f"Contenido para +{min_age_required} años"
                else:
                    item['is_blocked'] = False

                item['title'] = item.get('title') or item.get('name') or "Sin título"
                item['image_url'] = _get_item_image_url(item, overrides_map)
                result.append(item)
            return result

        context = {
            'user': user,
            'user_age': user_age,
            'movies': clean_items(movies),
            'series': clean_items(series),
            'genres': genres_list,
            'directors': directors_list,
            'selected_genre': selected_genre,
            'selected_director': selected_director,
            'content_type': content_type,
            'search_query': search_query,
        }
        return render(request, 'web/home.html', context)

    except (FunctionalUser.DoesNotExist, InfoUser.DoesNotExist):
        return redirect('login')
