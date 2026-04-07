from django.db import models

from django.db import models

class FunctionalUser(models.Model):
    user_name = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)
    email = models.EmailField(unique=True)
    
    RANK_CHOICES = [
        ('final-user', 'Final User'),
        ('sysadmin', 'Sysadmin'),
        ('finance', 'Finance'),
    ]
    rank = models.CharField(max_length=20, choices=RANK_CHOICES)

    # Placeholder for future platform API keys
    # You can add fields like:
    # platform_a_api_key = models.CharField(max_length=255, blank=True, null=True)
    # platform_b_api_key = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.user_name

class InfoUser(models.Model):
    user = models.OneToOneField(FunctionalUser, on_delete=models.CASCADE, primary_key=True)
    address = models.CharField(max_length=255)
    language = models.CharField(max_length=50)
    age = models.PositiveIntegerField()

    SEX_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]
    sex = models.CharField(max_length=10, choices=SEX_CHOICES)

    # Preferences
    preferences = models.TextField(blank=True, help_text="Sèries i gèneres preferits")

    def __str__(self):
        return f"Info for {self.user.user_name}"

