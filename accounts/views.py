import hashlib

from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .models import User


def home_view(request):
    """
    Simple home page view.
    """
    if request.user.is_authenticated:
        return redirect("admin:index")
    else:
        return redirect("admin:login")


@require_http_methods(["GET", "POST"])
@csrf_protect
def first_login_view(request, token):
    """
    Handle first-time login with token-based password setup.
    """
    # Hash the token to match stored hash
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Find user with matching token
    try:
        user = User.objects.get(first_login_token=token_hash)
    except User.DoesNotExist:
        messages.error(request, "Ungültiger oder abgelaufener Einladungslink.")
        return redirect("admin:login")

    if request.method == "GET":
        # Show password setup form
        context = {
            "user": user,
            "token": token,
        }
        return render(request, "accounts/first_login.html", context)

    elif request.method == "POST":
        # Process password setup
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")

        # Validation
        errors = []
        if len(password1) < 8:
            errors.append("Das Passwort muss mindestens 8 Zeichen lang sein.")

        if password1 != password2:
            errors.append("Die Passwörter stimmen nicht überein.")

        if not password1:
            errors.append("Bitte geben Sie ein Passwort ein.")

        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                "user": user,
                "token": token,
            }
            return render(request, "accounts/first_login.html", context)

        # Set new password and clear token
        user.set_password(password1)
        user.first_login_token = None
        user.save()

        # Log user in
        login(request, user)

        messages.success(
            request,
            f"Willkommen, {user.get_full_name()}! "
            f"Ihr Passwort wurde erfolgreich festgelegt.",
        )

        # Redirect based on role
        if user.is_backoffice:
            return redirect("admin:index")
        else:
            # TODO: Redirect to employee dashboard when implemented
            return redirect("admin:index")  # Temporary
