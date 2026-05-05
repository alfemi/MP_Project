import json
from pathlib import Path

import requests
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch

from django.contrib.auth.models import Group, Permission
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import ApiFailureEvent, ContentInteraction, FavoriteContent, FailedLoginAttempt, FunctionalUser, InfoUser, MovieImageOverride
from .image_resolver import ContentImageService
from .services import StreamApiService


class UserStoryCoverageFileTest(TestCase):
    def test_user_story_coverage_file_exists(self):
        coverage_path = Path(__file__).resolve().parent.parent / 'USER_STORY_COVERAGE.md'
        self.assertTrue(coverage_path.exists())
        content = coverage_path.read_text()
        self.assertIn('IE10.1', content)
        self.assertIn('IPR12.1', content)
        self.assertIn('R4.5', content)


class RegistrationValidationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.register_url = reverse('register')
        self.valid_payload = {
            'user_name': 'testuser_ok',
            'email': 'Test_OK@Example.com ',
            'password': 'StrongPassword123!',
            'address': '',
            'language': 'ca',
            'age': '25',
            'sex': 'male',
            'genres': ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi'],
            'terms': '1',
        }

    def test_registration_with_less_than_5_genres_fails(self):
        payload = self.valid_payload | {'user_name': 'shortgenres', 'email': 'short@example.com', 'genres': ['Action', 'Comedy', 'Drama', 'Horror']}
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecciona al menos 5 géneros distintos.')
        self.assertFalse(FunctionalUser.objects.filter(user_name='shortgenres').exists())

    def test_registration_normalizes_email_and_creates_profile(self):
        response = self.client.post(self.register_url, self.valid_payload)

        self.assertRedirects(response, reverse('login'))

        user = FunctionalUser.objects.get(user_name='testuser_ok')
        self.assertEqual(user.email, 'test_ok@example.com')
        self.assertFalse(user.email_verified)
        self.assertTrue(check_password('StrongPassword123!', user.password))

        info = InfoUser.objects.get(user=user)
        self.assertEqual(info.language, 'ca')
        self.assertEqual(info.preferences, 'Action,Comedy,Drama,Horror,Sci-Fi')

    def test_registration_rejects_case_insensitive_duplicate_email(self):
        FunctionalUser.objects.create(
            user_name='existing',
            email='existing@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )

        payload = self.valid_payload | {'user_name': 'anotheruser', 'email': ' Existing@Example.com '}
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ese email ya está registrado.')
        self.assertFalse(FunctionalUser.objects.filter(user_name='anotheruser').exists())

    def test_registration_requires_valid_language(self):
        payload = self.valid_payload | {'user_name': 'badlanguage', 'email': 'badlanguage@example.com', 'language': 'de'}
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecciona un idioma válido.')
        self.assertFalse(FunctionalUser.objects.filter(user_name='badlanguage').exists())

    def test_register_form_sets_csrf_cookie_and_is_not_cacheable(self):
        response = self.client.get(self.register_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertIn('csrftoken', response.cookies)
        self.assertIn('no-cache', response.headers.get('Cache-Control', ''))

    def test_registration_requires_terms_acceptance(self):
        payload = self.valid_payload.copy()
        payload.pop('terms')
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Debes aceptar los términos')
        self.assertFalse(FunctionalUser.objects.filter(user_name='testuser_ok').exists())


class LoginSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')
        self.user = FunctionalUser.objects.create(
            user_name='loginuser',
            email='login@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        InfoUser.objects.create(
            user=self.user,
            address='',
            language='es',
            age=30,
            sex='male',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )

    def test_login_returns_generic_error_for_invalid_credentials(self):
        response = self.client.post(self.login_url, {'user_name': 'unknown', 'password': 'wrong'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Credenciales no válidas.')
        self.assertEqual(FailedLoginAttempt.objects.count(), 1)

    def test_login_rate_limit_blocks_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(self.login_url, {'user_name': 'loginuser', 'password': 'wrong'})

        response = self.client.post(self.login_url, {'user_name': 'loginuser', 'password': 'wrong'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Demasiados intentos fallidos.')

    def test_login_updates_last_login(self):
        response = self.client.post(self.login_url, {'user_name': 'loginuser', 'password': 'StrongPassword123!'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_login_form_sets_csrf_cookie_and_is_not_cacheable(self):
        response = self.client.get(self.login_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertIn('csrftoken', response.cookies)
        self.assertIn('no-cache', response.headers.get('Cache-Control', ''))


class PublicCatalogAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.catalog_url = reverse('catalog')
        self.genres = [('Action', 'Acción'), ('Drama', 'Drama')]
        self.directors = [('1', 'Christopher Nolan')]
        self.movie = {
            'id': 501,
            'title': 'Public Movie',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 5,
            'image_url': 'https://example.com/public-movie.jpg',
        }

    def get_catalog_response(self, movies=None, series=None):
        with patch(
            'web.views.StreamApiService.get_movies',
            return_value=movies if movies is not None else [self.movie],
        ), patch(
            'web.views.StreamApiService.get_series',
            return_value=series if series is not None else [],
        ), patch(
            'web.views.StreamApiService.get_genres',
            return_value=self.genres,
        ), patch(
            'web.views.StreamApiService.get_directors',
            return_value=self.directors,
        ):
            return self.client.get(self.catalog_url)

    def test_anonymous_user_can_access_public_catalog(self):
        response = self.get_catalog_response(movies=[], series=[])

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'web/home.html')

    def test_anonymous_user_can_access_home_catalog(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[]), patch('web.views.StreamApiService.get_directors', return_value=[]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'web/home.html')

    def test_anonymous_user_can_see_movies(self):
        response = self.get_catalog_response()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Movie')
        self.assertEqual(len(response.context['movies']), 1)

    def test_anonymous_user_can_search_and_filter_catalog(self):
        response = self.get_catalog_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['search_query'], '')
        with patch('web.views.StreamApiService.get_movies', return_value=[self.movie]) as get_movies, patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=self.genres), patch('web.views.StreamApiService.get_directors', return_value=self.directors):
            filtered = self.client.get(self.catalog_url, {'title': 'Public', 'genre': 'Action', 'director': '1', 'type': 'movies'})

        self.assertEqual(filtered.status_code, 200)
        get_movies.assert_called_with({'genre': 'Action', 'director': '1', 'title': 'Public'})
        self.assertEqual(filtered.context['search_query'], 'Public')

    def test_anonymous_navbar_shows_public_links_only(self):
        response = self.get_catalog_response(movies=[], series=[])

        self.assertContains(response, 'Iniciar sessió')
        self.assertContains(response, 'Registrar-se')
        self.assertNotContains(response, 'Favoritos')
        self.assertNotContains(response, 'Perfil')
        self.assertNotContains(response, 'Panel directores')

    def test_anonymous_user_can_access_content_detail(self):
        with patch('web.views.StreamApiService.get_content_detail', return_value={
            'id': 501,
            'title': 'Public Movie',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
            'image_url': 'https://example.com/public-movie.jpg',
            'platform_name': 'Netflix',
        }), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('content_detail', args=['movie', '501']))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Movie')
        self.assertContains(response, 'Inicia sessió per guardar')

    def test_anonymous_catalog_uses_safe_info_user_fallbacks(self):
        response = self.get_catalog_response()

        self.assertIsNone(response.context['user'])
        self.assertIsNone(response.context['user_age'])
        self.assertEqual(response.context['user_language'], '')
        self.assertEqual(response.context['user_preferences'], [])
        self.assertFalse(response.context['movies'][0]['is_blocked'])

    def test_authenticated_catalog_keeps_personalized_profile_data(self):
        user = FunctionalUser.objects.create(
            user_name='cataloguser',
            email='catalog@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        InfoUser.objects.create(
            user=user,
            address='',
            language='ca',
            age=13,
            sex='female',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = user.id
        session.save()

        response = self.get_catalog_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['user'], user)
        self.assertEqual(response.context['user_age'], 13)
        self.assertEqual(response.context['user_language'], 'ca')
        self.assertEqual(
            response.context['user_preferences'],
            ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi'],
        )
        self.assertTrue(response.context['movies'][0]['is_blocked'])

    def test_anonymous_private_actions_redirect_or_block(self):
        favorite_response = self.client.post(reverse('toggle_favorite', args=['movie', '501']), {'next': reverse('favorites')})
        favorites_response = self.client.get(reverse('favorites'))
        profile_response = self.client.get(reverse('profile'))
        director_response = self.client.get(reverse('director_dashboard'))
        export_response = self.client.get(reverse('director_dashboard_export_csv'))

        self.assertRedirects(favorite_response, reverse('login'))
        self.assertRedirects(favorites_response, reverse('login'))
        self.assertRedirects(profile_response, reverse('login'))
        self.assertRedirects(director_response, reverse('login'))
        self.assertRedirects(export_response, reverse('login'))


class MovieImageOverrideIntegrationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = FunctionalUser.objects.create(
            user_name='viewer',
            email='viewer@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        InfoUser.objects.create(
            user=self.user,
            address='',
            language='es',
            age=30,
            sex='female',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = self.user.id
        session.save()

    def tearDown(self):
        MovieImageOverride.objects.all().delete()

    def test_home_prioritizes_manual_movie_image_override(self):
        MovieImageOverride.objects.create(
            movie_id='42',
            title='Test Movie',
            manual_image=SimpleUploadedFile('poster.jpg', b'fake-image-content', content_type='image/jpeg'),
        )

        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 42,
            'title': 'Test Movie',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
            'image_url': 'https://example.com/api-image.jpg',
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertIn('/media/movie_overrides/', movie['image_url'])

    def test_home_uses_external_image_when_no_manual_override_exists(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 77,
            'title': 'External Only',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
            'image_url': 'https://example.com/external-image.jpg',
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertEqual(movie['image_url'], 'https://example.com/external-image.jpg')
        self.assertEqual(movie['image_source'], 'external')

    def test_home_falls_back_to_placeholder_when_no_image_exists(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 88,
            'title': 'No Image',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertEqual(movie['image_url'], '')
        self.assertContains(response, 'No Image')
        self.assertEqual(movie['image_source'], 'placeholder')

    def test_home_uses_title_search_image_when_api_has_no_image(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 89,
            'title': 'Search Poster',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]), patch('web.image_resolver.ExternalTitleImageSearchService.search_movie_image', return_value='https://example.com/search-image.jpg'):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertEqual(movie['image_url'], 'https://example.com/search-image.jpg')
        self.assertEqual(movie['image_source'], 'search')

    def test_home_builds_absolute_url_from_relative_image_path(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 91,
            'title': 'Relative Poster',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
            '_api_base_url': 'http://localhost:8081',
            'poster_url': '/media/posters/relative.jpg',
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertEqual(movie['image_url'], 'http://localhost:8081/media/posters/relative.jpg')
        self.assertEqual(movie['image_source'], 'external')

    def test_home_builds_tmdb_url_from_poster_path(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 92,
            'title': 'TMDB Poster',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
            'poster_path': '/abc123poster.jpg',
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        movie = response.context['movies'][0]
        self.assertEqual(movie['image_url'], 'https://image.tmdb.org/t/p/w500/abc123poster.jpg')
        self.assertEqual(movie['image_source'], 'external')

    def test_invalid_image_values_fall_back_to_placeholder(self):
        with patch('web.image_resolver.ExternalTitleImageSearchService.search_movie_image', return_value=''):
            for invalid_value in ['null', 'none', 'undefined', 'n/a', 'sin imagen', 'ftp://example.com/poster.jpg']:
                with self.subTest(invalid_value=invalid_value):
                    image_data = ContentImageService.resolve_image(
                        {'id': 700, 'title': 'Bad Image', 'image_url': invalid_value},
                        {},
                    )
                    self.assertEqual(image_data['url'], '')
                    self.assertEqual(image_data['source'], 'placeholder')

    def test_catalog_card_keeps_button_and_adds_card_hitbox(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[{
            'id': 93,
            'title': 'Clickable Card',
            'director_id': 1,
            'genre_id': 'Action',
            'age_rating_id': 1,
        }]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            response = self.client.get(reverse('home'))

        detail_url = reverse('content_detail', args=['movie', '93'])
        self.assertContains(response, 'content-card-hitbox')
        self.assertContains(response, f'href="{detail_url}" class="content-card-hitbox"')
        self.assertContains(response, 'Ver ficha')


class ContentDetailAndFavoritesTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = FunctionalUser.objects.create(
            user_name='catalog_user',
            email='catalog@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        self.info = InfoUser.objects.create(
            user=self.user,
            address='',
            language='es',
            age=30,
            sex='female',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = self.user.id
        session.save()

    def test_content_detail_renders_fallbacks_and_recommendations(self):
        with patch('web.views.StreamApiService.get_content_detail', return_value={
            'id': 12,
            'title': 'Arrival',
            'genre_id': 'Action',
            'director_id': 1,
            'age_rating_id': 3,
            'platform_name': 'Netflix',
        }), patch('web.views.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.views.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]), patch('web.views.StreamApiService.get_movies', return_value=[
            {'id': 99, 'title': 'Interstellar', 'genre_id': 'Action', 'director_id': 1, 'rating': 9.2, 'age_rating_id': 3}
        ]):
            response = self.client.get(reverse('content_detail', args=['movie', '12']))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Arrival')
        self.assertContains(response, 'Sin sinopsis disponible.')
        self.assertContains(response, 'Interstellar')
        self.assertEqual(ContentInteraction.objects.filter(interaction_type='view').count(), 1)

    def test_toggle_favorite_creates_and_removes_favorite(self):
        create_payload = {
            'title': 'Arrival',
            'genre': 'Acción',
            'platform_name': 'Netflix',
            'platform_url': '',
            'image_url': 'https://example.com/poster.jpg',
            'next': reverse('favorites'),
        }
        response = self.client.post(reverse('toggle_favorite', args=['movie', '12']), create_payload)
        self.assertRedirects(response, reverse('favorites'))
        self.assertEqual(FavoriteContent.objects.count(), 1)
        self.assertEqual(ContentInteraction.objects.filter(interaction_type='favorite_add').count(), 1)

        response = self.client.post(reverse('toggle_favorite', args=['movie', '12']), {'next': reverse('favorites')})
        self.assertRedirects(response, reverse('favorites'))
        self.assertEqual(FavoriteContent.objects.count(), 0)
        self.assertEqual(ContentInteraction.objects.filter(interaction_type='favorite_remove').count(), 1)

    def test_favorites_page_loads(self):
        FavoriteContent.objects.create(
            user=self.user,
            content_type='movie',
            content_id='12',
            title='Arrival',
            genre='Acción',
            platform_name='Netflix',
        )
        response = self.client.get(reverse('favorites'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Arrival')


class ProfileFlowTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = FunctionalUser.objects.create(
            user_name='profile_user',
            email='profile@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        self.info = InfoUser.objects.create(
            user=self.user,
            address='Old address',
            language='es',
            age=27,
            sex='female',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = self.user.id
        session.save()

    def test_profile_requires_authentication(self):
        anon_client = Client()
        response = anon_client.get(reverse('profile'))
        self.assertRedirects(response, reverse('login'))

    def test_profile_page_loads(self):
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Perfil de profile_user')
        self.assertContains(response, 'profile@example.com')

    def test_profile_update_uses_django_form_validation(self):
        response = self.client.post(
            reverse('profile'),
            {
                'action': 'update_profile',
                'email': 'updated@example.com',
                'address': 'New address',
                'language': 'ca',
                'age': '31',
                'sex': 'female',
                'preferences': ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi'],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.info.refresh_from_db()
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(self.info.language, 'ca')
        self.assertEqual(self.info.age, 31)
        self.assertContains(response, 'Perfil actualizado correctamente.')

    def test_profile_password_change_updates_password_hash(self):
        response = self.client.post(
            reverse('profile'),
            {
                'action': 'change_password',
                'old_password': 'StrongPassword123!',
                'new_password': 'EvenStrongerPassword456!',
                'confirm_password': 'EvenStrongerPassword456!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(check_password('EvenStrongerPassword456!', self.user.password))
        self.assertContains(response, 'Contraseña actualizada correctamente.')

    def test_logout_clears_session_and_redirects(self):
        response = self.client.get(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('user_id', self.client.session)


class ApiFailureObservabilityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = FunctionalUser.objects.create(
            user_name='apiwatcher',
            email='apiwatcher@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        InfoUser.objects.create(
            user=self.user,
            address='',
            language='es',
            age=30,
            sex='male',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = self.user.id
        session.save()

    def test_api_timeout_is_logged(self):
        with patch('web.services.requests.get', side_effect=requests.exceptions.Timeout('timed out')):
            data = StreamApiService.get_movies()

        self.assertEqual(data, [])
        self.assertEqual(ApiFailureEvent.objects.count(), 3)
        event = ApiFailureEvent.objects.order_by('provider_name').first()
        self.assertEqual(event.operation, 'movies')
        self.assertEqual(event.error_type, 'timeout')
        self.assertEqual(event.severity, 'high')
        self.assertEqual(event.occurrences, 1)
        self.assertFalse(event.is_resolved)

    def test_http_error_is_logged(self):
        mock_response = Mock(status_code=503, text='Service unavailable')
        with patch('web.services.requests.get', return_value=mock_response):
            data = StreamApiService.get_genres()

        self.assertEqual(data, [])
        self.assertEqual(ApiFailureEvent.objects.count(), 3)
        event = ApiFailureEvent.objects.order_by('provider_name').first()
        self.assertEqual(event.status_code, 503)
        self.assertEqual(event.error_type, 'http_error')
        self.assertEqual(event.severity, 'critical')
        self.assertIn('Service unavailable', event.response_excerpt)

    def test_home_degrades_gracefully_when_apis_fail(self):
        with patch('web.services.requests.get', side_effect=requests.exceptions.ConnectionError('down')):
            response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['movies'], [])
        self.assertEqual(response.context['series'], [])
        self.assertGreaterEqual(ApiFailureEvent.objects.count(), 1)


class AdminSmokeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='AdminPassword123!',
        )
        self.client.force_login(self.admin_user)

        self.functional_user = FunctionalUser.objects.create(
            user_name='admin_target',
            email='target@example.com',
            password=make_password('StrongPassword123!'),
            rank='final-user',
        )
        self.info_user = InfoUser.objects.create(
            user=self.functional_user,
            address='Demo street',
            language='es',
            age=29,
            sex='male',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        self.failed_attempt = FailedLoginAttempt.objects.create(
            user_name_attempted='admin_target',
            ip_address='127.0.0.1',
            user_agent='test-agent',
            reason='wrong_password',
        )
        self.movie_override = MovieImageOverride.objects.create(
            movie_id='999',
            title='Admin Preview Movie',
            manual_image=SimpleUploadedFile('admin-poster.jpg', b'fake-image-content', content_type='image/jpeg'),
        )
        self.api_failure_event = ApiFailureEvent.objects.create(
            provider_name='localhost:8080',
            base_url='http://localhost:8080',
            operation='movies',
            status_code=503,
            severity='critical',
            error_type='http_error',
            error_message='HTTP 503 returned by provider.',
            response_excerpt='Service unavailable',
        )
        self.favorite = FavoriteContent.objects.create(
            user=self.functional_user,
            content_type='movie',
            content_id='11',
            title='Saved movie',
            genre='Action',
            platform_name='Netflix',
        )
        self.interaction = ContentInteraction.objects.create(
            user=self.functional_user,
            content_type='movie',
            content_id='11',
            interaction_type='view',
            title='Saved movie',
            genre='Action',
            platform_name='Netflix',
        )

    def test_admin_changelists_load(self):
        urls = [
            reverse('admin:web_functionaluser_changelist'),
            reverse('admin:web_infouser_changelist'),
            reverse('admin:web_failedloginattempt_changelist'),
            reverse('admin:web_movieimageoverride_changelist'),
            reverse('admin:web_apifailureevent_changelist'),
            reverse('admin:web_favoritecontent_changelist'),
            reverse('admin:web_contentinteraction_changelist'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, msg=f'Admin changelist failed: {url}')

    def test_admin_change_views_load(self):
        objects_and_urls = [
            (self.functional_user, 'admin:web_functionaluser_change'),
            (self.info_user, 'admin:web_infouser_change'),
            (self.failed_attempt, 'admin:web_failedloginattempt_change'),
            (self.movie_override, 'admin:web_movieimageoverride_change'),
            (self.api_failure_event, 'admin:web_apifailureevent_change'),
            (self.favorite, 'admin:web_favoritecontent_change'),
            (self.interaction, 'admin:web_contentinteraction_change'),
        ]
        for obj, url_name in objects_and_urls:
            response = self.client.get(reverse(url_name, args=[obj.pk]))
            self.assertEqual(response.status_code, 200, msg=f'Admin change view failed: {url_name}')


class DirectorDashboardAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.permission = Permission.objects.get(
            codename='can_view_director_dashboard',
            content_type=ContentType.objects.get_for_model(FunctionalUser),
        )
        self.directors_group = Group.objects.get(name='Directors')
        self.normal_user = self.create_functional_user('normal_director_test')
        self.director_user = self.create_functional_user('director_test')
        self.permission_user = self.create_functional_user('permission_director_test')
        self.permission_group_user = self.create_functional_user('permission_group_director_test')
        self.internal_user = self.create_functional_user('internal_director_test', rank='sysadmin')
        self.permission_group = Group.objects.create(name='Strategic Reporting')
        self.permission_group.permissions.add(self.permission)
        self.director_user.groups.add(self.directors_group)
        self.permission_user.user_permissions.add(self.permission)
        self.permission_group_user.groups.add(self.permission_group)

    def create_functional_user(self, user_name, rank='final-user'):
        user = FunctionalUser.objects.create(
            user_name=user_name,
            email=f'{user_name}@example.com',
            password=make_password('StrongPassword123!'),
            rank=rank,
        )
        InfoUser.objects.create(
            user=user,
            address='',
            language='es',
            age=30,
            sex='male',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        return user

    def login_functional_user(self, user):
        session = self.client.session
        session['user_id'] = user.id
        session.save()

    def get_director_response(self, client=None, movies=None, series=None):
        active_client = client or self.client
        with patch('web.analytics.StreamApiService.get_movies', return_value=movies if movies is not None else []), patch('web.analytics.StreamApiService.get_series', return_value=series if series is not None else []), patch('web.analytics.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.analytics.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            return active_client.get(reverse('director_dashboard'))

    def get_director_export_response(self, client=None, movies=None, series=None):
        active_client = client or self.client
        with patch('web.analytics.StreamApiService.get_movies', return_value=movies if movies is not None else []), patch('web.analytics.StreamApiService.get_series', return_value=series if series is not None else []), patch('web.analytics.StreamApiService.get_genres', return_value=[('Action', 'Acción')]), patch('web.analytics.StreamApiService.get_directors', return_value=[('1', 'Christopher Nolan')]):
            return active_client.get(reverse('director_dashboard_export_csv'))

    def test_directors_group_is_created_with_permission(self):
        self.assertTrue(self.directors_group.permissions.filter(pk=self.permission.pk).exists())
        self.assertFalse(self.normal_user.groups.filter(name='Directors').exists())
        self.assertFalse(
            self.normal_user.user_permissions.filter(codename='can_view_director_dashboard').exists()
        )

    def test_anonymous_director_dashboard_redirects_to_login(self):
        response = self.get_director_response()
        self.assertRedirects(response, reverse('login'))

    def test_normal_user_cannot_access_director_dashboard(self):
        self.login_functional_user(self.normal_user)
        response = self.get_director_response()
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'KPIs del catálogo', status_code=403)

    def test_normal_user_cannot_access_director_export(self):
        self.login_functional_user(self.normal_user)
        response = self.get_director_export_response()
        self.assertEqual(response.status_code, 403)

    def test_directors_group_user_can_access_director_dashboard(self):
        self.login_functional_user(self.director_user)
        response = self.get_director_response(movies=[{
            'id': 1,
            'title': 'Director Movie',
            'genre_id': 'Action',
            'director_id': 1,
            'rating': 8.4,
            'platform_name': 'Netflix',
            'platform_url': 'https://example.com/watch',
            'image_url': 'https://example.com/poster.jpg',
        }])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Panel de direcció')
        self.assertContains(response, 'Director Movie')
        self.assertContains(response, 'Informe estratègic')
        self.assertContains(response, 'Informe periòdic de rendiment')

    def test_directors_group_user_can_access_without_group_permission(self):
        self.directors_group.permissions.remove(self.permission)
        self.login_functional_user(self.director_user)
        response = self.get_director_response()
        self.assertEqual(response.status_code, 200)

    def test_permission_user_can_access_director_dashboard(self):
        self.login_functional_user(self.permission_user)
        response = self.get_director_response()
        self.assertEqual(response.status_code, 200)

    def test_director_user_can_access_csv_export_without_private_fields(self):
        self.login_functional_user(self.director_user)
        response = self.get_director_export_response(movies=[{
            'id': 22,
            'title': 'CSV Movie',
            'genre_id': 'Action',
            'director_id': 1,
            'platform_name': 'Netflix',
        }])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        body = response.content.decode()
        self.assertIn('dimension,label,count,period,source,status', body)
        self.assertIn('CSV Movie', body)
        self.assertNotIn('email', body.lower())
        self.assertNotIn('password', body.lower())
        self.assertNotIn('address', body.lower())

    def test_user_in_group_with_director_permission_can_access_dashboard(self):
        self.login_functional_user(self.permission_group_user)
        response = self.get_director_response()
        self.assertEqual(response.status_code, 200)

    def test_internal_functional_user_can_access_director_dashboard(self):
        self.login_functional_user(self.internal_user)
        response = self.get_director_response()
        self.assertEqual(response.status_code, 200)

    def test_django_superuser_can_access_director_dashboard(self):
        super_client = Client()
        admin_user = get_user_model().objects.create_superuser(
            username='director_admin',
            email='director-admin@example.com',
            password='AdminPassword123!',
        )
        super_client.force_login(admin_user)
        response = self.get_director_response(client=super_client)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Panel directores')

    def test_director_dashboard_handles_empty_catalog(self):
        self.login_functional_user(self.director_user)
        response = self.get_director_response(movies=[], series=[])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Catàleg total')
        self.assertContains(response, 'No disponible: el perfil d&#x27;usuari encara no registra nacionalitat o país/regió')
        self.assertContains(response, 'No disponible: no hi ha dades de subscripcions declarades')
        self.assertContains(response, 'Informe estratègic')
        self.assertContains(response, 'Informe periòdic de rendiment')

    def test_director_dashboard_chart_json_is_valid(self):
        self.login_functional_user(self.director_user)
        FavoriteContent.objects.create(
            user=self.director_user,
            content_type='movie',
            content_id='1',
            title='Favorite Movie',
            genre='Action',
            platform_name='Netflix',
        )
        ContentInteraction.objects.create(
            user=self.director_user,
            content_type='movie',
            content_id='1',
            interaction_type='view',
            title='Favorite Movie',
            genre='Action',
            platform_name='Netflix',
        )
        response = self.get_director_response(movies=[{
            'id': 1,
            'title': 'Favorite Movie',
            'genre_id': 'Action',
            'director_id': 1,
            'rating': 7.5,
            'platform_name': 'Netflix',
            'platform_url': 'https://example.com/watch',
            'image_url': 'https://example.com/poster.jpg',
        }])
        self.assertEqual(response.status_code, 200)
        for script_id in [
            'demographic-chart-data',
            'genre-chart-data',
            'platform-chart-data',
            'quality-chart-data',
        ]:
            self.assertContains(response, f'id="{script_id}"')
        genre_data = json.loads(json.dumps(response.context['genre_chart']))
        self.assertEqual(genre_data['labels'], ['Action'])
        self.assertEqual(genre_data['values'], [1])
        self.assertContains(response, 'Distribució del catàleg per proveïdor, no subscripcions d&#x27;usuari.')
        self.assertContains(response, 'Tendència temporal')

    def test_director_nav_visibility_follows_access(self):
        with patch('web.views.StreamApiService.get_movies', return_value=[]), patch('web.views.StreamApiService.get_series', return_value=[]), patch('web.views.StreamApiService.get_genres', return_value=[]), patch('web.views.StreamApiService.get_directors', return_value=[]):
            self.login_functional_user(self.normal_user)
            normal_response = self.client.get(reverse('home'))
            self.assertFalse(normal_response.context['can_access_director_dashboard'])
            self.assertNotContains(normal_response, 'Panel directores')

            self.login_functional_user(self.director_user)
            director_response = self.client.get(reverse('home'))
            self.assertTrue(director_response.context['can_access_director_dashboard'])
            self.assertContains(director_response, 'Panel directores')


class DashboardAndExportTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = FunctionalUser.objects.create(
            user_name='ops_user',
            email='ops@example.com',
            password=make_password('StrongPassword123!'),
            rank='sysadmin',
        )
        InfoUser.objects.create(
            user=self.user,
            address='',
            language='ca',
            age=34,
            sex='male',
            preferences='Action,Comedy,Drama,Horror,Sci-Fi',
        )
        session = self.client.session
        session['user_id'] = self.user.id
        session.save()
        FavoriteContent.objects.create(
            user=self.user,
            content_type='movie',
            content_id='1',
            title='Arrival',
            genre='Action',
            platform_name='Netflix',
        )
        ContentInteraction.objects.create(
            user=self.user,
            content_type='movie',
            content_id='1',
            interaction_type='view',
            title='Arrival',
            genre='Action',
            platform_name='Netflix',
        )
        ApiFailureEvent.objects.create(
            provider_name='localhost:8080',
            base_url='http://localhost:8080',
            operation='movies',
            status_code=503,
            severity='critical',
            error_type='http_error',
            error_message='HTTP 503',
        )

    def test_dashboard_loads_for_internal_user(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard operativo y negocio')
        self.assertContains(response, 'Netflix')

    def test_dashboard_csv_export_works(self):
        response = self.client.get(reverse('dashboard_export_csv', args=['favorites']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Arrival', response.content.decode())
