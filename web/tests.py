import requests
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import ApiFailureEvent, ContentInteraction, FavoriteContent, FailedLoginAttempt, FunctionalUser, InfoUser, MovieImageOverride
from .services import StreamApiService


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
