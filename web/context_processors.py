from .access import get_session_functional_user, has_director_access


def streamsync_access(request):
    functional_user = get_session_functional_user(request)
    can_access_director_dashboard = has_director_access(request, functional_user)
    return {
        "functional_user": functional_user,
        "can_access_director_dashboard": can_access_director_dashboard,
        "can_view_director_dashboard": can_access_director_dashboard,
    }
