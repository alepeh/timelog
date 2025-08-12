from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
import os

from .models import TimeEntry, User, Vehicle, VehicleUsage, FuelReceipt


class CreateEmployeeForm(forms.ModelForm):
    """
    Form for creating new employee accounts by backoffice users.
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role"]
        labels = {
            "first_name": "Vorname",
            "last_name": "Nachname",
            "email": "E-Mail-Adresse",
            "role": "Rolle",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise ValidationError(
                "Ein Benutzer mit dieser E-Mail-Adresse existiert bereits."
            )
        return email

    def clean_first_name(self):
        first_name = self.cleaned_data.get("first_name")
        if not first_name or not first_name.strip():
            raise ValidationError("Vorname ist erforderlich.")
        return first_name.strip()

    def clean_last_name(self):
        last_name = self.cleaned_data.get("last_name")
        if not last_name or not last_name.strip():
            raise ValidationError("Nachname ist erforderlich.")
        return last_name.strip()


class TimeEntryForm(forms.ModelForm):
    """
    Form for employees to create and edit their daily time entries.
    Covers US-C01 (time tracking), US-C02 (lunch breaks), US-C03 (pollution level),
    and US-C08 (vehicle tracking with mileage).
    """

    # Vehicle tracking fields (US-C08)
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.filter(is_active=True),
        required=False,
        empty_label="Fahrzeug auswählen...",
        label="Fahrzeug",
        help_text="Wählen Sie das verwendete Firmenfahrzeug",
        widget=forms.Select(attrs={"class": "form-control vehicle-field"}),
    )

    no_vehicle_used = forms.BooleanField(
        required=False,
        label="Kein Fahrzeug verwendet",
        help_text="Aktivieren Sie diese Option, wenn Sie kein Fahrzeug verwendet haben",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input", "id": "id_no_vehicle_used"}
        ),
    )

    start_kilometers = forms.IntegerField(
        required=False,
        min_value=0,
        label="Anfangs-km",
        help_text="Kilometerstand zu Beginn der Arbeitszeit",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control vehicle-field",
                "placeholder": "z.B. 50000",
                "min": "0",
            }
        ),
    )

    end_kilometers = forms.IntegerField(
        required=False,
        min_value=0,
        label="End-km",
        help_text="Kilometerstand am Ende der Arbeitszeit",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control vehicle-field",
                "placeholder": "z.B. 50150",
                "min": "0",
            }
        ),
    )

    vehicle_notes = forms.CharField(
        required=False,
        label="Fahrzeug-Notizen",
        help_text="Zusätzliche Informationen zur Fahrzeugnutzung (optional)",
        widget=forms.Textarea(
            attrs={
                "class": "form-control vehicle-field",
                "rows": "2",
                "placeholder": "z.B. Kundentermin, Wartung, etc...",
            }
        ),
    )

    class Meta:
        model = TimeEntry
        fields = [
            "date",
            "start_time",
            "end_time",
            "lunch_break_minutes",
            "pollution_level",
            "notes",
        ]
        labels = {
            "date": "Datum",
            "start_time": "Startzeit",
            "end_time": "Endzeit",
            "lunch_break_minutes": "Mittagspause (Minuten)",
            "pollution_level": "Verschmutzungsgrad",
            "notes": "Notizen (optional)",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_time": forms.TimeInput(
                attrs={"type": "time", "class": "form-control"}
            ),
            "end_time": forms.TimeInput(
                attrs={"type": "time", "class": "form-control"}
            ),
            "lunch_break_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "max": "480"}
            ),
            "pollution_level": forms.Select(attrs={"class": "form-control"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": "3",
                    "placeholder": "Optionale Notizen zum Arbeitstag...",
                }
            ),
        }
        help_texts = {
            "lunch_break_minutes": "Angabe in Minuten (z.B. 30 für 30 Minuten)",
            "pollution_level": "1 = Niedrig, 2 = Mittel, 3 = Hoch",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Set default date to today
        if not self.instance.pk:
            self.fields["date"].initial = timezone.now().date()

            # Set default vehicle if user has one configured
            if self.user and self.user.default_vehicle:
                self.fields["vehicle"].initial = self.user.default_vehicle

        # For editing existing entries, populate vehicle usage data
        if self.instance.pk:
            try:
                vehicle_usage = VehicleUsage.objects.get(time_entry=self.instance)
                self.fields["vehicle"].initial = vehicle_usage.vehicle
                self.fields["no_vehicle_used"].initial = vehicle_usage.no_vehicle_used
                self.fields["start_kilometers"].initial = vehicle_usage.start_kilometers
                self.fields["end_kilometers"].initial = vehicle_usage.end_kilometers
                self.fields["vehicle_notes"].initial = vehicle_usage.notes
            except VehicleUsage.DoesNotExist:
                # No vehicle usage record exists for this time entry
                pass

    def clean_date(self):
        """Validate that date is not in the future."""
        date = self.cleaned_data.get("date")
        if date and date > timezone.now().date():
            raise ValidationError("Das Datum darf nicht in der Zukunft liegen.")
        return date

    def clean(self):
        """Validate the complete form data according to business rules."""
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        lunch_break_minutes = cleaned_data.get("lunch_break_minutes", 0)
        date = cleaned_data.get("date")

        # Calculate work time for all subsequent validations
        if start_time and end_time:
            # Calculate work time in minutes
            start_minutes = start_time.hour * 60 + start_time.minute
            end_minutes = end_time.hour * 60 + end_time.minute

            # Check for overnight shifts (start after 18:00 AND end before 12:00)
            is_overnight_shift = start_time.hour >= 18 and end_time.hour <= 12

            # Handle overnight work
            if end_minutes <= start_minutes:
                if not is_overnight_shift:
                    raise ValidationError("Die Endzeit muss nach der Startzeit liegen.")
                else:
                    end_minutes += 24 * 60

            total_work_minutes = end_minutes - start_minutes - lunch_break_minutes

            # US-C06: Validate no negative/zero duration
            if total_work_minutes <= 0:
                raise ValidationError(
                    "Die Arbeitszeit (ohne Pause) muss positiv sein. "
                    "Prüfen Sie Start-, Endzeit und Pausendauer."
                )

            # US-C06: Warning for very long workdays (>10h net)
            total_work_hours = total_work_minutes / 60
            if total_work_hours > 10:
                # Store warning in form for template to display
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    f"Achtung: Sehr langer Arbeitstag "
                    f"({total_work_hours:.1f} Stunden netto). "
                    "Bitte prüfen Sie die Zeitangaben."
                )

        # US-C06: Confirmation for weekend work
        if date:
            # Check if date is weekend (Saturday=5, Sunday=6)
            if date.weekday() in [5, 6]:  # Saturday or Sunday
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                day_name = "Samstag" if date.weekday() == 5 else "Sonntag"
                self._warnings.append(
                    f"Hinweis: Arbeit am {day_name} ({date.strftime('%d.%m.%Y')}). "
                    "Bitte bestätigen Sie, dass dies korrekt ist."
                )

        # Validate uniqueness per user/date if creating new entry
        if self.user and date:
            existing_entry = TimeEntry.objects.filter(
                user=self.user, date=date
            ).exclude(pk=self.instance.pk if self.instance.pk else None)

            if existing_entry.exists():
                raise ValidationError(
                    f"Für das Datum {date} existiert bereits ein Zeiteintrag."
                )

        # US-C08: Vehicle usage validation
        self._validate_vehicle_usage(cleaned_data)

        return cleaned_data

    def get_warnings(self):
        """Get list of validation warnings (non-blocking)."""
        return getattr(self, "_warnings", [])

    def _validate_vehicle_usage(self, cleaned_data):
        """Validate vehicle usage fields according to business rules."""
        vehicle = cleaned_data.get("vehicle")
        no_vehicle_used = cleaned_data.get("no_vehicle_used", False)
        start_kilometers = cleaned_data.get("start_kilometers")
        end_kilometers = cleaned_data.get("end_kilometers")

        # Clear vehicle-related fields if no vehicle is used
        if no_vehicle_used:
            cleaned_data["vehicle"] = None
            cleaned_data["start_kilometers"] = None
            cleaned_data["end_kilometers"] = None
            return

        # If vehicle is selected, validate mileage requirements
        if vehicle:
            if start_kilometers is None or end_kilometers is None:
                raise ValidationError(
                    "Bei Fahrzeugnutzung müssen Anfangs- und "
                    "End-Kilometer angegeben werden."
                )

            # Validate mileage logic
            if end_kilometers < start_kilometers:
                raise ValidationError(
                    {
                        "end_kilometers": (
                            "End-Kilometer muss größer als " "Anfangs-Kilometer sein."
                        )
                    }
                )

            # Check for reasonable daily distance
            daily_distance = end_kilometers - start_kilometers
            if daily_distance > 500:
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    f"Achtung: Sehr hohe Tageskilometer ({daily_distance}km). "
                    "Bitte prüfen Sie die Kilometerangaben."
                )

            # Warn for very low mileage (might indicate input error)
            if daily_distance == 0:
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    "Hinweis: Keine Kilometer gefahren (0km). "
                    "Ist dies korrekt oder haben Sie vergessen die "
                    "Kilometerangaben anzupassen?"
                )

    def save(self, commit=True):
        """Save the time entry and create/update associated vehicle usage."""
        # Set required fields if not already set
        time_entry = super().save(commit=False)

        if not time_entry.user_id:
            time_entry.user = self.user
        if not time_entry.created_by_id:
            time_entry.created_by = self.user
        time_entry.updated_by = self.user

        if commit:
            time_entry.save()
            # Handle vehicle usage data
            self._save_vehicle_usage(time_entry)

        return time_entry

    def _save_vehicle_usage(self, time_entry):
        """Create or update VehicleUsage record for the time entry."""
        vehicle = self.cleaned_data.get("vehicle")
        no_vehicle_used = self.cleaned_data.get("no_vehicle_used", False)
        start_kilometers = self.cleaned_data.get("start_kilometers")
        end_kilometers = self.cleaned_data.get("end_kilometers")
        vehicle_notes = self.cleaned_data.get("vehicle_notes", "")

        # Get or create vehicle usage record
        vehicle_usage, created = VehicleUsage.objects.get_or_create(
            time_entry=time_entry,
            defaults={
                "vehicle": vehicle,
                "start_kilometers": start_kilometers,
                "end_kilometers": end_kilometers,
                "no_vehicle_used": no_vehicle_used,
                "notes": vehicle_notes,
            },
        )

        # Update existing record if not created
        if not created:
            vehicle_usage.vehicle = vehicle
            vehicle_usage.start_kilometers = start_kilometers
            vehicle_usage.end_kilometers = end_kilometers
            vehicle_usage.no_vehicle_used = no_vehicle_used
            vehicle_usage.notes = vehicle_notes
            vehicle_usage.save()


class FuelReceiptForm(forms.ModelForm):
    """
    Form for employees to upload fuel receipts with vehicle and odometer information.
    Implements US-C09: Fuel Receipt Tracking with S3 Storage.
    """

    class Meta:
        model = FuelReceipt
        fields = [
            "vehicle",
            "odometer_reading",
            "receipt_image",
            "fuel_amount_liters",
            "total_cost",
            "gas_station",
            "fuel_purchase_date",
            "notes",
        ]
        labels = {
            "vehicle": "Fahrzeug",
            "odometer_reading": "Kilometerstand",
            "receipt_image": "Beleg-Foto",
            "fuel_amount_liters": "Kraftstoffmenge (Liter)",
            "total_cost": "Gesamtkosten (€)",
            "gas_station": "Tankstelle",
            "fuel_purchase_date": "Tankdatum",
            "notes": "Notizen",
        }
        widgets = {
            "vehicle": forms.Select(attrs={"class": "form-control"}),
            "odometer_reading": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "placeholder": "z.B. 75000",
                }
            ),
            "receipt_image": forms.FileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*,.pdf",
                    "capture": "environment",  # Mobile camera hint
                }
            ),
            "fuel_amount_liters": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.01",
                    "placeholder": "z.B. 45.50",
                }
            ),
            "total_cost": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.01",
                    "placeholder": "z.B. 67.85",
                }
            ),
            "gas_station": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "z.B. Shell, Aral, ESSO...",
                }
            ),
            "fuel_purchase_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": "3",
                    "placeholder": "Zusätzliche Bemerkungen zum Tankvorgang...",
                }
            ),
        }
        help_texts = {
            "vehicle": "Wählen Sie das Fahrzeug aus, für das Sie tanken",
            "odometer_reading": "Aktueller Kilometerstand zum Zeitpunkt des Tankens",
            "receipt_image": "Foto oder Scan des Tankbelegs (max. 10MB, JPG/PNG/PDF)",
            "fuel_amount_liters": "Getankte Menge in Litern (optional)",
            "total_cost": "Gesamtbetrag in Euro (optional)",
            "gas_station": "Name oder Marke der Tankstelle (optional)",
            "fuel_purchase_date": "Datum des Tankvorgangs (falls abweichend von heute)",
            "notes": "Zusätzliche Informationen zum Tankvorgang",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Filter vehicles based on user permissions
        if self.user:
            # For now, show all active vehicles
            # Later can be extended with user-specific vehicle permissions
            self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True)

        # Set default fuel purchase date to today
        if not self.instance.pk:
            self.fields["fuel_purchase_date"].initial = timezone.now().date()

    def clean_receipt_image(self):
        """Validate receipt image file."""
        image = self.cleaned_data.get("receipt_image")
        
        if not image:
            raise ValidationError("Bitte laden Sie ein Foto des Tankbelegs hoch.")

        # Check file size
        if image.size > settings.MAX_RECEIPT_FILE_SIZE:
            raise ValidationError(
                f"Die Datei ist zu groß. Maximale Größe: "
                f"{settings.MAX_RECEIPT_FILE_SIZE // (1024*1024)}MB."
            )

        # Check file extension
        file_extension = os.path.splitext(image.name)[1].lower()
        if file_extension not in settings.ALLOWED_RECEIPT_EXTENSIONS:
            allowed_extensions = ", ".join(settings.ALLOWED_RECEIPT_EXTENSIONS)
            raise ValidationError(
                f"Dateityp nicht erlaubt. Erlaubte Formate: {allowed_extensions}"
            )

        return image

    def clean_odometer_reading(self):
        """Validate odometer reading against previous receipts."""
        odometer_reading = self.cleaned_data.get("odometer_reading")
        vehicle = self.cleaned_data.get("vehicle")

        if not odometer_reading or not vehicle:
            return odometer_reading

        # Check against previous receipts for this vehicle
        latest_receipt = (
            FuelReceipt.objects.filter(vehicle=vehicle)
            .exclude(pk=self.instance.pk if self.instance.pk else None)
            .order_by("-odometer_reading")
            .first()
        )

        if latest_receipt and odometer_reading < latest_receipt.odometer_reading:
            raise ValidationError(
                f"Kilometerstand ({odometer_reading}km) muss höher sein als "
                f"der letzte Eintrag ({latest_receipt.odometer_reading}km) "
                f"vom {latest_receipt.receipt_date.strftime('%d.%m.%Y')}."
            )

        # Check against vehicle usage data (if available)
        latest_usage = (
            VehicleUsage.objects.filter(vehicle=vehicle, end_kilometers__isnull=False)
            .order_by("-time_entry__date")
            .first()
        )

        if latest_usage and odometer_reading < latest_usage.end_kilometers:
            raise ValidationError(
                f"Kilometerstand ({odometer_reading}km) muss höher sein als "
                f"der letzte Fahrteneintrag ({latest_usage.end_kilometers}km) "
                f"vom {latest_usage.time_entry.date.strftime('%d.%m.%Y')}."
            )

        return odometer_reading

    def clean_fuel_purchase_date(self):
        """Validate fuel purchase date."""
        fuel_purchase_date = self.cleaned_data.get("fuel_purchase_date")

        if not fuel_purchase_date:
            return fuel_purchase_date

        # Check if date is not in the future
        if fuel_purchase_date > timezone.now().date():
            raise ValidationError("Tankdatum kann nicht in der Zukunft liegen.")

        # Check if date is not too old (30 days limit)
        days_diff = (timezone.now().date() - fuel_purchase_date).days
        if days_diff > 30:
            raise ValidationError(
                "Tankdatum liegt mehr als 30 Tage zurück. "
                "Belege müssen zeitnah eingereicht werden."
            )

        return fuel_purchase_date

    def clean(self):
        """Validate the complete form data."""
        cleaned_data = super().clean()
        fuel_amount = cleaned_data.get("fuel_amount_liters")
        total_cost = cleaned_data.get("total_cost")

        # If both fuel amount and cost are provided, check if cost per liter is reasonable
        if fuel_amount and total_cost and fuel_amount > 0:
            cost_per_liter = total_cost / fuel_amount
            if cost_per_liter > 3.0:  # €3.00 per liter seems high
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    f"Preis pro Liter ({cost_per_liter:.2f}€/L) erscheint hoch. "
                    "Bitte prüfen Sie Ihre Angaben."
                )
            elif cost_per_liter < 0.5:  # €0.50 per liter seems very low
                if not hasattr(self, "_warnings"):
                    self._warnings = []
                self._warnings.append(
                    f"Preis pro Liter ({cost_per_liter:.2f}€/L) erscheint niedrig. "
                    "Bitte prüfen Sie Ihre Angaben."
                )

        return cleaned_data

    def get_warnings(self):
        """Get list of validation warnings (non-blocking)."""
        return getattr(self, "_warnings", [])

    def save(self, commit=True):
        """Save the fuel receipt with employee information."""
        fuel_receipt = super().save(commit=False)

        # Set employee if not already set
        if not fuel_receipt.employee_id:
            fuel_receipt.employee = self.user

        if commit:
            fuel_receipt.save()

        return fuel_receipt
