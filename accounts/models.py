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

    # Vehicle assignment (will be populated after Vehicle model is created)
    default_vehicle = models.ForeignKey(
        "Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Standard-Fahrzeug",
        help_text="Standard-Fahrzeug für diesen Mitarbeiter",
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
            return (
                f"{self.employee.get_full_name()} - "
                f"jeden {self.day_of_month}. des Monats"
            )
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
                    "weekday": (
                        "Wochentag ist erforderlich bei "
                        "wöchentlich wiederkehrenden Tagen."
                    )
                }
            )

        if self.pattern == "monthly" and not self.day_of_month:
            raise ValidationError(
                {
                    "day_of_month": (
                        "Tag des Monats ist erforderlich bei "
                        "monatlich wiederkehrenden Tagen."
                    )
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


class Vehicle(models.Model):
    """
    Model representing company vehicles that can be used by employees.
    Tracks vehicle information for fleet management and mileage tracking.
    """

    FUEL_CHOICES = [
        ("petrol", "Benzin"),
        ("diesel", "Diesel"),
        ("electric", "Elektro"),
        ("hybrid", "Hybrid"),
        ("other", "Sonstiges"),
    ]

    license_plate = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Kennzeichen",
        help_text="Fahrzeugkennzeichen (eindeutig)",
    )

    make = models.CharField(
        max_length=50,
        verbose_name="Marke",
        help_text="Fahrzeughersteller (z.B. 'Volkswagen', 'BMW')",
    )

    model = models.CharField(
        max_length=50,
        verbose_name="Modell",
        help_text="Fahrzeugmodell (z.B. 'Golf', '3er')",
    )

    year = models.PositiveIntegerField(
        verbose_name="Baujahr",
        help_text="Baujahr des Fahrzeugs",
    )

    color = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Farbe",
        help_text="Fahrzeugfarbe (optional)",
    )

    fuel_type = models.CharField(
        max_length=20,
        choices=FUEL_CHOICES,
        default="petrol",
        verbose_name="Kraftstoffart",
        help_text="Art des Kraftstoffs",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktiv",
        help_text="Ist das Fahrzeug derzeit verfügbar?",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Notizen",
        help_text="Zusätzliche Informationen zum Fahrzeug",
    )

    # Audit fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Aktualisiert am",
    )

    class Meta:
        verbose_name = "Fahrzeug"
        verbose_name_plural = "Fahrzeuge"
        ordering = ["license_plate"]

    def __str__(self):
        return f"{self.license_plate} ({self.make} {self.model})"

    def clean(self):
        """Validate vehicle data."""
        super().clean()

        if self.year and self.year < 1900:
            raise ValidationError({"year": "Baujahr muss nach 1900 liegen."})

        if self.year and self.year > timezone.now().year + 1:
            raise ValidationError({"year": "Baujahr kann nicht in der Zukunft liegen."})

        # Clean license plate - remove spaces and convert to uppercase
        if self.license_plate:
            self.license_plate = self.license_plate.replace(" ", "").upper()


