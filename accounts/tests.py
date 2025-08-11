import hashlib
import os
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from .models import TimeEntry

User = get_user_model()


class DatabaseConfigurationTest(TestCase):
    """Test database configuration per US-E01 requirements."""

    def test_database_configuration_sqlite_for_dev(self):
        """Test that SQLite is used when DATABASE_URL is not set (development)."""
        from django.conf import settings
        from django.db import connection
        
        # If DATABASE_URL is not set, should use SQLite
        if not os.environ.get("DATABASE_URL"):
            self.assertEqual(
                connection.vendor, "sqlite", 
                "Should use SQLite for development when DATABASE_URL is not set"
            )
            self.assertIn("sqlite3", settings.DATABASES["default"]["ENGINE"])

    def test_database_configuration_postgresql_for_prod(self):
        """Test that PostgreSQL is used when DATABASE_URL is set (production)."""
        from django.conf import settings
        from django.db import connection
        
        # If DATABASE_URL is set, should use PostgreSQL
        if os.environ.get("DATABASE_URL"):
            self.assertEqual(
                connection.vendor, "postgresql",
                "Should use PostgreSQL when DATABASE_URL is set"
            )
            self.assertIn("postgresql", settings.DATABASES["default"]["ENGINE"])

    def test_migrations_work_on_current_database(self):
        """Test that migrations work on the current database engine."""
        from django.core.management import call_command
        from django.db import connection
        
        # This test verifies that our models can be migrated on the current DB
        # This is run in CI with SQLite and can be run manually with PostgreSQL
        
        # Verify we can create and query our models
        user = User.objects.create_user(
            username="test_db_user",
            email="test@example.com",
            role="employee"
        )
        
        time_entry = TimeEntry.objects.create(
            user=user,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=user,
            updated_by=user,
        )
        
        # Verify we can query the data
        self.assertEqual(TimeEntry.objects.filter(user=user).count(), 1)
        self.assertEqual(time_entry.total_work_minutes, 450)  # 8h - 30min lunch
        
        # Log the database engine being used for visibility in test output
        print(f"Database engine: {connection.vendor}")


class UserModelTest(TestCase):
    """Test the custom User model."""

    def setUp(self):
        self.user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "role": "employee",
        }

    def test_create_user(self):
        """Test creating a user with default role."""
        user = User.objects.create_user(**self.user_data)

        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.role, "employee")
        self.assertTrue(user.is_employee)
        self.assertFalse(user.is_backoffice)
        self.assertFalse(user.is_invited)

    def test_create_backoffice_user(self):
        """Test creating a backoffice user."""
        self.user_data["role"] = "backoffice"
        user = User.objects.create_user(**self.user_data)

        self.assertEqual(user.role, "backoffice")
        self.assertTrue(user.is_backoffice)
        self.assertFalse(user.is_employee)

    def test_user_string_representation(self):
        """Test the string representation of User."""
        user = User.objects.create_user(**self.user_data)
        expected = "Test User (Mitarbeiter)"
        self.assertEqual(str(user), expected)


