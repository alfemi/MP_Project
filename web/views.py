from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from .models import FunctionalUser, InfoUser
from .services import StreamApiService
import urllib.parse

# --- MAPEOS DE DATOS (Basados en tus CURLs) ---

GENRE_CHOICES = [
    ('1', '💥 Acción'), ('2', '😂 Comedia'), ('3', '🎭 Drama'),
    ('4', '👻 Terror'), ('5', '🚀 Sci-Fi'), ('6', '🧙‍♂️ Fantasía'),
    ('7', '❤️ Romance'), ('8', '🔪 Suspenso'), ('9', '🧸 Animación'),
    ('10', '📹 Documental'), ('11', '🔍 Misterio'), ('12', '🗺️ Aventura'),
    ('13', '🕵️‍♂️ Crimen'), ('14', '📚 Biografía'), ('15', '🏛️ Historia')
]

# Diccionario para traducir IDs de directores a nombres (Extraído de tu curl)
DIRECTOR_MAP = {
    1: "Christopher Nolan", 2: "Quentin Tarantino", 3: "Pedro Almodóvar",
    4: "Bong Joon-ho", 5: "Hayao Miyazaki", 30: "Denis Villeneuve",
    33: "Byron Howard", 34: "Steven Spielberg", 35: "Jon Watts",
    51: "Matt Reeves", 53: "James Cameron"
    # Puedes añadir el resto de la lista de tu curl aquí
}

# Diccionario para traducir age_rating_id a edad mínima numérica
# Mapeo estándar: 1: Todo público, 2: +7, 3: +13, 4: +16, 5: +18
AGE_RATING_MAP = {
    1: 0,
    2: 7,
    3: 13,
    4: 16,
    5: 18
}

def root_redirect(request):
    return redirect('home')

# --- VISTAS DE USUARIO ---

