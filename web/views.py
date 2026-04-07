from django.shortcuts import render

from django.shortcuts import render, redirect
from django.contrib.auth.hashers import make_password, check_password
from .models import FunctionalUser, InfoUser

def root_redirect(request):
    return redirect('home')

def register(request):
    if request.method == 'POST':
        user_name = request.POST.get('user_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        # InfoUser fields
        address = request.POST.get('address')
        language = request.POST.get('language')
        age = request.POST.get('age')
        sex = request.POST.get('sex')
        preferences = request.POST.get('preferences')

        # Basic validation
        if not all([user_name, email, password, address, language, age, sex]):
            return render(request, 'web/register.html', {'error': 'All required fields must be filled.'})

        if FunctionalUser.objects.filter(user_name=user_name).exists():
            return render(request, 'web/register.html', {'error': 'Username already exists.'})

        if FunctionalUser.objects.filter(email=email).exists():
            return render(request, 'web/register.html', {'error': 'Email already registered.'})

        # Create user
        hashed_password = make_password(password)
        user = FunctionalUser.objects.create(
            user_name=user_name,
            email=email,
            password=hashed_password,
            rank='final-user'
        )
        
        # Create InfoUser
        InfoUser.objects.create(
            user=user,
            address=address,
            language=language,
            age=age,
            sex=sex,
            preferences=preferences
        )
        
        return redirect('login')

    return render(request, 'web/register.html')

def login_view(request):
    if request.method == 'POST':
        user_name = request.POST.get('user_name')
        password = request.POST.get('password')

        if not all([user_name, password]):
            return render(request, 'web/login.html', {'error': 'All fields are required.'})

        try:
            user = FunctionalUser.objects.get(user_name=user_name)
            if check_password(password, user.password):
                request.session['user_id'] = user.id
                # Redirect to a new page, e.g., a dashboard
                return redirect('home') # Assuming you have a 'home' url
            else:
                return render(request, 'web/login.html', {'error': 'Invalid credentials.'})
        except FunctionalUser.DoesNotExist:
            return render(request, 'web/login.html', {'error': 'User not found.'})

    return render(request, 'web/login.html')

def home(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    try:
        user = FunctionalUser.objects.get(id=user_id)
        return render(request, 'web/home.html', {'user': user})
    except FunctionalUser.DoesNotExist:
        return redirect('login')