class VehicleUsage(models.Model):
    """
    Model representing vehicle usage linked to time entries.
    Tracks mileage and vehicle selection for individual work days.
    """

    time_entry = models.OneToOneField(
        TimeEntry,
        on_delete=models.CASCADE,
        verbose_name="Zeiteintrag",
        help_text="Verknüpfter Zeiteintrag",
    )

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Fahrzeug",
        help_text="Verwendetes Fahrzeug (leer wenn kein Fahrzeug verwendet)",
    )

    start_kilometers = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Anfangs-km",
        help_text="Kilometerstand zu Beginn der Arbeitszeit",
    )

    end_kilometers = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="End-km",
        help_text="Kilometerstand am Ende der Arbeitszeit",
    )

    no_vehicle_used = models.BooleanField(
        default=False,
        verbose_name="Kein Fahrzeug verwendet",
        help_text="Aktivieren wenn kein Fahrzeug verwendet wurde",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Notizen",
        help_text="Zusätzliche Informationen zur Fahrzeugnutzung",
    )

    # Audit fields
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Aktualisiert am",
    )

    class Meta:
        verbose_name = "Fahrzeugnutzung"
        verbose_name_plural = "Fahrzeugnutzungen"
        ordering = ["-time_entry__date"]

    def __str__(self):
        if self.no_vehicle_used:
            return (
                f"{self.time_entry.user.get_full_name()} - "
                f"{self.time_entry.date} (Kein Fahrzeug)"
            )
        elif self.vehicle:
            return (
                f"{self.time_entry.user.get_full_name()} - "
                f"{self.time_entry.date} ({self.vehicle.license_plate})"
            )
        else:
            return (
                f"{self.time_entry.user.get_full_name()} - " f"{self.time_entry.date}"
            )

    @property
    def daily_distance(self):
        """Calculate distance traveled in kilometers."""
        if self.start_kilometers and self.end_kilometers and not self.no_vehicle_used:
            return max(0, self.end_kilometers - self.start_kilometers)
        return 0

    def clean(self):
        """Validate vehicle usage data."""
        super().clean()

        if not self.no_vehicle_used:
            # If vehicle is used, require mileage data
            if self.vehicle and (
                self.start_kilometers is None or self.end_kilometers is None
            ):
                raise ValidationError(
                    "Bei Fahrzeugnutzung müssen Anfangs- und "
                    "End-Kilometer angegeben werden."
                )

            # Validate mileage logic
            if (
                self.start_kilometers is not None
                and self.end_kilometers is not None
                and self.end_kilometers < self.start_kilometers
            ):
                raise ValidationError(
                    {
                        "end_kilometers": (
                            "End-Kilometer muss größer als " "Anfangs-Kilometer sein."
                        )
                    }
                )

            # Check for reasonable daily distance (warning for > 500km)
            if self.daily_distance > 500:
                raise ValidationError(
                    f"Tägliche Fahrtstrecke von {self.daily_distance}km "
                    f"erscheint ungewöhnlich hoch. Bitte prüfen Sie die Eingabe."
                )

        else:
            # If no vehicle is used, clear vehicle-related fields
            self.vehicle = None
            self.start_kilometers = None
            self.end_kilometers = None


