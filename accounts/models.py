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
            is_overnight_shift = self.start_time.hour >= 18 and self.end_time.hour <= 12

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


class PublicHoliday(models.Model):
    """
    Model representing public holidays that apply to all employees.
    Supports both one-time holidays and annually recurring holidays.
    """

    name = models.CharField(
        max_length=100,
        verbose_name="Name",
        help_text="Name des Feiertags (z.B. 'Neujahr', 'Weihnachten')",
    )

    date = models.DateField(verbose_name="Datum", help_text="Datum des Feiertags")

    is_recurring = models.BooleanField(
        default=False,
        verbose_name="Jährlich wiederkehrend",
        help_text="Wiederholt sich dieser Feiertag jährlich am gleichen Datum?",
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Beschreibung",
        help_text="Optionale Beschreibung des Feiertags",
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="Aktualisiert am")

    class Meta:
        verbose_name = "Feiertag"
        verbose_name_plural = "Feiertage"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "date"], name="unique_holiday_name_date"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.date.strftime('%d.%m.%Y')})"

    @classmethod
    def get_holidays_for_year(cls, year):
        """
        Get all holidays for a specific year, including recurring holidays.
        Returns QuerySet of PublicHoliday objects.
        """
        from datetime import date

        # Get holidays for the year
        # Get holidays that apply to this year

        # Get holidays that fall within the year (both one-time and recurring)
        holidays = cls.objects.filter(
            models.Q(date__year=year)  # Exact year match
            | models.Q(
                is_recurring=True
            )  # Recurring holidays (filter by month/day later)
        )

        return holidays

    def applies_to_date(self, check_date):
        """
        Check if this holiday applies to a given date.
        For recurring holidays, checks month and day match.
        """
        if self.is_recurring:
            return (
                self.date.month == check_date.month and self.date.day == check_date.day
            )
        else:
            return self.date == check_date


class EmployeeNonWorkingDay(models.Model):
    """
    Model representing non-working days specific to individual employees.
    Allows configuration of employee-specific days off (beyond weekends/holidays).
    """

    PATTERN_CHOICES = [
        ("specific", "Spezifisches Datum"),
        ("weekly", "Wöchentlich wiederkehrend"),
        ("monthly", "Monatlich wiederkehrend"),
    ]

    WEEKDAY_CHOICES = [
        (0, "Montag"),
        (1, "Dienstag"),
        (2, "Mittwoch"),
        (3, "Donnerstag"),
        (4, "Freitag"),
        (5, "Samstag"),
        (6, "Sonntag"),
    ]

    employee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "employee"},
        verbose_name="Mitarbeiter",
        help_text="Mitarbeiter für den dieser arbeitsfreie Tag gilt",
    )

    pattern = models.CharField(
        max_length=20,
        choices=PATTERN_CHOICES,
        default="specific",
        verbose_name="Muster",
        help_text="Art des arbeitsfreien Tages",
    )

    # For specific dates
    date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Datum",
        help_text="Spezifisches Datum (nur bei 'Spezifisches Datum')",
    )

    # For weekly recurring (e.g., every Friday)
    weekday = models.PositiveSmallIntegerField(
        choices=WEEKDAY_CHOICES,
        blank=True,
        null=True,
        verbose_name="Wochentag",
        help_text="Wochentag (nur bei 'Wöchentlich wiederkehrend')",
    )

    # For monthly recurring (e.g., first Monday of each month)
    day_of_month = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name="Tag des Monats",
        help_text="Tag des Monats (nur bei 'Monatlich wiederkehrend')",
    )

    # Validity period
    valid_from = models.DateField(
        blank=True,
        null=True,
        verbose_name="Gültig ab",
        help_text="Startdatum der Gültigkeit (optional)",
    )

    valid_until = models.DateField(
        blank=True,
        null=True,
        verbose_name="Gültig bis",
        help_text="Enddatum der Gültigkeit (optional)",
    )

    reason = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Grund",
        help_text="Grund für den arbeitsfreien Tag (z.B. 'Teilzeit', 'Urlaub')",
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="Aktualisiert am")

    class Meta:
        verbose_name = "Arbeitsfreier Tag (Mitarbeiter)"
        verbose_name_plural = "Arbeitsfreie Tage (Mitarbeiter)"
        ordering = ["employee", "date", "weekday"]

    def __str__(self):
        if self.pattern == "specific" and self.date:
            return f"{self.employee.get_full_name()} - {self.date.strftime('%d.%m.%Y')}"
        elif self.pattern == "weekly" and self.weekday is not None:
            weekday_name = dict(self.WEEKDAY_CHOICES)[self.weekday]
            return f"{self.employee.get_full_name()} - jeden {weekday_name}"
        elif self.pattern == "monthly" and self.day_of_month:
            return f"{self.employee.get_full_name()} - jeden {self.day_of_month}. des Monats"
        else:
            return f"{self.employee.get_full_name()} - {self.get_pattern_display()}"

    def clean(self):
        """Validate the non-working day configuration."""
        super().clean()

        if self.pattern == "specific" and not self.date:
            raise ValidationError(
                {"date": "Datum ist erforderlich bei spezifischen Daten."}
            )

        if self.pattern == "weekly" and self.weekday is None:
            raise ValidationError(
                {
                    "weekday": "Wochentag ist erforderlich bei wöchentlich wiederkehrenden Tagen."
                }
            )

        if self.pattern == "monthly" and not self.day_of_month:
            raise ValidationError(
                {
                    "day_of_month": "Tag des Monats ist erforderlich bei monatlich wiederkehrenden Tagen."
                }
            )

        if self.day_of_month and (self.day_of_month < 1 or self.day_of_month > 31):
            raise ValidationError(
                {"day_of_month": "Tag des Monats muss zwischen 1 und 31 liegen."}
            )

        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValidationError(
                {"valid_until": "Enddatum muss nach dem Startdatum liegen."}
            )

    def applies_to_date(self, check_date):
        """
        Check if this non-working day applies to a given date.
        """
        # Check validity period
        if self.valid_from and check_date < self.valid_from:
            return False
        if self.valid_until and check_date > self.valid_until:
            return False

        # Check pattern match
        if self.pattern == "specific":
            return self.date == check_date
        elif self.pattern == "weekly":
            return check_date.weekday() == self.weekday
        elif self.pattern == "monthly":
            return check_date.day == self.day_of_month

        return False
