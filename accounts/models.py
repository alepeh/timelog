from django.contrib.auth.models import AbstractUser
from django.db import models


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