def register(request):
    if request.method == 'POST':
        user_name = request.POST.get('user_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        address = request.POST.get('address')
        language = request.POST.get('language')
        age = request.POST.get('age')
        sex = request.POST.get('sex')
        selected_genres = request.POST.getlist('genres')

        if not all([user_name, email, password, address, language, age, sex]):
            return render(request, 'web/register.html', {
                'error': 'Todos los campos son obligatorios.',
                'genres': GENRE_CHOICES
            })

        if len(selected_genres) < 5:
            return render(request, 'web/register.html', {
                'error': 'Selecciona al menos 5 géneros.',
                'genres': GENRE_CHOICES
            })

        if FunctionalUser.objects.filter(user_name=user_name).exists() or \
           FunctionalUser.objects.filter(email=email).exists():
            return render(request, 'web/register.html', {
                'error': 'El usuario o email ya existe.',
                'genres': GENRE_CHOICES
            })

        user = FunctionalUser.objects.create(
            user_name=user_name,
            email=email,
            password=make_password(password),
            rank='final-user'
        )
        
        InfoUser.objects.create(
            user=user,
            address=address,
            language=language,
            age=age,
            sex=sex,
            preferences=','.join(selected_genres)
        )
        return redirect('login')

    return render(request, 'web/register.html', {'genres': GENRE_CHOICES})

def login_view(request):
    if request.method == 'POST':
        user_name = request.POST.get('user_name')
        password = request.POST.get('password')

        try:
            user = FunctionalUser.objects.get(user_name=user_name)
            if check_password(password, user.password):
                request.session['user_id'] = user.id
                return redirect('home')
            return render(request, 'web/login.html', {'error': 'Contraseña incorrecta.'})
        except FunctionalUser.DoesNotExist:
            return render(request, 'web/login.html', {'error': 'Usuario no encontrado.'})

    return render(request, 'web/login.html')

from django.shortcuts import render, redirect
from .models import FunctionalUser, InfoUser
from .services import StreamApiService

# Mapeo de edad para la restricción (puedes moverlo a models o services si prefieres)
AGE_RATING_MAP = {
    1: 0,   # Todo público
    2: 7,   # +7 años
    3: 13,  # +13 años
    4: 16,  # +16 años
    5: 18,  # +18 años
}

def home(request):
    # --- AUTENTICACIÓN ---
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = FunctionalUser.objects.get(id=user_id)
        info_user = InfoUser.objects.get(user=user)
        user_age = info_user.age
        
        # 1. CAPTURA DE PARÁMETROS
        selected_genre = request.GET.get('genre', '')
        selected_director = request.GET.get('director', '')
        content_type = request.GET.get('type', 'all')
        search_query = request.GET.get('title', '')

        # 2. CONSTRUCCIÓN DE FILTROS PARA LA API
        api_filters = {}
        if selected_genre: api_filters['genre'] = selected_genre
        if selected_director: api_filters['director'] = selected_director
        if search_query: api_filters['title'] = search_query

        # 3. LLAMADAS DINÁMICAS A LAS APIs (Service con deduplicación)
        movies = []
        series = []
        
        # Obtenemos géneros y directores directamente de las APIs
        genres_list = StreamApiService.get_genres()
        directors_list = StreamApiService.get_directors()
        
        # Diccionarios rápidos para traducción en el clean_items
        genre_dict = {str(gid): gname for gid, gname in genres_list}
        director_dict = {str(did): dname for did, dname in directors_list}

        try:
            if content_type in ['all', 'movies']:
                movies = StreamApiService.get_movies(api_filters)
            if content_type in ['all', 'series']:
                series = StreamApiService.get_series(api_filters)
        except Exception as e:
            print(f"Error llamando a las APIs de contenido: {e}")

        # 4. LIMPIEZA DEFENSIVA Y LÓGICA DE RESTRICCIÓN DE EDAD
        def clean_items(items):
            if not items or not isinstance(items, list): return []
            result = []
            for item in items:
                if not isinstance(item, dict): continue
                
                # Traducir Director ID -> Nombre (usando datos de la API)
                d_id = str(item.get('director_id'))
                item['director_name'] = director_dict.get(d_id, "Director Desconocido")

                # Traducir Género ID -> Nombre (Para el hover en el HTML)
                g_id = str(item.get('genre_id'))
                genre_label = genre_dict.get(g_id, "General")
                item['genre_description'] = genre_label # Coincide con el HTML anterior

                # --- LÓGICA DE EDAD ---
                ar_id = item.get('age_rating_id', 1)
                min_age_required = AGE_RATING_MAP.get(ar_id, 0)
                
                if user_age < min_age_required:
                    item['is_blocked'] = True
                    item['block_message'] = f"Contenido para +{min_age_required} años"
                else:
                    item['is_blocked'] = False

                # Asegurar título y campos básicos
                item['title'] = item.get('title') or item.get('name') or "Sin título"
                result.append(item)
            return result

        # 5. CONTEXTO
        context = {
            'user': user,
            'user_age': user_age,
            'movies': clean_items(movies),
            'series': clean_items(series),
            'genres': genres_list,      # Viene de StreamApiService.get_genres()
            'directors': directors_list, # Viene de StreamApiService.get_directors()
            'selected_genre': selected_genre,
            'selected_director': selected_director,
            'content_type': content_type,
            'search_query': search_query,
        }
        return render(request, 'web/home.html', context)

    except (FunctionalUser.DoesNotExist, InfoUser.DoesNotExist):
        return redirect('login')

def profile(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = FunctionalUser.objects.get(id=user_id)
        info = InfoUser.objects.get(user=user)
        
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'update_info':
                user.email = request.POST.get('email', user.email)
                info.address = request.POST.get('address', info.address)
                info.language = request.POST.get('language', info.language)
                info.age = request.POST.get('age', info.age)
                info.sex = request.POST.get('sex', info.sex)
                
                user.save()
                info.save()
                return render(request, 'web/profile.html', {'user': user, 'info': info, 'success': 'Información actualizada correctamente.'})
            
            elif action == 'change_password':
                old_password = request.POST.get('old_password')
                new_password = request.POST.get('new_password')
                confirm_password = request.POST.get('confirm_password')
                
                if not check_password(old_password, user.password):
                    return render(request, 'web/profile.html', {'user': user, 'info': info, 'error': 'La contraseña actual es incorrecta.'})
                
                if new_password != confirm_password:
                    return render(request, 'web/profile.html', {'user': user, 'info': info, 'error': 'Las nuevas contraseñas no coinciden.'})
                
                user.password = make_password(new_password)
                user.save()
                return render(request, 'web/profile.html', {'user': user, 'info': info, 'success': 'Contraseña cambiada correctamente.'})

        return render(request, 'web/profile.html', {'user': user, 'info': info})
    except (FunctionalUser.DoesNotExist, InfoUser.DoesNotExist):
        return redirect('login')

def logout_view(request):
    request.session.flush()
    return redirect('login')