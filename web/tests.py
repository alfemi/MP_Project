from django.test import TestCase, Client
from django.urls import reverse
from .models import FunctionalUser, InfoUser
from django.contrib.auth.hashers import check_password

class RegistrationGenreTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.register_url = reverse('register')

    def test_registration_with_less_than_5_genres_fails(self):
        """Test that registration fails if less than 5 genres are selected."""
        data = {
            'user_name': 'testuser',
            'email': 'test@example.com',
            'password': 'password123',
            'address': 'Test Address',
            'language': 'Català',
            'age': 25,
            'sex': 'male',
            'genres': ['Action', 'Comedy', 'Drama', 'Horror'] # Only 4
        }
        response = self.client.post(self.register_url, data)
        
        # Should stay on register page and show error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Heu de seleccionar almenys 5 gèneres.')
        
        # User should not be created
        self.assertFalse(FunctionalUser.objects.filter(user_name='testuser').exists())

    def test_registration_with_5_or_more_genres_succeeds(self):
        """Test that registration succeeds with 5 or more genres."""
        data = {
            'user_name': 'testuser_ok',
            'email': 'test_ok@example.com',
            'password': 'password123',
            'address': 'Test Address',
            'language': 'Català',
            'age': 25,
            'sex': 'male',
            'genres': ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi'] # Exactly 5
        }
        response = self.client.post(self.register_url, data)
        
        # Should redirect to login
        self.assertRedirects(response, reverse('login'))
        
        # User should be created
        user = FunctionalUser.objects.get(user_name='testuser_ok')
        self.assertEqual(user.email, 'test_ok@example.com')
        self.assertTrue(check_password('password123', user.password))
        
        # InfoUser should be created with correct preferences
        info = InfoUser.objects.get(user=user)
        self.assertEqual(info.preferences, 'Action,Comedy,Drama,Horror,Sci-Fi')

    def test_registration_with_many_genres_succeeds(self):
        """Test that registration succeeds with more than 5 genres."""
        genres = ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi', 'Fantasy', 'Romance']
        data = {
            'user_name': 'testuser_many',
            'email': 'test_many@example.com',
            'password': 'password123',
            'address': 'Test Address',
            'language': 'Català',
            'age': 30,
            'sex': 'female',
            'genres': genres
        }
        response = self.client.post(self.register_url, data)
        
        self.assertRedirects(response, reverse('login'))
        
        user = FunctionalUser.objects.get(user_name='testuser_many')
        info = InfoUser.objects.get(user=user)
        self.assertEqual(info.preferences, ','.join(genres))

    def test_missing_required_fields_fails(self):
        """Test that registration fails if required fields are missing."""
        data = {
            'user_name': 'testuser_missing',
            # email missing
            'password': 'password123',
            'address': 'Test Address',
            'language': 'Català',
            'age': 25,
            'sex': 'male',
            'genres': ['Action', 'Comedy', 'Drama', 'Horror', 'Sci-Fi']
        }
        response = self.client.post(self.register_url, data)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'S’han d’omplir tots els camps obligatoris.')
        self.assertFalse(FunctionalUser.objects.filter(user_name='testuser_missing').exists())