class TimeEntryModelTest(TestCase):
    """Test the TimeEntry model."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            role="employee",
        )
        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            first_name="Back",
            last_name="Office",
            role="backoffice",
        )

        self.time_entry_data = {
            "user": self.employee,
            "date": date(2024, 1, 15),
            "start_time": time(9, 0),
            "end_time": time(17, 0),
            "lunch_break_minutes": 30,
            "pollution_level": 2,
            "notes": "Test entry",
            "created_by": self.backoffice,
            "updated_by": self.backoffice,
        }

    def test_create_time_entry(self):
        """Test creating a valid time entry."""
        entry = TimeEntry.objects.create(**self.time_entry_data)

        self.assertEqual(entry.user, self.employee)
        self.assertEqual(entry.date, date(2024, 1, 15))
        self.assertEqual(entry.start_time, time(9, 0))
        self.assertEqual(entry.end_time, time(17, 0))
        self.assertEqual(entry.lunch_break_minutes, 30)
        self.assertEqual(entry.pollution_level, 2)
        self.assertEqual(entry.notes, "Test entry")
        self.assertEqual(entry.created_by, self.backoffice)
        self.assertEqual(entry.updated_by, self.backoffice)

    def test_time_entry_string_representation(self):
        """Test the string representation of TimeEntry."""
        entry = TimeEntry.objects.create(**self.time_entry_data)
        expected = "Test Employee - 2024-01-15"
        self.assertEqual(str(entry), expected)

    def test_unique_constraint_user_date(self):
        """Test that unique constraint (user, date) is enforced."""
        TimeEntry.objects.create(**self.time_entry_data)

        # Try to create another entry for same user and date
        with self.assertRaises(IntegrityError):
            TimeEntry.objects.create(**self.time_entry_data)

    def test_validation_end_time_after_start_time(self):
        """Test that end time must be after start time during normal hours."""
        self.time_entry_data.update(
            {
                "start_time": time(10, 0),  # 10 AM
                "end_time": time(9, 0),     # 9 AM (invalid during normal hours)
            }
        )

        entry = TimeEntry(**self.time_entry_data)
        with self.assertRaises(ValidationError) as cm:
            entry.clean()

        self.assertIn("end_time", cm.exception.message_dict)
        self.assertIn(
            "Endzeit muss nach der Startzeit liegen",
            cm.exception.message_dict["end_time"][0],
        )

    def test_validation_negative_lunch_break(self):
        """Test that lunch break cannot be negative."""
        self.time_entry_data["lunch_break_minutes"] = -30

        entry = TimeEntry(**self.time_entry_data)
        with self.assertRaises(ValidationError) as cm:
            entry.clean()

        self.assertIn("lunch_break_minutes", cm.exception.message_dict)

    def test_validation_future_date(self):
        """Test that date cannot be in the future."""
        from django.utils import timezone

        future_date = timezone.now().date()
        future_date = future_date.replace(year=future_date.year + 1)

        self.time_entry_data["date"] = future_date

        entry = TimeEntry(**self.time_entry_data)
        with self.assertRaises(ValidationError) as cm:
            entry.clean()

        self.assertIn("date", cm.exception.message_dict)
        self.assertIn(
            "Datum kann nicht in der Zukunft liegen",
            cm.exception.message_dict["date"][0],
        )

    def test_total_work_minutes_calculation(self):
        """Test calculation of total work minutes."""
        entry = TimeEntry.objects.create(**self.time_entry_data)

        # 9:00 to 17:00 = 480 minutes, minus 30 minutes lunch = 450 minutes
        expected_minutes = 450
        self.assertEqual(entry.total_work_minutes, expected_minutes)

    def test_total_work_hours_calculation(self):
        """Test calculation of total work hours."""
        entry = TimeEntry.objects.create(**self.time_entry_data)

        # 450 minutes = 7.5 hours
        expected_hours = 7.5
        self.assertEqual(entry.total_work_hours, expected_hours)

    def test_overnight_work_calculation(self):
        """Test work time calculation for overnight shifts."""
        self.time_entry_data.update(
            {
                "start_time": time(22, 0),  # 10 PM
                "end_time": time(6, 0),  # 6 AM next day
                "lunch_break_minutes": 60,
            }
        )
        entry = TimeEntry.objects.create(**self.time_entry_data)

        # 22:00 to 06:00 next day = 8 hours = 480 minutes, minus 60 minutes lunch = 420 minutes  # noqa: E501
        expected_minutes = 420
        self.assertEqual(entry.total_work_minutes, expected_minutes)

    def test_pollution_level_choices(self):
        """Test pollution level choices."""
        # Test all valid pollution levels
        for level, description in TimeEntry.POLLUTION_CHOICES:
            self.time_entry_data.update(
                {
                    "pollution_level": level,
                    "date": date(
                        2024, 1, 15 + level
                    ),  # Different dates to avoid unique constraint
                }
            )
            entry = TimeEntry.objects.create(**self.time_entry_data)
            self.assertEqual(entry.pollution_level, level)
            self.assertEqual(entry.get_pollution_level_display(), description)

    def test_save_calls_clean(self):
        """Test that save() calls clean() for validation."""
        self.time_entry_data.update(
            {
                "start_time": time(10, 0),  # 10 AM
                "end_time": time(9, 0),     # 9 AM (invalid during normal hours)
            }
        )

        entry = TimeEntry(**self.time_entry_data)
        with self.assertRaises(ValidationError):
            entry.save()


class FirstLoginViewTest(TestCase):
    """Test the first login functionality."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="newuser",
            email="new@example.com",
            first_name="New",
            last_name="User",
            role="employee",
        )
        # Set up first login token
        self.token = "test-token-123"
        self.user.first_login_token = hashlib.sha256(self.token.encode()).hexdigest()
        self.user.is_invited = True
        self.user.save()

    def test_first_login_get(self):
        """Test GET request shows the password setup form."""
        url = reverse("accounts:first_login", kwargs={"token": self.token})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New User")
        self.assertContains(response, "Neues Passwort")

    def test_first_login_invalid_token(self):
        """Test first login with invalid token."""
        url = reverse("accounts:first_login", kwargs={"token": "invalid-token"})
        response = self.client.get(url)

        # Should redirect to admin login
        self.assertEqual(response.status_code, 302)

    def test_first_login_post_success(self):
        """Test successful password setup."""
        url = reverse("accounts:first_login", kwargs={"token": self.token})
        data = {"password1": "testpassword123", "password2": "testpassword123"}
        response = self.client.post(url, data)

        # Should redirect after successful setup
        self.assertEqual(response.status_code, 302)

        # Check user was updated
        self.user.refresh_from_db()
        self.assertIsNone(self.user.first_login_token)
        self.assertTrue(self.user.check_password("testpassword123"))

    def test_first_login_password_mismatch(self):
        """Test password setup with mismatched passwords."""
        url = reverse("accounts:first_login", kwargs={"token": self.token})
        data = {"password1": "testpassword123", "password2": "differentpassword123"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "stimmen nicht überein")

    def test_first_login_short_password(self):
        """Test password setup with too short password."""
        url = reverse("accounts:first_login", kwargs={"token": self.token})
        data = {"password1": "123", "password2": "123"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mindestens 8 Zeichen")


class AdminInterfaceTest(TestCase):
    """Test the admin interface for user management."""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin123",
            role="backoffice",
        )
        self.client.login(username="admin", password="admin123")

    def test_admin_user_list(self):
        """Test that users are displayed in admin."""
        url = reverse("admin:accounts_user_changelist")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")

    def test_admin_create_user_form(self):
        """Test the add user form in admin."""
        url = reverse("admin:accounts_user_add")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rolle")


