import hashlib
import secrets

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .forms import CreateEmployeeForm
from .models import User
from .permissions import backoffice_required


def home_view(request):
    """
    Home page view with proper landing page.
    """
    context = {
        "title": "Timelog - Zeiterfassung",
        "user": request.user,
    }
    return render(request, "accounts/home.html", context)


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


@login_required
@backoffice_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def create_employee_view(request):
    """
    Create new employee account (backoffice only).
    """
    if request.method == "POST":
        form = CreateEmployeeForm(request.POST)
        if form.is_valid():
            # Create user with generated username
            user = form.save(commit=False)
            user.username = form.cleaned_data["email"]  # Use email as username
            user.is_invited = True

            # Generate first login token
            token = secrets.token_urlsafe(32)
            user.first_login_token = hashlib.sha256(token.encode()).hexdigest()

            # Save user without usable password
            user.set_unusable_password()
            user.save()

            # Generate first login URL (for now just show the token)
            first_login_url = request.build_absolute_uri(
                f"/accounts/first-login/{token}/"
            )

            messages.success(
                request,
                f"Mitarbeiter {user.get_full_name()} wurde erfolgreich angelegt. "
                f"Erstanmeldung-Link: {first_login_url}",
            )

            return redirect("accounts:create_employee")
    else:
        form = CreateEmployeeForm()

    context = {"form": form, "title": "Neuen Mitarbeiter anlegen"}
    return render(request, "accounts/create_employee.html", context)
