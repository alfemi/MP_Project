from django.urls import path
from . import views

urlpatterns = [
    path("", views.root_redirect, name="root_redirect"),
    path("catalog/", views.catalog, name="catalog"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("home/", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
    path("logout/", views.logout_view, name="logout"),
    path(
        "content/<str:content_type>/<str:content_id>/",
        views.content_detail,
        name="content_detail",
    ),
    path("favorites/", views.favorites, name="favorites"),
    path(
        "favorites/toggle/<str:content_type>/<str:content_id>/",
        views.toggle_favorite,
        name="toggle_favorite",
    ),
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
        "dashboard/export/<str:dataset>/",
        views.dashboard_export_csv,
        name="dashboard_export_csv",
    ),
]
