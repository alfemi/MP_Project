from django.urls import path
from . import views

urlpatterns = [
    path('', views.root_redirect, name='root_redirect'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('home/', views.home, name='home'),
    path('profile/', views.profile, name='profile'),
    path('logout/', views.logout_view, name='logout'),
]
