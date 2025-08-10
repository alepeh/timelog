from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Adds employee role functionality for the timelog system.
    """

    ROLE_CHOICES = [
        ("employee", "Mitarbeiter"),
        ("backoffice", "Backoffice"),
    ]

    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default="employee", verbose_name="Rolle"
    )

    # Track invitation and first login status
    is_invited = models.BooleanField(default=False, verbose_name="Eingeladen")

    first_login_token = models.CharField(
        max_length=64, blank=True, null=True, verbose_name="Erstanmeldung Token"
    )

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display()})"

    @property
    def is_backoffice(self):
        """Check if user has backoffice role."""
        return self.role == "backoffice"

    @property
    def is_employee(self):
        """Check if user has employee role."""
        return self.role == "employee"


class TimeEntry(models.Model):
    """
    Model representing a time entry for an employee.
    Tracks daily work time, breaks, and environmental conditions.
    """

    POLLUTION_CHOICES = [
        (1, "Niedrig"),
        (2, "Mittel"),
        (3, "Hoch"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="Benutzer",
        help_text="Der Mitarbeiter für diesen Zeiteintrag",
    )

    date = models.DateField(
        verbose_name="Datum",
        help_text="Arbeitstag für diesen Zeiteintrag",
    )

    start_time = models.TimeField(
        verbose_name="Startzeit",
        help_text="Beginn der Arbeitszeit",
    )

    end_time = models.TimeField(
        verbose_name="Endzeit",
        help_text="Ende der Arbeitszeit",
    )

    lunch_break_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name="Mittagspause (Minuten)",
        help_text="Dauer der Mittagspause in Minuten",
    )

    pollution_level = models.PositiveSmallIntegerField(
        choices=POLLUTION_CHOICES,
        default=1,
        verbose_name="Verschmutzungsgrad",
        help_text=(
            "Grad der Umweltverschmutzung am Arbeitsplatz "
            "(1=niedrig, 2=mittel, 3=hoch)"
        ),
    )

    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Notizen",
        help_text="Optionale Notizen zum Arbeitstag",
    )

    # Audit fields
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_time_entries",
        verbose_name="Erstellt von",
        help_text="Benutzer, der diesen Eintrag erstellt hat",
    )

    updated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="updated_time_entries",
        verbose_name="Aktualisiert von",
        help_text="Benutzer, der diesen Eintrag zuletzt aktualisiert hat",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Aktualisiert am",
    )

    class Meta:
        verbose_name = "Zeiteintrag"
        verbose_name_plural = "Zeiteinträge"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"],
                name="unique_user_date",
            ),
        ]
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.date}"

    def clean(self):
        """Validate the time entry data."""
        super().clean()

        if self.start_time and self.end_time:
            # Check if this is potentially an overnight shift
            # Overnight shifts: start after 18:00 AND end before 12:00
            is_overnight_shift = (
                self.start_time.hour >= 18 and self.end_time.hour <= 12
            )
            
            if self.start_time >= self.end_time and not is_overnight_shift:
                raise ValidationError(
                    {"end_time": "Endzeit muss nach der Startzeit liegen."}
                )

        if self.lunch_break_minutes < 0:
            raise ValidationError(
                {"lunch_break_minutes": "Mittagspause kann nicht negativ sein."}
            )

        if self.date and self.date > timezone.now().date():
            raise ValidationError({"date": "Datum kann nicht in der Zukunft liegen."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def total_work_minutes(self):
        """Calculate total work time in minutes, excluding lunch break."""
        if not self.start_time or not self.end_time:
            return 0

        start_minutes = self.start_time.hour * 60 + self.start_time.minute
        end_minutes = self.end_time.hour * 60 + self.end_time.minute

        # Handle overnight work (end time next day)
        if end_minutes <= start_minutes:
            end_minutes += 24 * 60

        work_minutes = end_minutes - start_minutes - self.lunch_break_minutes
        return max(0, work_minutes)

    @property
    def total_work_hours(self):
        """Calculate total work time in hours."""
        return self.total_work_minutes / 60
