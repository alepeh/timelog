import hashlib
import secrets

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .forms import CreateEmployeeForm, TimeEntryForm
from .models import TimeEntry, User
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

        # Log user in (specify backend due to django-axes)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

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


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def time_entry_list(request):
    """
    List view for employee's time entries.
    Shows all time entries for the current user, with basic filtering.
    """
    # Get user's time entries, ordered by date (newest first)
    time_entries = TimeEntry.objects.filter(user=request.user).order_by("-date")

    context = {
        "time_entries": time_entries,
        "title": "Meine Zeiteinträge",
    }
    return render(request, "accounts/time_entry_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def time_entry_create(request):
    """
    Create view for new time entries.
    Implements US-C01 (time tracking), US-C02 (lunch breaks), and US-C03
    (pollution level).
    """
    if request.method == "POST":
        form = TimeEntryForm(request.POST, user=request.user)
        if form.is_valid():
            time_entry = form.save(commit=False)
            time_entry.user = request.user
            time_entry.created_by = request.user
            time_entry.updated_by = request.user
            time_entry.save()

            messages.success(
                request,
                f"Zeiteintrag für {time_entry.date} wurde erfolgreich erstellt. "
                f"Arbeitszeit: {time_entry.total_work_hours:.1f} Stunden.",
            )
            return redirect("accounts:time_entry_list")
    else:
        form = TimeEntryForm(user=request.user)

    context = {
        "form": form,
        "title": "Neuer Zeiteintrag",
        "submit_text": "Zeiteintrag erstellen",
    }
    return render(request, "accounts/time_entry_form.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def time_entry_edit(request, entry_id):
    """
    Edit view for existing time entries.
    Only allows users to edit their own time entries.
    """
    try:
        time_entry = TimeEntry.objects.get(pk=entry_id, user=request.user)
    except TimeEntry.DoesNotExist:
        messages.error(request, "Zeiteintrag nicht gefunden oder keine Berechtigung.")
        return redirect("accounts:time_entry_list")

    if request.method == "POST":
        form = TimeEntryForm(request.POST, instance=time_entry, user=request.user)
        if form.is_valid():
            time_entry = form.save(commit=False)
            time_entry.updated_by = request.user
            time_entry.save()

            messages.success(
                request,
                f"Zeiteintrag für {time_entry.date} wurde erfolgreich aktualisiert. "
                f"Arbeitszeit: {time_entry.total_work_hours:.1f} Stunden.",
            )
            return redirect("accounts:time_entry_list")
    else:
        form = TimeEntryForm(instance=time_entry, user=request.user)

    context = {
        "form": form,
        "time_entry": time_entry,
        "title": f"Zeiteintrag bearbeiten - {time_entry.date}",
        "submit_text": "Änderungen speichern",
    }
    return render(request, "accounts/time_entry_form.html", context)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def time_entry_delete(request, entry_id):
    """
    Delete view for time entries.
    Only allows users to delete their own time entries.
    """
    try:
        time_entry = TimeEntry.objects.get(pk=entry_id, user=request.user)
        date = time_entry.date
        time_entry.delete()
        messages.success(request, f"Zeiteintrag für {date} wurde erfolgreich gelöscht.")
    except TimeEntry.DoesNotExist:
        messages.error(request, "Zeiteintrag nicht gefunden oder keine Berechtigung.")

    return redirect("accounts:time_entry_list")