class FuelReceipt(models.Model):
    """
    Model representing fuel receipts uploaded by employees.
    Stores receipt information and links to S3-stored receipt images.
    Implements US-C09: Fuel Receipt Tracking with S3 Storage.
    """

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    # Core fields
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        verbose_name="Fahrzeug",
        help_text="Fahrzeug für das der Tankbeleg eingereicht wird",
    )

    employee = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        verbose_name="Mitarbeiter",
        help_text="Mitarbeiter der den Beleg eingereicht hat",
        related_name="fuel_receipts",
    )

    odometer_reading = models.PositiveIntegerField(
        verbose_name="Kilometerstand",
        help_text="Kilometerstand zum Zeitpunkt des Tankens",
    )

    receipt_date = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Eingereicht am",
        help_text="Zeitpunkt der Belegeinreichung",
    )

    # Receipt image stored in S3
    receipt_image = models.ImageField(
        upload_to="fuel-receipts/%Y/%m/",
        verbose_name="Beleg-Bild",
        help_text="Foto oder Scan des Tankbelegs",
    )

    # Optional fuel purchase details
    fuel_amount_liters = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Kraftstoffmenge (Liter)",
        help_text="Getankte Kraftstoffmenge in Litern",
    )

    total_cost = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Gesamtkosten (€)",
        help_text="Gesamtkosten des Tankvorgangs",
    )

    gas_station = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Tankstelle",
        help_text="Name/Marke der Tankstelle",
    )

    fuel_purchase_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Tankdatum",
        help_text="Datum des Tankvorgangs (falls abweichend vom Upload)",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Notizen",
        help_text="Zusätzliche Bemerkungen zum Tankbeleg",
    )

    # Administrative fields
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="Status",
        help_text="Bearbeitungsstatus des Belegs",
    )

    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_receipts",
        verbose_name="Genehmigt von",
        help_text="Backoffice-Mitarbeiter der den Beleg genehmigt hat",
    )

    rejection_reason = models.TextField(
        blank=True,
        verbose_name="Ablehnungsgrund",
        help_text="Grund für die Ablehnung des Belegs",
    )

    # Metadata
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Aktualisiert am",
    )

    class Meta:
        verbose_name = "Tankbeleg"
        verbose_name_plural = "Tankbelege"
        ordering = ["-receipt_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(fuel_amount_liters__gte=0),
                name="positive_fuel_amount",
                violation_error_message="Kraftstoffmenge muss positiv sein.",
            ),
            models.CheckConstraint(
                check=models.Q(total_cost__gte=0),
                name="positive_total_cost",
                violation_error_message="Gesamtkosten müssen positiv sein.",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee.get_full_name()} - "
            f"{self.vehicle.license_plate} - "
            f"{self.receipt_date.strftime('%d.%m.%Y')}"
        )

    def clean(self):
        """Validate fuel receipt data."""
        super().clean()

        # Validate odometer reading is reasonable
        if self.odometer_reading and self.odometer_reading > 9999999:
            raise ValidationError(
                {"odometer_reading": "Kilometerstand erscheint unrealistisch hoch."}
            )

        # Check if odometer reading is higher than previous readings for this vehicle
        if self.vehicle_id and self.odometer_reading:
            latest_receipt = (
                FuelReceipt.objects.filter(vehicle=self.vehicle)
                .exclude(pk=self.pk)
                .order_by("-odometer_reading")
                .first()
            )

            if latest_receipt and self.odometer_reading < latest_receipt.odometer_reading:
                raise ValidationError(
                    {
                        "odometer_reading": (
                            f"Kilometerstand ({self.odometer_reading}km) muss höher sein "
                            f"als der letzte Eintrag ({latest_receipt.odometer_reading}km)."
                        )
                    }
                )

        # Validate fuel purchase date is not in the future
        if self.fuel_purchase_date and self.fuel_purchase_date > timezone.now().date():
            raise ValidationError(
                {"fuel_purchase_date": "Tankdatum kann nicht in der Zukunft liegen."}
            )

        # Validate fuel purchase date is not too old (30 days limit)
        if self.fuel_purchase_date:
            days_diff = (timezone.now().date() - self.fuel_purchase_date).days
            if days_diff > 30:
                raise ValidationError(
                    {
                        "fuel_purchase_date": (
                            "Tankdatum liegt mehr als 30 Tage zurück. "
                            "Belege müssen zeitnah eingereicht werden."
                        )
                    }
                )

    @property
    def can_be_edited(self):
        """Check if receipt can still be edited (within 24 hours and pending status)."""
        if self.status != "pending":
            return False

        # Check if within 24-hour edit window
        time_diff = timezone.now() - self.created_at
        return time_diff.total_seconds() < 24 * 60 * 60  # 24 hours in seconds

    @property
    def days_since_upload(self):
        """Calculate days since upload."""
        time_diff = timezone.now() - self.created_at
        return time_diff.days

    def approve(self, approved_by_user):
        """Approve the fuel receipt."""
        if self.status == "approved":
            raise ValidationError("Beleg ist bereits genehmigt.")

        self.status = "approved"
        self.approved_by = approved_by_user
        self.rejection_reason = ""
        self.save()

    def reject(self, rejected_by_user, reason):
        """Reject the fuel receipt with a reason."""
        if self.status == "approved":
            raise ValidationError("Genehmigte Belege können nicht abgelehnt werden.")

        self.status = "rejected"
        self.approved_by = rejected_by_user
        self.rejection_reason = reason
        self.save()
