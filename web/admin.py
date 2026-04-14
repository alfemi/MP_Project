from django.contrib import admin
from django.contrib.auth.hashers import identify_hasher, make_password
from django.utils.html import format_html, format_html_join
from django.utils.timezone import localtime
from .models import FunctionalUser, InfoUser, FailedLoginAttempt, MovieImageOverride

# ---------------------------------------------------------------------------
# Personalització del site d'admin
# ---------------------------------------------------------------------------
admin.site.site_header = "StreamSync"
admin.site.site_title = "StreamSync Admin"
admin.site.index_title = "Panell de control"


# ---------------------------------------------------------------------------
# Helper intern
# ---------------------------------------------------------------------------
def _genre_badges(preferences_str):
    """Retorna badges HTML per a la cadena de preferències."""
    if not preferences_str:
        return format_html("<span style='color:#888;'>—</span>")
    genre_labels = dict(InfoUser.GENRE_CHOICES)
    genres = [genre_labels.get(g.strip(), g.strip()) for g in preferences_str.split(',') if g.strip()]
    return format_html_join(
        "",
        '<span style="background:#1a1a2e;color:#e0e0e0;padding:2px 8px;'
        'border-radius:12px;font-size:0.8em;margin:2px;display:inline-block;">{}</span> ',
        ((genre,) for genre in genres),
    )


# ---------------------------------------------------------------------------
# Inline: InfoUser dins FunctionalUser
# ---------------------------------------------------------------------------
class InfoUserInline(admin.StackedInline):
    model = InfoUser
    can_delete = False
    verbose_name = "Informació addicional"
    verbose_name_plural = "Informació addicional"
    extra = 0
    fields = ('address', 'language', 'age', 'sex', 'preferences', 'preferences_display')
    readonly_fields = ('preferences_display',)

    @admin.display(description="Preferències (vista)")
    def preferences_display(self, obj):
        if obj is None or not isinstance(obj, InfoUser):
            return format_html("<span style='color:#888;'>—</span>")
        return _genre_badges(obj.preferences)


