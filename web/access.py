DIRECTORS_GROUP_NAME = "Directors"
DIRECTOR_PERMISSION_CODENAME = "can_view_director_dashboard"
INTERNAL_RANK = "sysadmin"


def get_session_functional_user(request):
    from .models import FunctionalUser

    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return FunctionalUser.objects.get(id=user_id, is_active=True)
    except FunctionalUser.DoesNotExist:
        return None


def has_director_access(request, functional_user=None):
    if getattr(request.user, "is_authenticated", False) and getattr(
        request.user,
        "is_superuser",
        False,
    ):
        return True

    user = functional_user or get_session_functional_user(request)
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "rank", "") == INTERNAL_RANK:
        return True

    if not hasattr(user, "groups") or not hasattr(user, "user_permissions"):
        return False

    if user.groups.filter(name=DIRECTORS_GROUP_NAME).exists():
        return True

    if user.user_permissions.filter(codename=DIRECTOR_PERMISSION_CODENAME).exists():
        return True

    return user.groups.filter(permissions__codename=DIRECTOR_PERMISSION_CODENAME).exists()
