# Generated for StreamSync director dashboard access.

from django.db import migrations, models


DIRECTOR_PERMISSION = "can_view_director_dashboard"
DIRECTORS_GROUP = "Directors"


def create_directors_group(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="web",
        model="functionaluser",
    )
    permission, _ = Permission.objects.get_or_create(
        codename=DIRECTOR_PERMISSION,
        content_type=content_type,
        defaults={"name": "Can view director dashboard"},
    )
    group, _ = Group.objects.get_or_create(name=DIRECTORS_GROUP)
    group.permissions.add(permission)


def remove_directors_group_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    try:
        group = Group.objects.get(name=DIRECTORS_GROUP)
        permission = Permission.objects.get(
            codename=DIRECTOR_PERMISSION,
            content_type__app_label="web",
        )
    except (Group.DoesNotExist, Permission.DoesNotExist):
        return
    group.permissions.remove(permission)


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("web", "0006_apifailureevent_severity_contentinteraction_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="functionaluser",
            options={
                "ordering": ["-date_joined"],
                "permissions": [
                    ("can_view_director_dashboard", "Can view director dashboard"),
                ],
                "verbose_name": "Usuario",
                "verbose_name_plural": "Usuarios",
            },
        ),
        migrations.AddField(
            model_name="functionaluser",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                related_name="functional_users",
                to="auth.group",
            ),
        ),
        migrations.AddField(
            model_name="functionaluser",
            name="user_permissions",
            field=models.ManyToManyField(
                blank=True,
                related_name="functional_users",
                to="auth.permission",
            ),
        ),
        migrations.RunPython(create_directors_group, remove_directors_group_permission),
    ]
