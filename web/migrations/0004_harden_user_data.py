import uuid

import django.core.validators
import django.db.models.functions.text
from django.db import migrations, models


def normalize_existing_users(apps, schema_editor):
    FunctionalUser = apps.get_model('web', 'FunctionalUser')
    for user in FunctionalUser.objects.all():
        updated_fields = []
        normalized_user_name = (user.user_name or '').strip()
        normalized_email = (user.email or '').strip().lower()

        if user.user_name != normalized_user_name:
            user.user_name = normalized_user_name
            updated_fields.append('user_name')

        if user.email != normalized_email:
            user.email = normalized_email
            updated_fields.append('email')

        if updated_fields:
            user.save(update_fields=updated_fields)


def populate_public_ids(apps, schema_editor):
    FunctionalUser = apps.get_model('web', 'FunctionalUser')
    for user in FunctionalUser.objects.filter(public_id__isnull=True):
        user.public_id = uuid.uuid4()
        user.save(update_fields=['public_id'])


def normalize_existing_profiles(apps, schema_editor):
    InfoUser = apps.get_model('web', 'InfoUser')
    language_map = {
        'català': 'ca',
        'catala': 'ca',
        'ca': 'ca',
        'español': 'es',
        'espanol': 'es',
        'castellano': 'es',
        'es': 'es',
        'english': 'en',
        'inglés': 'en',
        'ingles': 'en',
        'en': 'en',
        'français': 'fr',
        'francais': 'fr',
        'francés': 'fr',
        'frances': 'fr',
        'fr': 'fr',
    }
    for profile in InfoUser.objects.all():
        normalized_language = language_map.get((profile.language or '').strip().lower(), 'es')
        normalized_age = max(profile.age or 13, 13)
        normalized_address = (profile.address or '').strip()

        updated_fields = []
        if profile.language != normalized_language:
            profile.language = normalized_language
            updated_fields.append('language')
        if profile.age != normalized_age:
            profile.age = normalized_age
            updated_fields.append('age')
        if profile.address != normalized_address:
            profile.address = normalized_address
            updated_fields.append('address')
        if updated_fields:
            profile.save(update_fields=updated_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0003_failedloginattempt_movieimageoverride_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='functionaluser',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='functionaluser',
            name='public_id',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(normalize_existing_users, migrations.RunPython.noop),
        migrations.RunPython(normalize_existing_profiles, migrations.RunPython.noop),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='functionaluser',
            name='public_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='functionaluser',
            name='user_name',
            field=models.CharField(max_length=150, unique=True, validators=[django.core.validators.RegexValidator(message='El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos.', regex='^[A-Za-z0-9_.-]+$')]),
        ),
        migrations.AlterField(
            model_name='infouser',
            name='address',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='infouser',
            name='age',
            field=models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(13), django.core.validators.MaxValueValidator(120)]),
        ),
        migrations.AlterField(
            model_name='infouser',
            name='language',
            field=models.CharField(choices=[('ca', 'Català'), ('es', 'Español'), ('en', 'English'), ('fr', 'Français')], default='es', max_length=2),
        ),
        migrations.AddConstraint(
            model_name='functionaluser',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('user_name'), name='functionaluser_username_ci_unique'),
        ),
        migrations.AddConstraint(
            model_name='functionaluser',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('email'), name='functionaluser_email_ci_unique'),
        ),
    ]
