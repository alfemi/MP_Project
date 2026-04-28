from django import forms
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import FunctionalUser, InfoUser, normalize_email


class ProfileUpdateForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico")
    address = forms.CharField(label="Dirección", max_length=255, required=False)
    language = forms.ChoiceField(label="Idioma", choices=InfoUser.LANGUAGE_CHOICES)
    age = forms.IntegerField(label="Edad", min_value=13, max_value=120)
    sex = forms.ChoiceField(label="Género", choices=InfoUser.SEX_CHOICES)
    preferences = forms.MultipleChoiceField(
        label="Preferencias",
        choices=InfoUser.GENRE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])
        existing = FunctionalUser.objects.filter(email__iexact=email)
        if self.user:
            existing = existing.exclude(pk=self.user.pk)
        if existing.exists():
            raise ValidationError("Ese email ya está registrado.")
        return email

    def clean_preferences(self):
        preferences = self.cleaned_data.get("preferences") or []
        unique_preferences = list(dict.fromkeys(preferences))
        if len(unique_preferences) < 5:
            raise ValidationError("Selecciona al menos 5 géneros distintos.")
        return unique_preferences

    def save(self, user, info_user):
        user.email = self.cleaned_data["email"]
        user.save(update_fields=["email"])

        info_user.address = self.cleaned_data["address"]
        info_user.language = self.cleaned_data["language"]
        info_user.age = self.cleaned_data["age"]
        info_user.sex = self.cleaned_data["sex"]
        info_user.preferences = ",".join(self.cleaned_data["preferences"])
        info_user.save()
        return user, info_user


class PasswordChangeForm(forms.Form):
    old_password = forms.CharField(label="Contraseña actual", widget=forms.PasswordInput)
    new_password = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput)
    confirm_password = forms.CharField(
        label="Confirmar contraseña", widget=forms.PasswordInput
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data["old_password"]
        if not self.user or not check_password(old_password, self.user.password):
            raise ValidationError("La contraseña actual no es correcta.")
        return old_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error("confirm_password", "Las nuevas contraseñas no coinciden.")

        if new_password and self.user:
            validate_password(new_password)
            if check_password(new_password, self.user.password):
                self.add_error(
                    "new_password",
                    "La nueva contraseña debe ser distinta de la actual.",
                )
        return cleaned_data

    def save(self, user):
        user.password = make_password(self.cleaned_data["new_password"])
        user.save(update_fields=["password"])
        return user