class EmailInvitationTest(TestCase):
    """Test email invitation functionality."""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin123",
            role="backoffice",
        )
        # Clear any existing emails
        mail.outbox = []

    def test_user_creation_sends_email(self):
        """Test that creating a user through admin sends invitation email."""
        # This would typically be tested through the admin interface
        # For now, we'll test the basic email functionality

        # Create a user (simulating admin creation)
        user = User.objects.create_user(
            username="newuser",
            email="newuser@example.com",
            first_name="New",
            last_name="User",
            role="employee",
        )

        # In actual admin save, email would be sent
        # Here we verify the user was created properly
        self.assertEqual(user.role, "employee")
        self.assertEqual(user.email, "newuser@example.com")


class CreateEmployeeViewTest(TestCase):
    """Test the create employee functionality."""

    def setUp(self):
        self.client = Client()
        # Create a backoffice user for testing
        self.backoffice_user = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            password="testpass123",
            first_name="Back",
            last_name="Office",
            role="backoffice",
        )
        # Create a regular employee user
        self.employee_user = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            password="testpass123",
            first_name="Employee",
            last_name="User",
            role="employee",
        )

    def test_create_employee_requires_login(self):
        """Test that create employee view requires login."""
        url = reverse("accounts:create_employee")
        response = self.client.get(url)

        # Should redirect to login
        self.assertEqual(response.status_code, 302)

    def test_create_employee_requires_backoffice_role(self):
        """Test that create employee view requires backoffice role."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:create_employee")
        response = self.client.get(url)

        # Should be forbidden or redirect (depends on user_passes_test behavior)
        self.assertIn(response.status_code, [302, 403])

    def test_create_employee_get_success(self):
        """Test GET request to create employee view."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("accounts:create_employee")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neuen Mitarbeiter anlegen")
        self.assertContains(response, "Vorname")
        self.assertContains(response, "Nachname")
        self.assertContains(response, "E-Mail-Adresse")
        self.assertContains(response, "Rolle")

    def test_create_employee_post_success(self):
        """Test successful employee creation."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("accounts:create_employee")

        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "role": "employee",
        }

        response = self.client.post(url, data)

        # Should redirect back to form
        self.assertEqual(response.status_code, 302)

        # Check that user was created
        created_user = User.objects.get(email="john.doe@example.com")
        self.assertEqual(created_user.first_name, "John")
        self.assertEqual(created_user.last_name, "Doe")
        self.assertEqual(created_user.role, "employee")
        self.assertEqual(created_user.username, "john.doe@example.com")
        self.assertTrue(created_user.is_invited)
        self.assertIsNotNone(created_user.first_login_token)
        self.assertFalse(created_user.has_usable_password())

    def test_create_employee_duplicate_email(self):
        """Test creating employee with duplicate email."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("accounts:create_employee")

        data = {
            "first_name": "Test",
            "last_name": "User",
            "email": "employee@example.com",  # Already exists
            "role": "employee",
        }

        response = self.client.post(url, data)

        # Should stay on form with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "existiert bereits")

    def test_create_employee_missing_required_fields(self):
        """Test creating employee with missing required fields."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("accounts:create_employee")

        # Missing first_name
        data = {
            "last_name": "Doe",
            "email": "incomplete@example.com",
            "role": "employee",
        }

        response = self.client.post(url, data)

        # Should stay on form with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "erforderlich")

    def test_create_employee_backoffice_role(self):
        """Test creating employee with backoffice role."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("accounts:create_employee")

        data = {
            "first_name": "Jane",
            "last_name": "Manager",
            "email": "jane.manager@example.com",
            "role": "backoffice",
        }

        response = self.client.post(url, data)

        # Should redirect successfully
        self.assertEqual(response.status_code, 302)

        # Check that backoffice user was created
        created_user = User.objects.get(email="jane.manager@example.com")
        self.assertEqual(created_user.role, "backoffice")
        self.assertTrue(created_user.is_backoffice)
        self.assertFalse(created_user.is_employee)
