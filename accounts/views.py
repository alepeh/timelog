import hashlib
import secrets

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .calendar_utils import get_current_month_calendar, get_month_calendar
from .forms import CreateEmployeeForm, TimeEntryForm, FuelReceiptForm
from .models import TimeEntry, User, FuelReceipt, Vehicle
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
    Shows all time entries for the current user, with filtering options.
    """
    # Get user's time entries with vehicle usage data
    time_entries = (
        TimeEntry.objects.filter(user=request.user)
        .select_related("user")
        .prefetch_related("vehicleusage__vehicle")
    )

    # Apply vehicle filtering
    vehicle_filter = request.GET.get("vehicle")
    if vehicle_filter:
        if vehicle_filter == "no_vehicle":
            # Filter for entries where no vehicle was used
            time_entries = time_entries.filter(vehicleusage__no_vehicle_used=True)
        elif vehicle_filter == "with_vehicle":
            # Filter for entries with any vehicle
            time_entries = time_entries.filter(
                vehicleusage__vehicle__isnull=False, vehicleusage__no_vehicle_used=False
            )
        else:
            # Filter for specific vehicle ID
            try:
                vehicle_id = int(vehicle_filter)
                time_entries = time_entries.filter(vehicleusage__vehicle_id=vehicle_id)
            except (ValueError, TypeError):
                pass  # Invalid vehicle ID, ignore filter

    # Apply date filtering
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if date_from:
        try:
            from datetime import datetime

            parsed_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            time_entries = time_entries.filter(date__gte=parsed_date)
        except ValueError:
            pass  # Invalid date format, ignore filter

    if date_to:
        try:
            from datetime import datetime

            parsed_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            time_entries = time_entries.filter(date__lte=parsed_date)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Order by date (newest first)
    time_entries = time_entries.order_by("-date")

    # Get available vehicles for filter dropdown
    from .models import Vehicle

    available_vehicles = Vehicle.objects.filter(is_active=True).order_by(
        "license_plate"
    )

    # Calculate vehicle usage statistics
    all_entries = TimeEntry.objects.filter(user=request.user).prefetch_related(
        "vehicleusage__vehicle"
    )
    vehicle_stats = {
        "total_entries": all_entries.count(),
        "with_vehicle": all_entries.filter(
            vehicleusage__vehicle__isnull=False, vehicleusage__no_vehicle_used=False
        ).count(),
        "no_vehicle": all_entries.filter(vehicleusage__no_vehicle_used=True).count(),
        "unknown": all_entries.filter(vehicleusage__isnull=True).count(),
        "total_kilometers": 0,
    }

    # Calculate total kilometers driven
    for entry in all_entries:
        if (
            hasattr(entry, "vehicleusage")
            and entry.vehicleusage
            and entry.vehicleusage.daily_distance
        ):
            vehicle_stats["total_kilometers"] += entry.vehicleusage.daily_distance

    context = {
        "time_entries": time_entries,
        "title": "Meine Zeiteinträge",
        "available_vehicles": available_vehicles,
        "vehicle_stats": vehicle_stats,
        "current_filters": {
            "vehicle": vehicle_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    }
    return render(request, "accounts/time_entry_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def time_entry_create(request, target_date=None):
    """
    Create view for new time entries.
    Implements US-C01 (time tracking), US-C02 (lunch breaks), and US-C03
    (pollution level).
    """
    if request.method == "POST":
        form = TimeEntryForm(request.POST, user=request.user)
        if form.is_valid():
            # Check for warnings before saving
            warnings = form.get_warnings()
            if warnings:
                # Display warnings but allow saving
                for warning in warnings:
                    messages.warning(request, warning)

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

        # Pre-fill date if provided from calendar
        if target_date:
            try:
                from datetime import datetime

                parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
                form.fields["date"].initial = parsed_date
            except ValueError:
                pass  # Invalid date format, ignore

    context = {
        "form": form,
        "title": "Neuer Zeiteintrag",
        "submit_text": "Zeiteintrag erstellen",
        "target_date": target_date,
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
            # Check for warnings before saving
            warnings = form.get_warnings()
            if warnings:
                # Display warnings but allow saving
                for warning in warnings:
                    messages.warning(request, warning)

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


@login_required
@require_http_methods(["GET"])
def time_entry_calendar(request):
    """
    Calendar view for employee's time entries.
    Shows monthly overview with color-coded days.
    Implements US-C07: Monthly Time Entry Overview Calendar.
    """
    # Get month/year from query parameters, default to current month
    try:
        year = int(request.GET.get("year", ""))
        month = int(request.GET.get("month", ""))
        calendar_data = get_month_calendar(year, month, request.user)
    except (ValueError, TypeError):
        # Default to current month if parameters are invalid
        calendar_data = get_current_month_calendar(request.user)

    context = {
        "calendar": calendar_data,
        "title": f"Kalender - {calendar_data.title}",
        "current_year": calendar_data.year,
        "current_month": calendar_data.month,
        "prev_year": calendar_data.prev_month[0],
        "prev_month": calendar_data.prev_month[1],
        "next_year": calendar_data.next_month[0],
        "next_month": calendar_data.next_month[1],
        "stats": calendar_data.stats,
        "weeks": calendar_data.get_weeks(),
    }
    return render(request, "accounts/time_entry_calendar.html", context)


# Fuel Receipt Views (US-C09)


@login_required
@require_http_methods(["GET"])
def fuel_receipt_list(request):
    """
    List view for employee's fuel receipts.
    Shows all receipts for the current user with filtering options.
    """
    # Get user's fuel receipts
    receipts = FuelReceipt.objects.filter(employee=request.user).select_related(
        "vehicle", "approved_by"
    )

    # Apply filtering
    status_filter = request.GET.get("status")
    if status_filter:
        receipts = receipts.filter(status=status_filter)

    vehicle_filter = request.GET.get("vehicle")
    if vehicle_filter:
        try:
            vehicle_id = int(vehicle_filter)
            receipts = receipts.filter(vehicle_id=vehicle_id)
        except (ValueError, TypeError):
            pass  # Invalid vehicle ID, ignore filter

    # Order by receipt date (newest first)
    receipts = receipts.order_by("-receipt_date")

    # Get available vehicles and status choices for filters
    available_vehicles = Vehicle.objects.filter(
        is_active=True, fuelreceipt__employee=request.user
    ).distinct()

    context = {
        "receipts": receipts,
        "title": "Meine Tankbelege",
        "available_vehicles": available_vehicles,
        "status_choices": FuelReceipt.STATUS_CHOICES,
        "current_filters": {
            "status": status_filter,
            "vehicle": vehicle_filter,
        },
    }
    return render(request, "accounts/fuel_receipt_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def fuel_receipt_create(request):
    """
    Create view for new fuel receipts.
    Implements US-C09: Fuel Receipt Tracking with S3 Storage.
    """
    if request.method == "POST":
        form = FuelReceiptForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            # Check for warnings before saving
            warnings = form.get_warnings()
            if warnings:
                # Display warnings but allow saving
                for warning in warnings:
                    messages.warning(request, warning)

            receipt = form.save()

            messages.success(
                request,
                f"Tankbeleg für {receipt.vehicle.license_plate} wurde erfolgreich eingereicht. "
                f"Status: {receipt.get_status_display()}",
            )
            return redirect("accounts:fuel_receipt_list")
    else:
        form = FuelReceiptForm(user=request.user)

    context = {
        "form": form,
        "title": "Neuer Tankbeleg",
        "submit_text": "Beleg einreichen",
    }
    return render(request, "accounts/fuel_receipt_form.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def fuel_receipt_edit(request, receipt_id):
    """
    Edit view for existing fuel receipts.
    Only allows users to edit their own receipts within 24 hours and pending status.
    """
    try:
        receipt = FuelReceipt.objects.get(pk=receipt_id, employee=request.user)
    except FuelReceipt.DoesNotExist:
        messages.error(request, "Tankbeleg nicht gefunden oder keine Berechtigung.")
        return redirect("accounts:fuel_receipt_list")

    # Check if receipt can be edited
    if not receipt.can_be_edited:
        if receipt.status != "pending":
            messages.error(
                request,
                f"Tankbeleg kann nicht bearbeitet werden. "
                f"Status: {receipt.get_status_display()}",
            )
        else:
            messages.error(
                request,
                "Tankbeleg kann nur innerhalb von 24 Stunden nach "
                "der Einreichung bearbeitet werden.",
            )
        return redirect("accounts:fuel_receipt_detail", receipt_id=receipt.id)

    if request.method == "POST":
        form = FuelReceiptForm(
            request.POST, request.FILES, instance=receipt, user=request.user
        )
        if form.is_valid():
            # Check for warnings before saving
            warnings = form.get_warnings()
            if warnings:
                # Display warnings but allow saving
                for warning in warnings:
                    messages.warning(request, warning)

            receipt = form.save()

            messages.success(
                request,
                f"Tankbeleg für {receipt.vehicle.license_plate} "
                f"wurde erfolgreich aktualisiert.",
            )
            return redirect("accounts:fuel_receipt_detail", receipt_id=receipt.id)
    else:
        form = FuelReceiptForm(instance=receipt, user=request.user)

    context = {
        "form": form,
        "receipt": receipt,
        "title": f"Tankbeleg bearbeiten - {receipt.vehicle.license_plate}",
        "submit_text": "Änderungen speichern",
    }
    return render(request, "accounts/fuel_receipt_form.html", context)


@login_required
@require_http_methods(["GET"])
def fuel_receipt_detail(request, receipt_id):
    """
    Detail view for fuel receipts.
    Shows receipt information with secure image access.
    """
    try:
        receipt = FuelReceipt.objects.select_related(
            "vehicle", "employee", "approved_by"
        ).get(pk=receipt_id, employee=request.user)
    except FuelReceipt.DoesNotExist:
        messages.error(request, "Tankbeleg nicht gefunden oder keine Berechtigung.")
        return redirect("accounts:fuel_receipt_list")

    context = {
        "receipt": receipt,
        "title": f"Tankbeleg - {receipt.vehicle.license_plate}",
        "can_edit": receipt.can_be_edited,
    }
    return render(request, "accounts/fuel_receipt_detail.html", context)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def fuel_receipt_delete(request, receipt_id):
    """
    Delete view for fuel receipts.
    Only allows users to delete their own receipts if they're pending and within edit window.
    """
    try:
        receipt = FuelReceipt.objects.get(pk=receipt_id, employee=request.user)
    except FuelReceipt.DoesNotExist:
        messages.error(request, "Tankbeleg nicht gefunden oder keine Berechtigung.")
        return redirect("accounts:fuel_receipt_list")

    # Check if receipt can be deleted
    if not receipt.can_be_edited:
        if receipt.status != "pending":
            messages.error(
                request,
                f"Tankbeleg kann nicht gelöscht werden. "
                f"Status: {receipt.get_status_display()}",
            )
        else:
            messages.error(
                request,
                "Tankbeleg kann nur innerhalb von 24 Stunden nach "
                "der Einreichung gelöscht werden.",
            )
        return redirect("accounts:fuel_receipt_detail", receipt_id=receipt.id)

    vehicle_plate = receipt.vehicle.license_plate
    receipt.delete()
    messages.success(
        request, f"Tankbeleg für {vehicle_plate} wurde erfolgreich gelöscht."
    )

    return redirect("accounts:fuel_receipt_list")
