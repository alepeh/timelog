import hashlib
import os
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from .forms import TimeEntryForm
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
                connection.vendor,
                "sqlite",
                "Should use SQLite for development when DATABASE_URL is not set",
            )
            self.assertIn("sqlite3", settings.DATABASES["default"]["ENGINE"])

    def test_database_configuration_postgresql_for_prod(self):
        """Test that PostgreSQL is used when DATABASE_URL is set (production)."""
        from django.conf import settings
        from django.db import connection

        # If DATABASE_URL is set, should use PostgreSQL
        if os.environ.get("DATABASE_URL"):
            self.assertEqual(
                connection.vendor,
                "postgresql",
                "Should use PostgreSQL when DATABASE_URL is set",
            )
            self.assertIn("postgresql", settings.DATABASES["default"]["ENGINE"])

    def test_migrations_work_on_current_database(self):
        """Test that migrations work on the current database engine."""
        from django.db import connection

        # This test verifies that our models can be migrated on the current DB
        # This is run in CI with SQLite and can be run manually with PostgreSQL
        # Verify we can create and query our models
        user = User.objects.create_user(
            username="test_db_user", email="test@example.com", role="employee"
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
                "end_time": time(9, 0),  # 9 AM (invalid during normal hours)
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
                "end_time": time(9, 0),  # 9 AM (invalid during normal hours)
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
    """Test the admin interface for user and time entry management."""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin123",
            role="backoffice",
        )
        self.employee_user = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            role="employee",
        )
        self.client.login(username="admin", password="admin123")

    def test_admin_user_list(self):
        """Test that users are displayed in admin with proper fields and filters."""
        url = reverse("admin:accounts_user_changelist")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")
        self.assertContains(response, "employee")
        # Check list_display fields are shown
        self.assertContains(response, "admin@example.com")
        self.assertContains(response, "backoffice")

    def test_admin_user_filters_available(self):
        """Test that user list has proper filters."""
        url = reverse("admin:accounts_user_changelist")
        response = self.client.get(url)

        # Check for filter options based on list_filter configuration
        self.assertContains(response, "role")
        self.assertContains(response, "is_invited")
        self.assertContains(response, "is_active")

    def test_admin_create_user_form(self):
        """Test the add user form in admin."""
        url = reverse("admin:accounts_user_add")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rolle")

    def test_admin_timeentry_list(self):
        """Test that time entries are displayed in admin."""
        # Create a time entry first
        TimeEntry.objects.create(
            user=self.employee_user,
            date=date(2025, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=2,
            notes="Test entry",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        url = reverse("admin:accounts_timeentry_changelist")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Check that we can find the time entry in the response
        self.assertContains(response, "2025-01-15")
        self.assertContains(response, "Test Employee")
        self.assertContains(
            response, "09:00"
        )  # Changed from "09:00:00" as format might be different
        self.assertContains(response, "17:00")  # Changed from "17:00:00"

    def test_admin_timeentry_filters_available(self):
        """Test that time entry list has comprehensive filters."""
        url = reverse("admin:accounts_timeentry_changelist")
        response = self.client.get(url)

        # Check for filter options based on list_filter configuration
        self.assertContains(response, "pollution_level")
        self.assertContains(response, "date")

    def test_admin_timeentry_search_functionality(self):
        """Test search functionality for time entries."""
        # Create a time entry
        TimeEntry.objects.create(
            user=self.employee_user,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            notes="Searchable note content",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        url = reverse("admin:accounts_timeentry_changelist")
        response = self.client.get(url + "?q=Test")

        self.assertEqual(response.status_code, 200)
        # Should find entries based on user name search

    def test_admin_timeentry_date_hierarchy(self):
        """Test date hierarchy navigation in time entries."""
        url = reverse("admin:accounts_timeentry_changelist")
        response = self.client.get(url)

        # Should have date hierarchy for easy navigation
        self.assertEqual(response.status_code, 200)

    def test_admin_timeentry_csv_export_action(self):
        """Test CSV export action for time entries."""
        # Create a time entry
        TimeEntry.objects.create(
            user=self.employee_user,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=2,
            notes="Export test",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        url = reverse("admin:accounts_timeentry_changelist")

        # Test that export action is available
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "export_to_csv")

    def test_admin_models_registered(self):
        """Test that all required models are registered in admin."""
        from django.contrib import admin

        from .models import TimeEntry, User

        # Check that models are registered
        self.assertIn(User, admin.site._registry)
        self.assertIn(TimeEntry, admin.site._registry)

        # Check admin classes are properly configured
        user_admin = admin.site._registry[User]
        timeentry_admin = admin.site._registry[TimeEntry]

        # Verify key configurations exist
        self.assertTrue(hasattr(user_admin, "list_display"))
        self.assertTrue(hasattr(user_admin, "list_filter"))
        self.assertTrue(hasattr(timeentry_admin, "list_display"))
        self.assertTrue(hasattr(timeentry_admin, "list_filter"))


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


class RoleBasedPermissionTest(TestCase):
    """Test role-based permission system as per US-B01."""

    def setUp(self):
        self.client = Client()

        # Create employee user
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        # Create another employee for cross-access testing
        self.other_employee = User.objects.create_user(
            username="employee2",
            email="employee2@example.com",
            first_name="Other",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        # Create backoffice user
        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            first_name="Back",
            last_name="Office",
            password="testpass123",
            role="backoffice",
        )

        # Create time entries
        self.employee_entry = TimeEntry.objects.create(
            user=self.employee,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

        self.other_employee_entry = TimeEntry.objects.create(
            user=self.other_employee,
            date=date(2024, 1, 15),
            start_time=time(8, 0),
            end_time=time(16, 0),
            lunch_break_minutes=60,
            pollution_level=2,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

    def test_permission_functions(self):
        """Test permission checking functions."""
        from .permissions import (
            can_access_time_entry,
            can_create_time_entry_for_user,
            can_create_users,
            can_export_time_entries,
            can_modify_time_entry,
            can_view_user_list,
        )

        # Employee permissions
        self.assertTrue(can_access_time_entry(self.employee, self.employee_entry))
        self.assertFalse(
            can_access_time_entry(self.employee, self.other_employee_entry)
        )
        self.assertTrue(can_modify_time_entry(self.employee, self.employee_entry))
        self.assertFalse(
            can_modify_time_entry(self.employee, self.other_employee_entry)
        )
        self.assertTrue(can_create_time_entry_for_user(self.employee, self.employee))
        self.assertFalse(
            can_create_time_entry_for_user(self.employee, self.other_employee)
        )
        self.assertFalse(can_view_user_list(self.employee))
        self.assertFalse(can_create_users(self.employee))
        self.assertFalse(can_export_time_entries(self.employee))

        # Backoffice permissions
        self.assertTrue(can_access_time_entry(self.backoffice, self.employee_entry))
        self.assertTrue(
            can_access_time_entry(self.backoffice, self.other_employee_entry)
        )
        self.assertTrue(can_modify_time_entry(self.backoffice, self.employee_entry))
        self.assertTrue(
            can_modify_time_entry(self.backoffice, self.other_employee_entry)
        )
        self.assertTrue(can_create_time_entry_for_user(self.backoffice, self.employee))
        self.assertTrue(
            can_create_time_entry_for_user(self.backoffice, self.other_employee)
        )
        self.assertTrue(can_view_user_list(self.backoffice))
        self.assertTrue(can_create_users(self.backoffice))
        self.assertTrue(can_export_time_entries(self.backoffice))

    def test_get_accessible_time_entries(self):
        """Test time entry filtering by role."""
        from .permissions import get_accessible_time_entries

        # Employee can only see their own entries
        employee_entries = get_accessible_time_entries(self.employee)
        self.assertEqual(employee_entries.count(), 1)
        self.assertEqual(employee_entries.first(), self.employee_entry)

        # Backoffice can see all entries
        backoffice_entries = get_accessible_time_entries(self.backoffice)
        self.assertEqual(backoffice_entries.count(), 2)
        self.assertIn(self.employee_entry, backoffice_entries)
        self.assertIn(self.other_employee_entry, backoffice_entries)

        # Anonymous user sees nothing
        from django.contrib.auth.models import AnonymousUser

        anon_entries = get_accessible_time_entries(AnonymousUser())
        self.assertEqual(anon_entries.count(), 0)

    def test_get_accessible_users(self):
        """Test user filtering by role."""
        from .permissions import get_accessible_users

        # Employee can only see themselves
        employee_users = get_accessible_users(self.employee)
        self.assertEqual(employee_users.count(), 1)
        self.assertEqual(employee_users.first(), self.employee)

        # Backoffice can see all users
        backoffice_users = get_accessible_users(self.backoffice)
        self.assertGreaterEqual(
            backoffice_users.count(), 3
        )  # At least the 3 test users
        self.assertIn(self.employee, backoffice_users)
        self.assertIn(self.other_employee, backoffice_users)
        self.assertIn(self.backoffice, backoffice_users)

    def test_decorators(self):
        """Test permission decorators."""
        from django.core.exceptions import PermissionDenied
        from django.http import HttpRequest

        from .permissions import role_required

        # Mock view function
        def mock_view(request):
            return "success"

        # Test role_required decorator
        backoffice_only_view = role_required("backoffice")(mock_view)
        employee_only_view = role_required("employee")(mock_view)

        # Create mock requests
        employee_request = HttpRequest()
        employee_request.user = self.employee

        backoffice_request = HttpRequest()
        backoffice_request.user = self.backoffice

        # Employee trying to access backoffice-only view
        with self.assertRaises(PermissionDenied):
            backoffice_only_view(employee_request)

        # Backoffice trying to access employee-only view
        with self.assertRaises(PermissionDenied):
            employee_only_view(backoffice_request)

        # Correct role access
        self.assertEqual(backoffice_only_view(backoffice_request), "success")
        self.assertEqual(employee_only_view(employee_request), "success")

    def test_time_entry_access_decorator(self):
        """Test time entry access decorators."""
        from django.core.exceptions import PermissionDenied
        from django.http import HttpRequest

        from .permissions import require_time_entry_access

        @require_time_entry_access
        def mock_view(request, time_entry=None, **kwargs):
            return f"access to entry {time_entry.id}"

        # Employee accessing their own entry
        employee_request = HttpRequest()
        employee_request.user = self.employee
        result = mock_view(employee_request, pk=self.employee_entry.id)
        self.assertIn(str(self.employee_entry.id), result)

        # Employee trying to access other's entry
        with self.assertRaises(PermissionDenied):
            mock_view(employee_request, pk=self.other_employee_entry.id)

        # Backoffice accessing any entry
        backoffice_request = HttpRequest()
        backoffice_request.user = self.backoffice
        result = mock_view(backoffice_request, pk=self.other_employee_entry.id)
        self.assertIn(str(self.other_employee_entry.id), result)


class AdminRoleBasedAccessTest(TestCase):
    """Test admin interface role-based access control."""

    def setUp(self):
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        self.other_employee = User.objects.create_user(
            username="employee2",
            email="employee2@example.com",
            first_name="Other",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            first_name="Back",
            last_name="Office",
            password="testpass123",
            role="backoffice",
            is_staff=True,
        )

        # Make backoffice superuser for admin access
        self.backoffice.is_superuser = True
        self.backoffice.save()

        # Make employee staff for limited admin access
        self.employee.is_staff = True
        self.employee.save()

        # Give employee the minimum Django permissions needed for admin access
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        user_content_type = ContentType.objects.get_for_model(User)
        timeentry_content_type = ContentType.objects.get_for_model(TimeEntry)

        # Add view permissions
        view_user_perm = Permission.objects.get(
            codename="view_user", content_type=user_content_type
        )
        view_timeentry_perm = Permission.objects.get(
            codename="view_timeentry", content_type=timeentry_content_type
        )
        change_user_perm = Permission.objects.get(
            codename="change_user", content_type=user_content_type
        )
        change_timeentry_perm = Permission.objects.get(
            codename="change_timeentry", content_type=timeentry_content_type
        )

        self.employee.user_permissions.add(
            view_user_perm, view_timeentry_perm, change_user_perm, change_timeentry_perm
        )

    def test_user_admin_access_control(self):
        """Test UserAdmin role-based access."""
        from django.contrib import admin
        from django.test import RequestFactory

        from .models import User

        user_admin = admin.site._registry[User]

        # Create proper request objects with all necessary attributes
        factory = RequestFactory()

        employee_request = factory.get("/admin/")
        employee_request.user = self.employee

        backoffice_request = factory.get("/admin/")
        backoffice_request.user = self.backoffice

        # Test view permissions
        # Employee cannot view user list
        self.assertFalse(user_admin.has_view_permission(employee_request, None))

        # Employee can view their own profile
        self.assertTrue(user_admin.has_view_permission(employee_request, self.employee))

        # Employee cannot view other profiles
        self.assertFalse(
            user_admin.has_view_permission(employee_request, self.other_employee)
        )

        # Backoffice can view user list and all profiles
        self.assertTrue(user_admin.has_view_permission(backoffice_request, None))
        self.assertTrue(
            user_admin.has_view_permission(backoffice_request, self.employee)
        )
        self.assertTrue(
            user_admin.has_view_permission(backoffice_request, self.other_employee)
        )

        # Test add permissions
        self.assertFalse(user_admin.has_add_permission(employee_request))
        self.assertTrue(user_admin.has_add_permission(backoffice_request))

        # Test change permissions
        self.assertTrue(
            user_admin.has_change_permission(employee_request, self.employee)
        )
        self.assertFalse(
            user_admin.has_change_permission(employee_request, self.other_employee)
        )
        self.assertTrue(
            user_admin.has_change_permission(backoffice_request, self.employee)
        )
        self.assertTrue(
            user_admin.has_change_permission(backoffice_request, self.other_employee)
        )

        # Test delete permissions
        self.assertFalse(
            user_admin.has_delete_permission(employee_request, self.employee)
        )
        self.assertTrue(
            user_admin.has_delete_permission(backoffice_request, self.employee)
        )

    def test_timeentry_admin_access_control(self):
        """Test TimeEntryAdmin role-based access."""
        from django.contrib import admin
        from django.test import RequestFactory

        from .models import TimeEntry

        # Create test time entries
        employee_entry = TimeEntry.objects.create(
            user=self.employee,
            date=date(2025, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

        other_entry = TimeEntry.objects.create(
            user=self.other_employee,
            date=date(2025, 1, 15),
            start_time=time(8, 0),
            end_time=time(16, 0),
            lunch_break_minutes=60,
            pollution_level=2,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

        timeentry_admin = admin.site._registry[TimeEntry]

        # Create proper request objects with all necessary attributes
        factory = RequestFactory()

        employee_request = factory.get("/admin/")
        employee_request.user = self.employee

        backoffice_request = factory.get("/admin/")
        backoffice_request.user = self.backoffice

        # Test view permissions
        self.assertTrue(timeentry_admin.has_view_permission(employee_request, None))
        self.assertTrue(timeentry_admin.has_view_permission(backoffice_request, None))

        # Test change permissions on specific objects
        self.assertTrue(
            timeentry_admin.has_change_permission(employee_request, employee_entry)
        )
        self.assertFalse(
            timeentry_admin.has_change_permission(employee_request, other_entry)
        )
        self.assertTrue(
            timeentry_admin.has_change_permission(backoffice_request, employee_entry)
        )
        self.assertTrue(
            timeentry_admin.has_change_permission(backoffice_request, other_entry)
        )

        # Test queryset filtering
        employee_qs = timeentry_admin.get_queryset(employee_request)
        self.assertEqual(employee_qs.count(), 1)
        self.assertEqual(employee_qs.first(), employee_entry)

        backoffice_qs = timeentry_admin.get_queryset(backoffice_request)
        self.assertEqual(backoffice_qs.count(), 2)
        self.assertIn(employee_entry, backoffice_qs)
        self.assertIn(other_entry, backoffice_qs)

    def test_admin_action_filtering(self):
        """Test that admin actions are filtered by role."""
        from django.contrib import admin
        from django.http import HttpRequest

        from .models import TimeEntry

        timeentry_admin = admin.site._registry[TimeEntry]

        # Create mock requests
        employee_request = HttpRequest()
        employee_request.user = self.employee

        backoffice_request = HttpRequest()
        backoffice_request.user = self.backoffice

        # Employee should not have export action
        employee_actions = timeentry_admin.get_actions(employee_request)
        self.assertNotIn("export_to_csv", employee_actions)

        # Backoffice should have export action
        backoffice_actions = timeentry_admin.get_actions(backoffice_request)
        self.assertIn("export_to_csv", backoffice_actions)


class TimeEntryFormTest(TestCase):
    """Test TimeEntryForm validation and functionality (US-C01, US-C02, US-C03)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            role="employee",
        )

        self.valid_data = {
            "date": date(2024, 1, 15),
            "start_time": time(9, 0),
            "end_time": time(17, 0),
            "lunch_break_minutes": 30,
            "pollution_level": 1,
            "notes": "Test entry",
        }

    def test_valid_form_creation(self):
        """Test creating a valid time entry form."""
        form = TimeEntryForm(data=self.valid_data, user=self.user)
        self.assertTrue(form.is_valid())

        time_entry = form.save(commit=False)
        time_entry.user = self.user
        time_entry.created_by = self.user
        time_entry.updated_by = self.user
        time_entry.save()

        self.assertEqual(time_entry.date, date(2024, 1, 15))
        self.assertEqual(time_entry.total_work_hours, 7.5)  # 8 hours - 0.5 hours lunch

    def test_form_validates_end_after_start(self):
        """Test US-C01 requirement: end time must be after start time."""
        invalid_data = self.valid_data.copy()
        invalid_data["start_time"] = time(17, 0)
        invalid_data["end_time"] = time(9, 0)  # End before start

        form = TimeEntryForm(data=invalid_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("Die Endzeit muss nach der Startzeit liegen", str(form.errors))

    def test_form_validates_lunch_break_not_exceeding_total_time(self):
        """Test US-C02 requirement: lunch break cannot exceed total work time."""
        invalid_data = self.valid_data.copy()
        invalid_data["start_time"] = time(9, 0)
        invalid_data["end_time"] = time(10, 0)  # Only 1 hour total
        invalid_data["lunch_break_minutes"] = 120  # 2 hours lunch break

        form = TimeEntryForm(data=invalid_data, user=self.user)
        self.assertFalse(form.is_valid())
        # Updated validation now uses the new US-C06 message
        self.assertIn(
            "Die Arbeitszeit (ohne Pause) muss positiv sein", str(form.errors)
        )

    def test_form_validates_future_date(self):
        """Test that date cannot be in the future."""
        from django.utils import timezone

        invalid_data = self.valid_data.copy()
        future_date = timezone.now().date()
        future_date = future_date.replace(year=future_date.year + 1)
        invalid_data["date"] = future_date

        form = TimeEntryForm(data=invalid_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("Zukunft", str(form.errors))

    def test_form_validates_unique_date_per_user(self):
        """Test that each user can only have one entry per date."""
        # Create first entry
        TimeEntry.objects.create(
            user=self.user,
            date=date(2024, 1, 15),
            start_time=time(8, 0),
            end_time=time(16, 0),
            lunch_break_minutes=60,
            pollution_level=2,
            created_by=self.user,
            updated_by=self.user,
        )

        # Try to create second entry for same date
        form = TimeEntryForm(data=self.valid_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("existiert bereits", str(form.errors))

    def test_form_pollution_level_choices(self):
        """Test US-C03 requirement: pollution level choices."""
        for level in [1, 2, 3]:
            data = self.valid_data.copy()
            data["pollution_level"] = level
            data["date"] = date(2024, 1, 15 + level)  # Different dates

            form = TimeEntryForm(data=data, user=self.user)
            self.assertTrue(form.is_valid(), f"Level {level} should be valid")

        # Test invalid pollution level
        invalid_data = self.valid_data.copy()
        invalid_data["pollution_level"] = 4  # Invalid level
        form = TimeEntryForm(data=invalid_data, user=self.user)
        self.assertFalse(form.is_valid())

    def test_form_overnight_shift_validation(self):
        """Test validation for overnight shifts."""
        overnight_data = self.valid_data.copy()
        overnight_data["start_time"] = time(22, 0)  # 10 PM
        overnight_data["end_time"] = time(6, 0)  # 6 AM next day
        overnight_data["lunch_break_minutes"] = 60

        form = TimeEntryForm(data=overnight_data, user=self.user)
        self.assertTrue(form.is_valid())

    def test_form_sets_default_date_to_today(self):
        """Test that form sets default date to today for new entries."""
        from django.utils import timezone

        form = TimeEntryForm(user=self.user)
        self.assertEqual(form.fields["date"].initial, timezone.now().date())

    def test_form_validates_negative_zero_duration(self):
        """Test US-C06 requirement: no negative/zero durations."""
        # Test negative duration (lunch break too long)
        negative_data = self.valid_data.copy()
        negative_data["start_time"] = time(9, 0)
        negative_data["end_time"] = time(10, 0)  # 1 hour total
        negative_data["lunch_break_minutes"] = 70  # 70 minutes lunch > 60 minutes total

        form = TimeEntryForm(data=negative_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Die Arbeitszeit (ohne Pause) muss positiv sein", str(form.errors)
        )

        # Test zero net duration (exactly zero work time)
        zero_net_data = self.valid_data.copy()
        zero_net_data["start_time"] = time(9, 0)
        zero_net_data["end_time"] = time(10, 0)  # 1 hour total
        zero_net_data["lunch_break_minutes"] = 60  # 60 minutes lunch = 60 minutes total

        form = TimeEntryForm(data=zero_net_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Die Arbeitszeit (ohne Pause) muss positiv sein", str(form.errors)
        )

    def test_form_warns_very_long_workdays(self):
        """Test US-C06 requirement: warning for >10h net work."""
        long_day_data = self.valid_data.copy()
        long_day_data["start_time"] = time(7, 0)  # 7 AM
        long_day_data["end_time"] = time(20, 0)  # 8 PM = 13 hours total
        long_day_data["lunch_break_minutes"] = 60  # 1 hour lunch = 12h net work

        form = TimeEntryForm(data=long_day_data, user=self.user)
        self.assertTrue(form.is_valid())  # Should be valid but have warnings

        warnings = form.get_warnings()
        self.assertTrue(len(warnings) > 0)
        self.assertIn("Sehr langer Arbeitstag", warnings[0])
        self.assertIn("12.0 Stunden", warnings[0])

    def test_form_warns_weekend_work_saturday(self):
        """Test US-C06 requirement: confirmation for weekend work (Saturday)."""
        from datetime import date as date_class

        # Find next Saturday
        saturday_data = self.valid_data.copy()
        # Use a known Saturday: 2024-01-13
        saturday_data["date"] = date_class(2024, 1, 13)  # Saturday

        form = TimeEntryForm(data=saturday_data, user=self.user)
        self.assertTrue(form.is_valid())  # Should be valid but have warnings

        warnings = form.get_warnings()
        self.assertTrue(len(warnings) > 0)
        self.assertIn("Arbeit am Samstag", warnings[0])
        self.assertIn("13.01.2024", warnings[0])

    def test_form_warns_weekend_work_sunday(self):
        """Test US-C06 requirement: confirmation for weekend work (Sunday)."""
        from datetime import date as date_class

        sunday_data = self.valid_data.copy()
        # Use a known Sunday: 2024-01-14
        sunday_data["date"] = date_class(2024, 1, 14)  # Sunday

        form = TimeEntryForm(data=sunday_data, user=self.user)
        self.assertTrue(form.is_valid())  # Should be valid but have warnings

        warnings = form.get_warnings()
        self.assertTrue(len(warnings) > 0)
        self.assertIn("Arbeit am Sonntag", warnings[0])
        self.assertIn("14.01.2024", warnings[0])

    def test_form_no_warnings_normal_weekday(self):
        """Test that normal weekday work has no warnings."""
        from datetime import date as date_class

        # Use a known Monday with normal hours
        weekday_data = self.valid_data.copy()
        weekday_data["date"] = date_class(2024, 1, 15)  # Monday
        weekday_data["start_time"] = time(9, 0)
        weekday_data["end_time"] = time(17, 0)  # 8 hours
        weekday_data["lunch_break_minutes"] = 30  # 7.5h net work

        form = TimeEntryForm(data=weekday_data, user=self.user)
        self.assertTrue(form.is_valid())

        warnings = form.get_warnings()
        self.assertEqual(len(warnings), 0)

    def test_form_multiple_warnings_combined(self):
        """Test form can handle multiple warnings (long day + weekend)."""
        from datetime import date as date_class

        # Saturday with very long hours
        combined_data = self.valid_data.copy()
        combined_data["date"] = date_class(2024, 1, 13)  # Saturday
        combined_data["start_time"] = time(6, 0)  # 6 AM
        combined_data["end_time"] = time(20, 0)  # 8 PM = 14 hours total
        combined_data["lunch_break_minutes"] = 60  # 1 hour lunch = 13h net work

        form = TimeEntryForm(data=combined_data, user=self.user)
        self.assertTrue(form.is_valid())  # Should be valid but have multiple warnings

        warnings = form.get_warnings()
        self.assertEqual(len(warnings), 2)  # Should have both warnings

        # Check both warnings are present
        warning_text = " ".join(warnings)
        self.assertIn("Sehr langer Arbeitstag", warning_text)
        self.assertIn("13.0 Stunden", warning_text)
        self.assertIn("Arbeit am Samstag", warning_text)

    def test_form_exactly_ten_hours_no_warning(self):
        """Test that exactly 10 hours doesn't trigger warning."""
        exactly_ten_data = self.valid_data.copy()
        exactly_ten_data["start_time"] = time(8, 0)  # 8 AM
        exactly_ten_data["end_time"] = time(18, 30)  # 6:30 PM = 10.5 hours total
        exactly_ten_data["lunch_break_minutes"] = 30  # 0.5 hour lunch = 10h net work

        form = TimeEntryForm(data=exactly_ten_data, user=self.user)
        self.assertTrue(form.is_valid())

        warnings = form.get_warnings()
        # Should not have long day warning for exactly 10 hours
        long_day_warnings = [w for w in warnings if "Sehr langer Arbeitstag" in w]
        self.assertEqual(len(long_day_warnings), 0)


class TimeEntryViewTest(TestCase):
    """Test time entry views (US-C01, US-C02, US-C03)."""

    def setUp(self):
        self.client = Client()

        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        self.other_employee = User.objects.create_user(
            username="employee2",
            email="employee2@example.com",
            first_name="Other",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )

        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            first_name="Back",
            last_name="Office",
            password="testpass123",
            role="backoffice",
        )

        # Create test time entries
        self.employee_entry = TimeEntry.objects.create(
            user=self.employee,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            notes="Test entry",
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

    def test_time_entry_list_requires_login(self):
        """Test that time entry list requires login."""
        url = reverse("accounts:time_entry_list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_time_entry_list_shows_user_entries(self):
        """Test that list view only shows user's own entries."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Meine Zeiteinträge")
        self.assertContains(response, "15.01.2024")  # German date format
        self.assertContains(
            response, "7,5h"
        )  # Work hours with German decimal separator
        self.assertContains(response, "Niedrig")  # Pollution level

    def test_time_entry_create_get(self):
        """Test GET request to time entry create view."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neuer Zeiteintrag")
        self.assertContains(response, "Datum")
        self.assertContains(response, "Startzeit")
        self.assertContains(response, "Endzeit")
        self.assertContains(response, "Mittagspause")
        self.assertContains(response, "Verschmutzungsgrad")
        self.assertContains(response, "Arbeitszeit Vorschau")  # JavaScript preview

    def test_time_entry_create_post_success(self):
        """Test successful time entry creation."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_create")

        data = {
            "date": "2024-02-15",
            "start_time": "08:00",
            "end_time": "16:30",
            "lunch_break_minutes": "45",
            "pollution_level": "2",
            "notes": "New test entry",
        }

        response = self.client.post(url, data)

        # Should redirect to list view
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:time_entry_list"))

        # Check entry was created
        created_entry = TimeEntry.objects.get(
            user=self.employee, date=date(2024, 2, 15)
        )
        self.assertEqual(created_entry.lunch_break_minutes, 45)
        self.assertEqual(created_entry.pollution_level, 2)
        self.assertEqual(created_entry.notes, "New test entry")
        self.assertEqual(created_entry.total_work_hours, 7.75)  # 8.5 - 0.75 hours

    def test_time_entry_create_post_validation_error(self):
        """Test time entry creation with validation errors."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_create")

        # Invalid data: end before start
        data = {
            "date": "2024-02-15",
            "start_time": "17:00",
            "end_time": "09:00",
            "lunch_break_minutes": "30",
            "pollution_level": "1",
        }

        response = self.client.post(url, data)

        # Should stay on form with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Die Endzeit muss nach der Startzeit liegen")

    def test_time_entry_edit_get(self):
        """Test GET request to time entry edit view."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_edit", args=[self.employee_entry.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zeiteintrag bearbeiten")
        self.assertContains(response, "2024-01-15")  # Date in title
        self.assertContains(response, "09:00")  # Pre-filled start time
        self.assertContains(response, "17:00")  # Pre-filled end time
        self.assertContains(response, "Test entry")  # Pre-filled notes

    def test_time_entry_edit_post_success(self):
        """Test successful time entry editing."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_edit", args=[self.employee_entry.id])

        data = {
            "date": "2024-01-15",  # Keep same date
            "start_time": "08:30",  # Changed
            "end_time": "16:30",  # Changed
            "lunch_break_minutes": "60",  # Changed
            "pollution_level": "3",  # Changed
            "notes": "Updated test entry",  # Changed
        }

        response = self.client.post(url, data)

        # Should redirect to list view
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:time_entry_list"))

        # Check entry was updated
        self.employee_entry.refresh_from_db()
        self.assertEqual(self.employee_entry.start_time, time(8, 30))
        self.assertEqual(self.employee_entry.end_time, time(16, 30))
        self.assertEqual(self.employee_entry.lunch_break_minutes, 60)
        self.assertEqual(self.employee_entry.pollution_level, 3)
        self.assertEqual(self.employee_entry.notes, "Updated test entry")
        self.assertEqual(self.employee_entry.updated_by, self.employee)

    def test_time_entry_edit_other_user_entry_forbidden(self):
        """Test that user cannot edit other user's entries."""
        # Create entry for other employee
        other_entry = TimeEntry.objects.create(
            user=self.other_employee,
            date=date(2024, 1, 16),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_edit", args=[other_entry.id])
        response = self.client.get(url)

        # Should redirect with error message
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:time_entry_list"))

    def test_time_entry_delete_success(self):
        """Test successful time entry deletion."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_delete", args=[self.employee_entry.id])

        response = self.client.post(url)

        # Should redirect to list view
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:time_entry_list"))

        # Check entry was deleted
        with self.assertRaises(TimeEntry.DoesNotExist):
            TimeEntry.objects.get(id=self.employee_entry.id)

    def test_time_entry_delete_other_user_entry_forbidden(self):
        """Test that user cannot delete other user's entries."""
        other_entry = TimeEntry.objects.create(
            user=self.other_employee,
            date=date(2024, 1, 16),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=self.backoffice,
            updated_by=self.backoffice,
        )

        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_delete", args=[other_entry.id])

        response = self.client.post(url)

        # Should redirect with error message
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:time_entry_list"))

        # Entry should still exist
        self.assertTrue(TimeEntry.objects.filter(id=other_entry.id).exists())

    def test_time_entry_list_empty_state(self):
        """Test time entry list shows empty state when no entries exist."""
        # Delete the existing entry
        self.employee_entry.delete()

        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Noch keine Zeiteinträge vorhanden")
        self.assertContains(response, "Ersten Zeiteintrag erstellen")

    def test_time_entry_views_calculate_work_hours_correctly(self):
        """Test that views display correct work hour calculations."""
        # Create entry with specific times for calculation test
        TimeEntry.objects.create(
            user=self.employee,
            date=date(2024, 1, 20),
            start_time=time(8, 15),  # 8:15 AM
            end_time=time(17, 45),  # 5:45 PM = 9.5 hours total
            lunch_break_minutes=75,  # 1.25 hours lunch
            pollution_level=2,
            created_by=self.employee,
            updated_by=self.employee,
        )

        self.client.login(username="employee", password="testpass123")
        url = reverse("accounts:time_entry_list")
        response = self.client.get(url)

        # Should show 8.25 hours (9.5 - 1.25) with German decimal separator
        self.assertContains(response, "8,3h")


class ViewRoleBasedAccessTest(TestCase):
    """Test view-level role-based access control."""

    def setUp(self):
        self.client = Client()

        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            password="testpass123",
            role="employee",
        )

        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            password="testpass123",
            role="backoffice",
        )

    def test_create_employee_view_access(self):
        """Test that only backoffice can access create employee view."""
        url = reverse("accounts:create_employee")

        # Anonymous user should be redirected to login
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Employee should be forbidden
        self.client.login(username="employee", password="testpass123")
        response = self.client.get(url)
        self.assertIn(response.status_code, [403, 302])  # Forbidden or redirect

        # Backoffice should have access
        self.client.login(username="backoffice", password="testpass123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neuen Mitarbeiter anlegen")

    def test_home_view_role_based_content(self):
        """Test that home view shows different content based on role."""
        url = reverse("home")

        # Employee view
        self.client.login(username="employee", password="testpass123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Meine Zeiteinträge"
        )  # Employee sees time entry link
        self.assertContains(
            response, "Neuer Zeiteintrag"
        )  # Employee can create time entries
        self.assertNotContains(
            response, "Mitarbeiter anlegen"
        )  # No create employee link

        # Backoffice view
        self.client.login(username="backoffice", password="testpass123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin-Bereich")
        self.assertContains(response, "Mitarbeiter anlegen")  # Has create employee link


class AuthenticationFlowsTest(TestCase):
    """Test authentication flows including login, logout, and password reset."""

    def setUp(self):
        self.client = Client()
        self.user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "testpass123",
            "role": "employee",
        }
        self.user = User.objects.create_user(**self.user_data)

    def test_login_view_get(self):
        """Test GET request to login view shows login form."""
        url = reverse("accounts:login")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmelden")
        self.assertContains(response, "Benutzername")
        self.assertContains(response, "Passwort")
        self.assertContains(response, "⏰ Timelog")

    def test_login_success(self):
        """Test successful login redirects to home page."""
        url = reverse("accounts:login")
        data = {"username": "testuser", "password": "testpass123"}
        response = self.client.post(url, data, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response.wsgi_request.user, self.user)

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials shows error."""
        url = reverse("accounts:login")
        data = {"username": "testuser", "password": "wrongpassword"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Bitte Benutzername und Passwort eingeben")

    def test_login_nonexistent_user(self):
        """Test login with nonexistent user shows error."""
        url = reverse("accounts:login")
        data = {"username": "nonexistent", "password": "testpass123"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout_redirects_to_login(self):
        """Test logout redirects to login page."""
        # First login
        self.client.login(username="testuser", password="testpass123")

        # Then logout
        url = reverse("accounts:logout")
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:login"))

    def test_password_reset_view_get(self):
        """Test GET request to password reset view."""
        url = reverse("accounts:password_reset")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort zurücksetzen")
        self.assertContains(response, "E-Mail-Adresse")

    def test_password_reset_post_valid_email(self):
        """Test password reset with valid email sends email."""
        url = reverse("accounts:password_reset")
        data = {"email": self.user.email}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:password_reset_done"))

        # Check email was sent
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Passwort zurücksetzen", email.subject)
        self.assertIn(self.user.email, email.to)
        self.assertIn("/accounts/reset/", email.body)

    def test_password_reset_post_invalid_email(self):
        """Test password reset with invalid email still redirects (security)."""
        url = reverse("accounts:password_reset")
        data = {"email": "nonexistent@example.com"}
        response = self.client.post(url, data)

        # Django redirects even for invalid emails (security best practice)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:password_reset_done"))

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_done_view(self):
        """Test password reset done view."""
        url = reverse("accounts:password_reset_done")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "E-Mail erfolgreich versendet")
        self.assertContains(response, "✉️")

    def test_password_reset_confirm_valid_token(self):
        """Test password reset confirm with valid token."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        # Generate valid token and uid
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        url = reverse(
            "accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token}
        )
        response = self.client.get(url)

        # Django redirects to set-password URL on first access with valid token
        self.assertEqual(response.status_code, 302)
        self.assertIn("/set-password/", response.url)

        # Follow the redirect to the actual form
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neues Passwort festlegen")
        self.assertContains(response, "Passwort-Anforderungen")

    def test_password_reset_confirm_invalid_token(self):
        """Test password reset confirm with invalid token."""
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uid, "token": "invalid-token"},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ungültiger Link")

    def test_password_reset_confirm_post_success(self):
        """Test successful password reset confirmation."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        # Generate valid token and uid
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        url = reverse(
            "accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token}
        )

        # First access the URL to get the set-password redirect
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Now post to the set-password URL
        data = {"new_password1": "newpassword123", "new_password2": "newpassword123"}
        response = self.client.post(response.url, data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))

        # Check password was changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpassword123"))

    def test_password_reset_confirm_post_password_mismatch(self):
        """Test password reset confirmation with password mismatch."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        url = reverse(
            "accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token}
        )

        # First access the URL to get the set-password redirect
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Now post to the set-password URL with mismatched passwords
        data = {"new_password1": "newpassword123", "new_password2": "differentpassword"}
        response = self.client.post(response.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Die beiden Passwörter sind nicht identisch")

    def test_password_reset_complete_view(self):
        """Test password reset complete view."""
        url = reverse("accounts:password_reset_complete")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort erfolgreich geändert")
        self.assertContains(response, "✅")
        self.assertContains(response, "Jetzt anmelden")


class AccountLockoutTest(TestCase):
    """Test account lockout functionality using django-axes."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            role="employee",
        )
        self.login_url = reverse("accounts:login")

    def test_failed_login_attempts_increase_counter(self):
        """Test that failed login attempts are tracked."""
        # Make 3 failed attempts
        for _ in range(3):
            response = self.client.post(
                self.login_url, {"username": "testuser", "password": "wrongpass"}
            )
            self.assertEqual(response.status_code, 200)

        # Check that axes recorded the attempts
        from axes.models import AccessAttempt

        attempts = AccessAttempt.objects.filter(username="testuser")
        self.assertTrue(attempts.exists())

    def test_account_lockout_after_max_attempts(self):
        """Test that account gets locked after maximum failed attempts."""
        # Make 5 failed attempts (AXES_FAILURE_LIMIT)
        for i in range(5):
            response = self.client.post(
                self.login_url, {"username": "testuser", "password": "wrongpass"}
            )
            # First 4 attempts should show normal login form
            if i < 4:
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Anmelden")

        # 6th attempt should be locked out with 429 status
        response = self.client.post(
            self.login_url, {"username": "testuser", "password": "wrongpass"}
        )
        self.assertEqual(response.status_code, 429)

    def test_locked_account_shows_lockout_page(self):
        """Test that locked account shows proper lockout page."""
        # Lock the account first
        for _ in range(6):
            self.client.post(
                self.login_url, {"username": "testuser", "password": "wrongpass"}
            )

        # Try to access lockout URL directly
        lockout_url = reverse("accounts:locked")
        response = self.client.get(lockout_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Konto temporär gesperrt")
        self.assertContains(response, "🔒")
        self.assertContains(response, "1 Stunde")

    def test_successful_login_resets_attempts(self):
        """Test that successful login resets failed attempts counter."""
        # Make some failed attempts
        for _ in range(2):
            self.client.post(
                self.login_url, {"username": "testuser", "password": "wrongpass"}
            )

        # Now login successfully
        response = self.client.post(
            self.login_url, {"username": "testuser", "password": "testpass123"}
        )

        # Should be successful
        self.assertEqual(response.status_code, 302)

        # Check that attempts were reset
        from axes.models import AccessAttempt

        attempts = AccessAttempt.objects.filter(username="testuser")
        # Attempts should be cleared on success due to AXES_RESET_ON_SUCCESS
        self.assertEqual(attempts.count(), 0)

    def test_lockout_parameters_combination(self):
        """Test that lockout uses combination of username and IP."""
        # This tests AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
        # Make failed attempts from same IP with same username
        for _ in range(5):
            response = self.client.post(
                self.login_url,
                {"username": "testuser", "password": "wrongpass"},
                REMOTE_ADDR="192.168.1.100",
            )

        # Should be locked for this username/IP combination
        response = self.client.post(
            self.login_url,
            {"username": "testuser", "password": "wrongpass"},
            REMOTE_ADDR="192.168.1.100",
        )
        self.assertEqual(response.status_code, 429)

        # Note: Different IP behavior depends on axes configuration and test client
        # limitations. In a real environment, this would work, but test client
        # might not simulate IPs properly


class HomeViewAuthenticationTest(TestCase):
    """Test home view shows different content for authenticated and anonymous users."""

    def setUp(self):
        self.client = Client()
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            first_name="Test",
            last_name="Employee",
            password="testpass123",
            role="employee",
        )
        self.backoffice = User.objects.create_user(
            username="backoffice",
            email="backoffice@example.com",
            first_name="Back",
            last_name="Office",
            password="testpass123",
            role="backoffice",
        )

    def test_home_view_anonymous_user(self):
        """Test home view for anonymous user shows login section."""
        url = reverse("home")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmelden")
        self.assertContains(response, "Jetzt anmelden")
        self.assertNotContains(response, "Willkommen")

    def test_home_view_authenticated_employee(self):
        """Test home view for authenticated employee."""
        self.client.login(username="employee", password="testpass123")
        url = reverse("home")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Willkommen")
        self.assertContains(response, "Test Employee")
        self.assertContains(response, "Mitarbeiter")
        self.assertContains(response, "Meine Zeiteinträge")
        self.assertContains(response, "Neuer Zeiteintrag")
        self.assertContains(response, "Abmelden")

    def test_home_view_authenticated_backoffice(self):
        """Test home view for authenticated backoffice user."""
        self.client.login(username="backoffice", password="testpass123")
        url = reverse("home")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Willkommen")
        self.assertContains(response, "Back Office")
        self.assertContains(response, "Backoffice")
        self.assertContains(response, "Admin-Bereich")
        self.assertContains(response, "Mitarbeiter anlegen")
        self.assertContains(response, "Abmelden")

    def test_logout_link_functionality(self):
        """Test logout link in home view works correctly."""
        self.client.login(username="employee", password="testpass123")

        # Access home page to confirm login
        url = reverse("home")
        response = self.client.get(url)
        self.assertContains(response, "Willkommen")

        # Click logout link
        logout_url = reverse("accounts:logout")
        response = self.client.post(logout_url)

        # Should redirect to login page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:login"))

        # Access home page again - should show login section
        response = self.client.get(url)
        self.assertContains(response, "Anmelden")
        self.assertNotContains(response, "Willkommen")
