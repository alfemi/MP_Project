import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_user_name(value):
    return (value or "").strip()


class FunctionalUser(models.Model):
    user_name = models.CharField(
        max_length=150,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Za-z0-9_.-]+$",
                message="El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos.",
            )
        ],
    )
    password = models.CharField(max_length=128)
    email = models.EmailField(unique=True)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email_verified = models.BooleanField(default=False)

    RANK_CHOICES = [
        ('final-user', 'Usuario Final'),
        ('sysadmin', 'Administrador'),
        ('finance', 'Finanzas'),
    ]
    rank = models.CharField(max_length=20, choices=RANK_CHOICES)

    # Account status & audit fields
    is_active = models.BooleanField(default=True, help_text="Desactiva este usuario para bloquearlo sin eliminarlo.")
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    def clean(self):
        self.user_name = normalize_user_name(self.user_name)
        self.email = normalize_email(self.email)

        if not self.user_name:
            raise ValidationError({'user_name': "El nombre de usuario es obligatorio."})
        if not self.email:
            raise ValidationError({'email': "El email es obligatorio."})

    def save(self, *args, **kwargs):
        self.user_name = normalize_user_name(self.user_name)
        self.email = normalize_email(self.email)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.user_name

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ['-date_joined']
        constraints = [
            models.UniqueConstraint(
                Lower('user_name'),
                name='functionaluser_username_ci_unique',
            ),
            models.UniqueConstraint(
                Lower('email'),
                name='functionaluser_email_ci_unique',
            ),
        ]


class InfoUser(models.Model):
    LANGUAGE_CHOICES = [
        ('ca', 'Català'),
        ('es', 'Español'),
        ('en', 'English'),
        ('fr', 'Français'),
    ]

    user = models.OneToOneField(FunctionalUser, on_delete=models.CASCADE, primary_key=True)
    address = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='es')
    age = models.PositiveIntegerField(validators=[MinValueValidator(13), MaxValueValidator(120)])

    SEX_CHOICES = [
        ('male', 'Hombre'),
        ('female', 'Mujer'),
    ]
    sex = models.CharField(max_length=10, choices=SEX_CHOICES)

    GENRE_CHOICES = [
        ('Action', '💥 Acción'),
        ('Comedy', '😂 Comedia'),
        ('Drama', '🎭 Drama'),
        ('Horror', '👻 Terror'),
        ('Sci-Fi', '🚀 Ciencia Ficción'),
        ('Fantasy', '🧙‍♂️ Fantasía'),
        ('Romance', '❤️ Romance'),
        ('Thriller', '🔪 Suspenso'),
        ('Animation', '🧸 Animación'),
        ('Documentary', '📹 Documental'),
        ('Mystery', '🔍 Misterio'),
        ('Adventure', '🗺️ Aventura'),
        ('Crime', '🕵️‍♂️ Crimen'),
        ('Biography', '📚 Biografía'),
        ('History', '🏛️ Historia'),
        ('Music', '🎵 Música'),
        ('Musical', '💃 Musical'),
        ('War', '🎖️ Guerra'),
        ('Sport', '⚽ Deporte'),
        ('Western', '🤠 Oeste'),
    ]
    preferences = models.TextField(blank=True, help_text="Géneros cinematográficos seleccionados (mínimo 5)")

    @classmethod
    def valid_genre_values(cls):
        return {value for value, _ in cls.GENRE_CHOICES}

    @classmethod
    def parse_preferences(cls, preferences):
        return [item.strip() for item in (preferences or "").split(',') if item.strip()]

    def clean(self):
        preferences = self.parse_preferences(self.preferences)
        invalid_preferences = [value for value in preferences if value not in self.valid_genre_values()]
        if invalid_preferences:
            raise ValidationError({'preferences': "Hay géneros no válidos en las preferencias."})
        if preferences and len(set(preferences)) < 5:
            raise ValidationError({'preferences': "Debes seleccionar al menos 5 géneros distintos."})

    def save(self, *args, **kwargs):
        self.address = (self.address or "").strip()
        self.preferences = ",".join(dict.fromkeys(self.parse_preferences(self.preferences)))
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Información para {self.user.user_name}"

    class Meta:
        verbose_name = "Información de usuario"
        verbose_name_plural = "Información de usuarios"


class FailedLoginAttempt(models.Model):
    """Registro de intentos de login fallidos para seguridad y auditoría."""
    user_name_attempted = models.CharField(
        max_length=150,
        blank=True,
        db_index=True,
        help_text="Nombre de usuario introducido en el intento fallido."
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True,
        help_text="IP del cliente en el momento del intento."
    )
    user_agent = models.CharField(
        max_length=512, blank=True,
        help_text="User-Agent del navegador/cliente."
    )
    reason = models.CharField(
        max_length=100, blank=True,
        help_text="Motivo del fallo: 'wrong_password', 'user_not_found', etc."
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.user_name_attempted} ({self.ip_address})"

    class Meta:
        verbose_name = "Intento de login fallido"
        verbose_name_plural = "Intentos de login fallidos"
        ordering = ['-timestamp']


class MovieImageOverride(models.Model):
    """
    Override manual d'imatge per a una pel·lícula o sèrie provinent de les APIs externes.
    La imatge manual té prioritat sobre qualsevol imatge que pugui retornar l'API en el futur.
    Si no hi ha imatge manual, el sistema fa servir el placeholder de text (comportament actual).
    """
    movie_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="ID de la pel·lícula/sèrie tal com el retorna l'API externa."
    )
    title = models.CharField(
        max_length=255, blank=True,
        help_text="Títol de referència (no afecta la lògica, és per llegibilitat a l'admin)."
    )
    manual_image = models.ImageField(
        upload_to='movie_overrides/',
        null=True, blank=True,
        help_text="Imatge manual que substitueix qualsevol imatge de l'API. Format recomanat: 16:9 (ex. 1280×720px)."
    )
    notes = models.TextField(
        blank=True,
        help_text="Notes internes sobre aquest override (no es mostren a l'usuari)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.movie_id}] {self.title or 'Sense títol'}"

    def has_image(self):
        return bool(self.manual_image)
    has_image.boolean = True
    has_image.short_description = "Té imatge?"

    class Meta:
        verbose_name = "Override d'imatge de pel·lícula"
        verbose_name_plural = "Overrides d'imatge de pel·lícules"
        ordering = ['-updated_at']