# ---------------------------------------------------------------------------
# Accions de massa per a FunctionalUser
# ---------------------------------------------------------------------------
@admin.action(description="✅ Activar usuaris seleccionats")
def activate_users(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{updated} usuari(s) activat(s) correctament.")


@admin.action(description="🚫 Desactivar (bloquejar) usuaris seleccionats")
def deactivate_users(modeladmin, request, queryset):
    updated = queryset.update(is_active=False)
    modeladmin.message_user(request, f"{updated} usuari(s) desactivat(s) correctament.")


# ---------------------------------------------------------------------------
# FunctionalUserAdmin
# ---------------------------------------------------------------------------
@admin.register(FunctionalUser)
class FunctionalUserAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_name', 'email', 'email_verified', 'rank_badge', 'status_badge',
        'date_joined', 'last_login_display',
    )
    list_display_links = ('id', 'user_name')
    list_filter = ('rank', 'is_active', 'email_verified', 'date_joined')
    search_fields = ('user_name', 'email')
    ordering = ('-date_joined',)
    readonly_fields = ('public_id', 'date_joined', 'last_login', 'password')
    actions = [activate_users, deactivate_users]
    inlines = [InfoUserInline]

    fieldsets = (
        ("Identitat", {
            'fields': ('public_id', 'user_name', 'email', 'email_verified', 'password')
        }),
        ("Rol i estat", {
            'fields': ('rank', 'is_active')
        }),
        ("Auditoria", {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = ['public_id', 'date_joined', 'last_login']
        if obj:
            readonly_fields.append('password')
        return readonly_fields

    def save_model(self, request, obj, form, change):
        raw_password = form.cleaned_data.get('password')
        if raw_password:
            try:
                identify_hasher(raw_password)
            except Exception:
                obj.password = make_password(raw_password)
        super().save_model(request, obj, form, change)

    @admin.display(description="Rang", ordering='rank')
    def rank_badge(self, obj):
        colors = {
            'sysadmin': '#e50914',
            'finance': '#f5a623',
            'final-user': '#46d369',
        }
        color = colors.get(obj.rank, '#888')
        label = obj.get_rank_display()
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:12px;font-size:0.8em;">{}</span>',
            color, label
        )

    @admin.display(description="Estat", ordering='is_active')
    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:#46d369;font-weight:bold;">● Actiu</span>')
        return format_html('<span style="color:#e50914;font-weight:bold;">● Bloquejat</span>')

    @admin.display(description="Últim login", ordering='last_login')
    def last_login_display(self, obj):
        if obj.last_login:
            return localtime(obj.last_login).strftime("%d/%m/%Y %H:%M")
        return "—"


# ---------------------------------------------------------------------------
# InfoUserAdmin
# ---------------------------------------------------------------------------
@admin.register(InfoUser)
class InfoUserAdmin(admin.ModelAdmin):
    list_display = ('user', 'age', 'sex', 'language', 'address_display')
    list_filter = ('sex', 'language')
    search_fields = ('user__user_name', 'user__email', 'address')
    ordering = ('user__user_name',)
    readonly_fields = ('preferences_display',)
    fields = ('user', 'address', 'language', 'age', 'sex', 'preferences', 'preferences_display')
    list_select_related = ('user',)

    @admin.display(description="Dirección")
    def address_display(self, obj):
        return obj.address or "—"

    @admin.display(description="Preferències (vista)")
    def preferences_display(self, obj):
        if obj is None:
            return format_html("<span style='color:#888;'>—</span>")
        return _genre_badges(obj.preferences)


# ---------------------------------------------------------------------------
# Acció: esborrar intents seleccionats
# ---------------------------------------------------------------------------
@admin.action(description="🗑️ Eliminar intents seleccionats")
def delete_selected_attempts(modeladmin, request, queryset):
    count = queryset.count()
    queryset.delete()
    modeladmin.message_user(request, f"{count} intent(s) eliminat(s).")


# ---------------------------------------------------------------------------
# FailedLoginAttemptAdmin
# ---------------------------------------------------------------------------
@admin.register(FailedLoginAttempt)
class FailedLoginAttemptAdmin(admin.ModelAdmin):
    list_display = (
        'timestamp_display', 'user_name_attempted', 'reason_badge',
        'ip_address', 'user_agent_short',
    )
    list_filter = ('reason', 'timestamp')
    search_fields = ('user_name_attempted', 'ip_address')
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'
    actions = [delete_selected_attempts]
    readonly_fields = (
        'user_name_attempted', 'ip_address', 'user_agent', 'reason', 'timestamp',
    )
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    @admin.display(description="Timestamp", ordering='timestamp')
    def timestamp_display(self, obj):
        return localtime(obj.timestamp).strftime("%d/%m/%Y %H:%M:%S")

    @admin.display(description="Motiu", ordering='reason')
    def reason_badge(self, obj):
        colors = {
            'wrong_password': '#f5a623',
            'user_not_found': '#e50914',
            'account_inactive': '#888',
        }
        labels = {
            'wrong_password': '🔑 Contrasenya incorrecta',
            'user_not_found': '👤 Usuari no trobat',
            'account_inactive': '🚫 Compte inactiu',
        }
        color = colors.get(obj.reason, '#555')
        label = labels.get(obj.reason, obj.reason or '—')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:0.8em;">{}</span>',
            color, label
        )

    @admin.display(description="User-Agent")
    def user_agent_short(self, obj):
        if obj.user_agent and len(obj.user_agent) > 60:
            return obj.user_agent[:60] + "…"
        return obj.user_agent or "—"


# ---------------------------------------------------------------------------
# MovieImageOverrideAdmin
# ---------------------------------------------------------------------------
@admin.register(MovieImageOverride)
class MovieImageOverrideAdmin(admin.ModelAdmin):
    list_display = (
        'movie_id', 'title', 'image_preview', 'has_image', 'updated_at',
    )
    search_fields = ('movie_id', 'title')
    ordering = ('-updated_at',)
    readonly_fields = ('updated_at', 'image_preview_large')

    fieldsets = (
        ("Identificació", {
            'fields': ('movie_id', 'title'),
            'description': (
                "Introdueix l'ID de la pel·lícula tal com el retorna l'API externa. "
                "El títol és informatiu."
            ),
        }),
        ("Imatge manual", {
            'fields': ('manual_image', 'image_preview_large'),
            'description': (
                "Aquesta imatge substitueix qualsevol imatge de les APIs. "
                "Format recomanat: 16:9 (ex. 1280×720 px)."
            ),
        }),
        ("Notes internes", {
            'fields': ('notes', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description="Preview")
    def image_preview(self, obj):
        if obj and obj.manual_image and obj.manual_image.name:
            return format_html(
                '<img src="{}" style="height:40px;border-radius:4px;object-fit:cover;" />',
                obj.manual_image.url
            )
        return format_html('<span style="color:#888;">—</span>')

    @admin.display(description="Previsualització")
    def image_preview_large(self, obj):
        if obj and obj.manual_image and obj.manual_image.name:
            return format_html(
                '<img src="{}" style="max-height:200px;max-width:360px;'
                'border-radius:6px;object-fit:cover;border:1px solid #333;" />',
                obj.manual_image.url
            )
        return "Cap imatge carregada."
