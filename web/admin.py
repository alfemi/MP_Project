from django.contrib import admin

from django.contrib import admin
from .models import FunctionalUser, InfoUser

admin.site.register(FunctionalUser)
admin.site.register(InfoUser)

