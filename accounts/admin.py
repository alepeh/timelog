import hashlib
import secrets

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.mail import send_mail

from .models import TimeEntry, User


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
                "fields": ("role", "is_invited", "first_login_token"),
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
        """Optimize queryset with select_related."""
        return (
            super()
            .get_queryset(request)
            .select_related("user", "created_by", "updated_by")
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
