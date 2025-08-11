from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import TimeEntry, User


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
    Covers US-C01 (time tracking), US-C02 (lunch breaks), and US-C03 (pollution level).
    """

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

        return cleaned_data

    def get_warnings(self):
        """Get list of validation warnings (non-blocking)."""
        return getattr(self, "_warnings", [])
