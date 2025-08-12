import hashlib
import secrets

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.mail import send_mail

from .models import (
    EmployeeNonWorkingDay,
    PublicHoliday,
    TimeEntry,
    User,
    Vehicle,
    VehicleUsage,
)
from .permissions import (
    can_export_time_entries,
    can_view_user_list,
    get_accessible_time_entries,
    get_accessible_users,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom admin interface for User model with German labels.
    Supports creating new employees with invitation emails.
    """

    # Display configuration
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_invited",
        "is_active",
    )
    list_filter = ("role", "is_invited", "is_active", "date_joined")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)

    # Form configuration
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Timelog Einstellungen",
            {
                "fields": (
                    "role",
                    "is_invited",
                    "first_login_token",
                    "default_vehicle",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "first_name", "last_name", "role"),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        """Override save to handle new user creation with invitation."""
        if not change:  # New user
            # Generate random password and first login token
            random_password = User.objects.make_random_password()
            obj.set_password(random_password)

            # Generate secure token for first login
            token = secrets.token_urlsafe(32)
            obj.first_login_token = hashlib.sha256(token.encode()).hexdigest()
            obj.is_invited = True

            # Save user first
            super().save_model(request, obj, form, change)

            # Send invitation email
            self.send_invitation_email(obj, token, request.user)
        else:
            super().save_model(request, obj, form, change)

    def send_invitation_email(self, user, token, creator):
        """Send invitation email to new user."""
        subject = f"Willkommen bei Timelog - Account für {user.get_full_name()}"

        # Build first login URL (placeholder for now)
        first_login_url = f"http://localhost:8000/accounts/first-login/{token}/"

        message = f"""
Hallo {user.get_full_name()},

Sie wurden von {creator.get_full_name()} als {user.get_role_display()} \
zum Timelog-System eingeladen.

Bitte nutzen Sie folgenden Link für Ihre erste Anmeldung:
{first_login_url}

Bei der ersten Anmeldung können Sie Ihr eigenes Passwort festlegen.

Ihre Anmeldedaten:
Benutzername: {user.username}
E-Mail: {user.email}

Bei Fragen wenden Sie sich bitte an das Backoffice-Team.

Viele Grüße,
Das Timelog-Team
        """

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=(
                    settings.DEFAULT_FROM_EMAIL
                    if hasattr(settings, "DEFAULT_FROM_EMAIL")
                    else "noreply@timelog.local"
                ),
                recipient_list=[user.email],
                fail_silently=False,
            )
            self.message_user(
                None,
                f"Einladungs-E-Mail wurde erfolgreich an {user.email} gesendet.",
                level="SUCCESS",
            )
        except Exception as e:
            self.message_user(
                None,
                f"Fehler beim Senden der Einladungs-E-Mail: {str(e)}",
                level="ERROR",
            )

    actions = ["resend_invitation"]

    def resend_invitation(self, request, queryset):
        """Admin action to resend invitation emails."""
        for user in queryset:
            if user.first_login_token:
                # Generate new token
                token = secrets.token_urlsafe(32)
                user.first_login_token = hashlib.sha256(token.encode()).hexdigest()
                user.save()

                self.send_invitation_email(user, token, request.user)

    resend_invitation.short_description = "Einladung erneut senden"

    def has_view_permission(self, request, obj=None):
        """Check if user can view the user list."""
        # Superusers always have permission
        if request.user.is_superuser:
            return True

        if not super().has_view_permission(request, obj):
            return False

        # Only backoffice users can view user list
        if obj is None:  # List view
            return can_view_user_list(request.user)

        # For individual users, backoffice can see all, employees only themselves
        if request.user.is_superuser or request.user.is_backoffice:
            return True

        return request.user.is_employee and obj == request.user

    def has_add_permission(self, request):
        """Check if user can add new users."""
        return (
            super().has_add_permission(request)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_change_permission(self, request, obj=None):
        """Check if user can change user objects."""
        if not super().has_change_permission(request, obj):
            return False

        # Backoffice can change all users
        if request.user.is_backoffice:
            return True

        # Employees can only change their own profile
        if obj is None:  # List view
            return request.user.is_employee

        return request.user.is_employee and obj == request.user

    def has_delete_permission(self, request, obj=None):
        """Check if user can delete users."""
        # Only backoffice can delete users
        return (
            super().has_delete_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def get_queryset(self, request):
        """Filter queryset based on user role."""
        return get_accessible_users(request.user)


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    """
    Admin interface for TimeEntry model with comprehensive filtering and display.
    """

    # Display configuration
    list_display = (
        "date",
        "user",
        "start_time",
        "end_time",
        "lunch_break_minutes",
        "pollution_level",
        "total_work_hours",
        "created_by",
        "created_at",
    )

    list_filter = (
        "date",
        "pollution_level",
        "user__role",
        "created_at",
        "updated_at",
        ("user", admin.RelatedOnlyFieldListFilter),
        ("created_by", admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
        "notes",
    )

    date_hierarchy = "date"
    ordering = ("-date", "user")

    # Form configuration
    fieldsets = (
        (
            "Arbeitszeit",
            {
                "fields": (
                    "user",
                    "date",
                    "start_time",
                    "end_time",
                    "lunch_break_minutes",
                ),
            },
        ),
        (
            "Arbeitsbedingungen",
            {
                "fields": ("pollution_level", "notes"),
            },
        ),
        (
            "Metadaten",
            {
                "fields": ("created_by", "updated_by"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("total_work_hours", "total_work_minutes")

    def total_work_hours(self, obj):
        """Display total work hours as readonly field."""
        return f"{obj.total_work_hours:.1f} Stunden"

    total_work_hours.short_description = "Arbeitszeit (Stunden)"

    def save_model(self, request, obj, form, change):
        """Set created_by and updated_by fields automatically."""
        if not change:  # New object
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Filter queryset based on user role and optimize with select_related."""
        return get_accessible_time_entries(request.user).select_related(
            "user", "created_by", "updated_by"
        )

    # Custom actions
    actions = ["export_to_csv"]

    def export_to_csv(self, request, queryset):
        """Export selected time entries to CSV."""
        import csv

        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="zeiteintraege.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Datum",
                "Mitarbeiter",
                "Startzeit",
                "Endzeit",
                "Mittagspause (Min)",
                "Verschmutzungsgrad",
                "Arbeitszeit (Std)",
                "Notizen",
            ]
        )

        for entry in queryset:
            writer.writerow(
                [
                    entry.date,
                    entry.user.get_full_name(),
                    entry.start_time,
                    entry.end_time,
                    entry.lunch_break_minutes,
                    entry.get_pollution_level_display(),
                    f"{entry.total_work_hours:.1f}",
                    entry.notes or "",
                ]
            )

        return response

    export_to_csv.short_description = "Ausgewählte Einträge als CSV exportieren"

    def has_view_permission(self, request, obj=None):
        """Check if user can view time entries."""
        if not super().has_view_permission(request, obj):
            return False

        # All authenticated users can view time entries (with filtering)
        return request.user.is_authenticated

    def has_add_permission(self, request):
        """Check if user can add time entries."""
        # Both backoffice and employees can add entries (with restrictions)
        return super().has_add_permission(request) and request.user.is_authenticated

    def has_change_permission(self, request, obj=None):
        """Check if user can change time entries."""
        if not super().has_change_permission(request, obj):
            return False

        if not request.user.is_authenticated:
            return False

        # For specific objects, check if user has access
        if obj is not None:
            from .permissions import can_modify_time_entry

            return can_modify_time_entry(request.user, obj)

        # For list view, allow if authenticated (filtering handles access)
        return True

    def has_delete_permission(self, request, obj=None):
        """Check if user can delete time entries."""
        if not super().has_delete_permission(request, obj):
            return False

        if not request.user.is_authenticated:
            return False

        # For specific objects, check if user has access
        if obj is not None:
            from .permissions import can_modify_time_entry

            return can_modify_time_entry(request.user, obj)

        # For list view, allow if authenticated (filtering handles access)
        return True

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit user choices in forms based on role."""
        if db_field.name == "user":
            if request.user.is_employee:
                # Employees can only create entries for themselves
                kwargs["queryset"] = User.objects.filter(pk=request.user.pk)
            elif request.user.is_backoffice:
                # Backoffice can create entries for anyone
                kwargs["queryset"] = User.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_actions(self, request):
        """Filter available actions based on user role."""
        actions = super().get_actions(request)

        # Only backoffice users can export CSV
        if not can_export_time_entries(request.user):
            if "export_to_csv" in actions:
                del actions["export_to_csv"]

        return actions


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    """
    Admin interface for PublicHoliday model.
    Allows backoffice users to manage public holidays for all employees.
    """

    # Display configuration
    list_display = (
        "name",
        "date",
        "is_recurring",
        "description",
        "created_at",
    )

    list_filter = (
        "is_recurring",
        "date",
        "created_at",
    )

    search_fields = ("name", "description")

    date_hierarchy = "date"
    ordering = ("date", "name")

    # Form configuration
    fieldsets = (
        (
            "Feiertag",
            {
                "fields": (
                    "name",
                    "date",
                    "is_recurring",
                    "description",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        """Only backoffice users can add public holidays."""
        return (
            super().has_add_permission(request)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_change_permission(self, request, obj=None):
        """Only backoffice users can change public holidays."""
        return (
            super().has_change_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_delete_permission(self, request, obj=None):
        """Only backoffice users can delete public holidays."""
        return (
            super().has_delete_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_view_permission(self, request, obj=None):
        """All authenticated users can view public holidays."""
        return (
            super().has_view_permission(request, obj) and request.user.is_authenticated
        )


@admin.register(EmployeeNonWorkingDay)
class EmployeeNonWorkingDayAdmin(admin.ModelAdmin):
    """
    Admin interface for EmployeeNonWorkingDay model.
    Allows backoffice users to configure employee-specific non-working days.
    """

    # Display configuration
    list_display = (
        "employee",
        "pattern",
        "date",
        "weekday_display",
        "day_of_month",
        "valid_from",
        "valid_until",
        "reason",
    )

    list_filter = (
        "pattern",
        "weekday",
        "employee__role",
        "valid_from",
        "valid_until",
        ("employee", admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        "employee__first_name",
        "employee__last_name",
        "employee__email",
        "reason",
    )

    date_hierarchy = "date"
    ordering = ("employee", "date", "weekday")

    # Form configuration
    fieldsets = (
        (
            "Mitarbeiter",
            {
                "fields": ("employee",),
            },
        ),
        (
            "Muster",
            {
                "fields": (
                    "pattern",
                    "date",
                    "weekday",
                    "day_of_month",
                ),
            },
        ),
        (
            "Gültigkeitszeitraum",
            {
                "fields": (
                    "valid_from",
                    "valid_until",
                ),
            },
        ),
        (
            "Details",
            {
                "fields": ("reason",),
            },
        ),
    )

    def weekday_display(self, obj):
        """Display weekday name if set."""
        if obj.weekday is not None:
            return dict(EmployeeNonWorkingDay.WEEKDAY_CHOICES)[obj.weekday]
        return "-"

    weekday_display.short_description = "Wochentag"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit employee choices to actual employees."""
        if db_field.name == "employee":
            kwargs["queryset"] = User.objects.filter(role="employee")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request):
        """Only backoffice users can add employee non-working days."""
        return (
            super().has_add_permission(request)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_change_permission(self, request, obj=None):
        """Only backoffice users can change employee non-working days."""
        return (
            super().has_change_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_delete_permission(self, request, obj=None):
        """Only backoffice users can delete employee non-working days."""
        return (
            super().has_delete_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_view_permission(self, request, obj=None):
        """Backoffice can view all, employees can view their own."""
        if not super().has_view_permission(request, obj):
            return False

        if not request.user.is_authenticated:
            return False

        if request.user.is_backoffice:
            return True

        # Employees can view their own non-working days
        if obj is None:  # List view
            return request.user.is_employee

        return request.user.is_employee and obj.employee == request.user

    def get_queryset(self, request):
        """Filter queryset based on user role."""
        queryset = super().get_queryset(request)

        if request.user.is_superuser or request.user.is_backoffice:
            return queryset

        # Employees can only see their own non-working days
        if request.user.is_employee:
            return queryset.filter(employee=request.user)

        # Default: no access
        return queryset.none()


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    """
    Admin interface for Vehicle model.
    Allows backoffice users to manage company fleet vehicles.
    """

    # Display configuration
    list_display = (
        "license_plate",
        "make",
        "model",
        "year",
        "color",
        "fuel_type",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "fuel_type",
        "make",
        "year",
        "created_at",
    )

    search_fields = (
        "license_plate",
        "make",
        "model",
        "color",
        "notes",
    )

    date_hierarchy = "created_at"
    ordering = ("license_plate",)

    # Form configuration
    fieldsets = (
        (
            "Fahrzeug-Informationen",
            {
                "fields": (
                    "license_plate",
                    "make",
                    "model",
                    "year",
                    "color",
                    "fuel_type",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active",),
            },
        ),
        (
            "Zusätzliche Informationen",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at")

    # Custom actions
    actions = ["activate_vehicles", "deactivate_vehicles"]

    def activate_vehicles(self, request, queryset):
        """Activate selected vehicles."""
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f"{count} Fahrzeug(e) wurde(n) aktiviert.",
            level="SUCCESS",
        )

    activate_vehicles.short_description = "Ausgewählte Fahrzeuge aktivieren"

    def deactivate_vehicles(self, request, queryset):
        """Deactivate selected vehicles."""
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"{count} Fahrzeug(e) wurde(n) deaktiviert.",
            level="SUCCESS",
        )

    deactivate_vehicles.short_description = "Ausgewählte Fahrzeuge deaktivieren"

    def has_add_permission(self, request):
        """Only backoffice users can add vehicles."""
        return (
            super().has_add_permission(request)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_change_permission(self, request, obj=None):
        """Only backoffice users can change vehicles."""
        return (
            super().has_change_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_delete_permission(self, request, obj=None):
        """Only backoffice users can delete vehicles."""
        return (
            super().has_delete_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_view_permission(self, request, obj=None):
        """All authenticated users can view vehicles."""
        return (
            super().has_view_permission(request, obj) and request.user.is_authenticated
        )


@admin.register(VehicleUsage)
class VehicleUsageAdmin(admin.ModelAdmin):
    """
    Admin interface for VehicleUsage model.
    Primarily for reporting and monitoring vehicle usage patterns.
    """

    # Display configuration
    list_display = (
        "time_entry_display",
        "vehicle",
        "start_kilometers",
        "end_kilometers",
        "daily_distance",
        "no_vehicle_used",
        "created_at",
    )

    list_filter = (
        "no_vehicle_used",
        "time_entry__date",
        "vehicle",
        "time_entry__user",
        "created_at",
    )

    search_fields = (
        "time_entry__user__first_name",
        "time_entry__user__last_name",
        "vehicle__license_plate",
        "vehicle__make",
        "vehicle__model",
        "notes",
    )

    date_hierarchy = "time_entry__date"
    ordering = ("-time_entry__date",)

    # Form configuration
    fieldsets = (
        (
            "Verknüpfung",
            {
                "fields": ("time_entry",),
            },
        ),
        (
            "Fahrzeug-Nutzung",
            {
                "fields": (
                    "vehicle",
                    "no_vehicle_used",
                    "start_kilometers",
                    "end_kilometers",
                ),
            },
        ),
        (
            "Zusätzliche Informationen",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("daily_distance", "created_at", "updated_at")

    def time_entry_display(self, obj):
        """Display time entry information."""
        return f"{obj.time_entry.user.get_full_name()} - {obj.time_entry.date}"

    time_entry_display.short_description = "Zeiteintrag"

    def daily_distance(self, obj):
        """Display calculated daily distance."""
        distance = obj.daily_distance
        if distance > 0:
            return f"{distance} km"
        return "-"

    daily_distance.short_description = "Tageskilometer"

    # Custom actions
    actions = ["export_mileage_report"]

    def export_mileage_report(self, request, queryset):
        """Export vehicle usage data to CSV."""
        import csv

        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="fahrzeugnutzung.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Datum",
                "Mitarbeiter",
                "Fahrzeug",
                "Kennzeichen",
                "Anfangs-km",
                "End-km",
                "Tageskilometer",
                "Kein Fahrzeug",
                "Notizen",
            ]
        )

        for usage in queryset.select_related("time_entry__user", "vehicle"):
            writer.writerow(
                [
                    usage.time_entry.date,
                    usage.time_entry.user.get_full_name(),
                    str(usage.vehicle) if usage.vehicle else "Kein Fahrzeug",
                    usage.vehicle.license_plate if usage.vehicle else "-",
                    usage.start_kilometers or "-",
                    usage.end_kilometers or "-",
                    usage.daily_distance or "-",
                    "Ja" if usage.no_vehicle_used else "Nein",
                    usage.notes or "",
                ]
            )

        return response

    export_mileage_report.short_description = "Fahrzeugnutzung als CSV exportieren"

    def has_add_permission(self, request):
        """VehicleUsage records are created automatically with TimeEntry."""
        # Generally, these should be created through time entry forms
        return (
            super().has_add_permission(request)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_change_permission(self, request, obj=None):
        """Allow backoffice to modify, restrict employees to their own records."""
        if not super().has_change_permission(request, obj):
            return False

        if not request.user.is_authenticated:
            return False

        if request.user.is_backoffice:
            return True

        # Employees can edit their own vehicle usage records
        if obj is not None:
            return request.user.is_employee and obj.time_entry.user == request.user

        return request.user.is_employee

    def has_delete_permission(self, request, obj=None):
        """Only backoffice can delete vehicle usage records."""
        return (
            super().has_delete_permission(request, obj)
            and request.user.is_authenticated
            and request.user.is_backoffice
        )

    def has_view_permission(self, request, obj=None):
        """All authenticated users can view vehicle usage (with filtering)."""
        return (
            super().has_view_permission(request, obj) and request.user.is_authenticated
        )

    def get_queryset(self, request):
        """Filter queryset based on user role."""
        queryset = (
            super().get_queryset(request).select_related("time_entry__user", "vehicle")
        )

        if request.user.is_superuser or request.user.is_backoffice:
            return queryset

        # Employees can only see their own vehicle usage records
        if request.user.is_employee:
            return queryset.filter(time_entry__user=request.user)

        # Default: no access
        return queryset.none()

    def get_actions(self, request):
        """Filter available actions based on user role."""
        actions = super().get_actions(request)

        # Only backoffice users can export mileage reports
        if not request.user.is_backoffice:
            if "export_mileage_report" in actions:
                del actions["export_mileage_report"]

        return actions
