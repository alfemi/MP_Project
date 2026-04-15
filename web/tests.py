from django.contrib.auth import get_user_model
from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .models import FailedLoginAttempt, FunctionalUser, InfoUser, MovieImageOverride


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

    def test_admin_changelists_load(self):
        urls = [
            reverse('admin:web_functionaluser_changelist'),
            reverse('admin:web_infouser_changelist'),
            reverse('admin:web_failedloginattempt_changelist'),
            reverse('admin:web_movieimageoverride_changelist'),
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
        ]
        for obj, url_name in objects_and_urls:
            response = self.client.get(reverse(url_name, args=[obj.pk]))
            self.assertEqual(response.status_code, 200, msg=f'Admin change view failed: {url_name}')
