from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from .calendar_utils import CalendarDay, MonthlyCalendar
from .models import EmployeeNonWorkingDay, PublicHoliday, TimeEntry

User = get_user_model()


class CalendarDayTest(TestCase):
    """Test CalendarDay functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            role="employee",
        )
        self.test_date = date(2024, 1, 15)  # Monday

    def test_calendar_day_basic_properties(self):
        """Test basic CalendarDay properties."""
        day = CalendarDay(self.test_date, self.user)

        self.assertEqual(day.date, self.test_date)
        self.assertEqual(day.user, self.user)
        self.assertIsNone(day.time_entry)
        self.assertFalse(day.is_weekend)  # Monday
        self.assertFalse(day.is_public_holiday)
        self.assertFalse(day.is_employee_non_working_day)

    def test_weekend_detection(self):
        """Test weekend detection."""
        saturday = CalendarDay(date(2024, 1, 13), self.user)  # Saturday
        sunday = CalendarDay(date(2024, 1, 14), self.user)  # Sunday
        monday = CalendarDay(date(2024, 1, 15), self.user)  # Monday

        self.assertTrue(saturday.is_weekend)
        self.assertTrue(sunday.is_weekend)
        self.assertFalse(monday.is_weekend)

    def test_workday_detection(self):
        """Test workday detection."""
        # Regular weekday
        monday = CalendarDay(date(2024, 1, 15), self.user)
        self.assertTrue(monday.is_workday)

        # Weekend
        saturday = CalendarDay(date(2024, 1, 13), self.user)
        self.assertFalse(saturday.is_workday)

        # Public holiday
        holiday = CalendarDay(date(2024, 1, 15), self.user)
        holiday.is_public_holiday = True
        holiday.public_holiday_name = "Test Holiday"
        self.assertFalse(holiday.is_workday)

        # Employee non-working day
        non_working = CalendarDay(date(2024, 1, 15), self.user)
        non_working.is_employee_non_working_day = True
        self.assertFalse(non_working.is_workday)

    def test_css_classes(self):
        """Test CSS class generation."""
        # Weekend day
        weekend_day = CalendarDay(date(2024, 1, 13), self.user)
        classes = weekend_day.css_classes
        self.assertIn("calendar-day", classes)
        self.assertIn("weekend", classes)

        # Day with time entry
        workday = CalendarDay(date(2024, 1, 15), self.user)
        workday.time_entry = TimeEntry(
            user=self.user,
            date=self.test_date,
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
        )
        classes = workday.css_classes
        self.assertIn("has-entry", classes)

        # Missing entry on workday
        missing_day = CalendarDay(date(2024, 1, 16), self.user)  # Tuesday
        classes = missing_day.css_classes
        self.assertIn("missing-entry", classes)


class MonthlyCalendarTest(TestCase):
    """Test MonthlyCalendar functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            first_name="Test",
            last_name="User",
            role="employee",
        )

    def test_calendar_basic_properties(self):
        """Test basic calendar properties."""
        calendar = MonthlyCalendar(2024, 1, self.user)

        self.assertEqual(calendar.year, 2024)
        self.assertEqual(calendar.month, 1)
        self.assertEqual(calendar.user, self.user)
        self.assertEqual(calendar.month_name, "Januar")
        self.assertEqual(calendar.title, "Januar 2024")

    def test_calendar_navigation(self):
        """Test month navigation."""
        # January 2024
        jan_calendar = MonthlyCalendar(2024, 1, self.user)
        self.assertEqual(jan_calendar.prev_month, (2023, 12))
        self.assertEqual(jan_calendar.next_month, (2024, 2))

        # December 2024
        dec_calendar = MonthlyCalendar(2024, 12, self.user)
        self.assertEqual(dec_calendar.prev_month, (2024, 11))
        self.assertEqual(dec_calendar.next_month, (2025, 1))

    def test_calendar_days_generation(self):
        """Test that all days of the month are generated."""
        calendar = MonthlyCalendar(2024, 1, self.user)  # January has 31 days

        self.assertEqual(len(calendar.days), 31)

        # Check first and last day
        self.assertEqual(calendar.days[0].date, date(2024, 1, 1))
        self.assertEqual(calendar.days[-1].date, date(2024, 1, 31))

    def test_calendar_stats_empty_month(self):
        """Test calendar statistics for empty month."""
        calendar = MonthlyCalendar(2024, 1, self.user)
        stats = calendar.stats

        self.assertEqual(stats["total_days"], 31)
        self.assertEqual(stats["entries_count"], 0)
        self.assertEqual(stats["weekends"], 8)  # January 2024 has 8 weekend days
        self.assertEqual(stats["holidays"], 0)
        self.assertEqual(stats["non_working_days"], 0)

    def test_calendar_with_time_entries(self):
        """Test calendar with some time entries."""
        # Create a time entry
        TimeEntry.objects.create(
            user=self.user,
            date=date(2024, 1, 15),
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_break_minutes=30,
            pollution_level=1,
            created_by=self.user,
            updated_by=self.user,
        )

        calendar = MonthlyCalendar(2024, 1, self.user)
        stats = calendar.stats

        self.assertEqual(stats["entries_count"], 1)

        # Find the day with the entry
        entry_day = None
        for day in calendar.days:
            if day.date == date(2024, 1, 15):
                entry_day = day
                break

        self.assertIsNotNone(entry_day)
        self.assertTrue(entry_day.has_time_entry)
        self.assertIn("has-entry", entry_day.css_classes)

    def test_calendar_with_public_holiday(self):
        """Test calendar with public holidays."""
        # Create a public holiday
        PublicHoliday.objects.create(
            name="New Year",
            date=date(2024, 1, 1),
            is_recurring=True,
            description="New Year's Day",
        )

        calendar = MonthlyCalendar(2024, 1, self.user)
        stats = calendar.stats

        self.assertEqual(stats["holidays"], 1)

        # Check the holiday day
        holiday_day = calendar.days[0]  # First day of month
        self.assertTrue(holiday_day.is_public_holiday)
        self.assertEqual(holiday_day.public_holiday_name, "New Year")

    def test_calendar_with_employee_non_working_day(self):
        """Test calendar with employee non-working days."""
        # Create employee non-working day
        EmployeeNonWorkingDay.objects.create(
            employee=self.user,
            pattern="specific",
            date=date(2024, 1, 10),
            reason="Personal day",
        )

        calendar = MonthlyCalendar(2024, 1, self.user)
        stats = calendar.stats

        self.assertEqual(stats["non_working_days"], 1)

        # Find the non-working day
        non_working_day = None
        for day in calendar.days:
            if day.date == date(2024, 1, 10):
                non_working_day = day
                break

        self.assertIsNotNone(non_working_day)
        self.assertTrue(non_working_day.is_employee_non_working_day)
        self.assertEqual(non_working_day.employee_non_working_reason, "Personal day")

    def test_weeks_organization(self):
        """Test that calendar organizes days into weeks correctly."""
        calendar = MonthlyCalendar(2024, 1, self.user)
        weeks = calendar.get_weeks()

        # Should have some weeks (4-6 depending on month)
        self.assertTrue(4 <= len(weeks) <= 6)

        # Each week should have 7 days
        for week in weeks:
            self.assertEqual(len(week), 7)


class PublicHolidayTest(TestCase):
    """Test PublicHoliday model functionality."""

    def test_recurring_holiday_applies_to_date(self):
        """Test recurring holiday date matching."""
        holiday = PublicHoliday.objects.create(
            name="Christmas",
            date=date(2023, 12, 25),  # Original year
            is_recurring=True,
        )

        # Should apply to same date in different years
        self.assertTrue(holiday.applies_to_date(date(2024, 12, 25)))
        self.assertTrue(holiday.applies_to_date(date(2025, 12, 25)))

        # Should not apply to different dates
        self.assertFalse(holiday.applies_to_date(date(2024, 12, 24)))
        self.assertFalse(holiday.applies_to_date(date(2024, 11, 25)))

    def test_non_recurring_holiday_applies_to_date(self):
        """Test non-recurring holiday date matching."""
        holiday = PublicHoliday.objects.create(
            name="Special Event", date=date(2024, 6, 15), is_recurring=False
        )

        # Should only apply to exact date
        self.assertTrue(holiday.applies_to_date(date(2024, 6, 15)))

        # Should not apply to same date in different years
        self.assertFalse(holiday.applies_to_date(date(2023, 6, 15)))
        self.assertFalse(holiday.applies_to_date(date(2025, 6, 15)))


class EmployeeNonWorkingDayTest(TestCase):
    """Test EmployeeNonWorkingDay model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", role="employee"
        )

    def test_specific_date_pattern(self):
        """Test specific date pattern."""
        non_working_day = EmployeeNonWorkingDay.objects.create(
            employee=self.user,
            pattern="specific",
            date=date(2024, 5, 15),
            reason="Vacation",
        )

        self.assertTrue(non_working_day.applies_to_date(date(2024, 5, 15)))
        self.assertFalse(non_working_day.applies_to_date(date(2024, 5, 16)))

    def test_weekly_pattern(self):
        """Test weekly recurring pattern."""
        # Every Friday off
        non_working_day = EmployeeNonWorkingDay.objects.create(
            employee=self.user,
            pattern="weekly",
            weekday=4,  # Friday
            reason="Part-time",
        )

        # Test various Fridays
        self.assertTrue(non_working_day.applies_to_date(date(2024, 1, 5)))  # Friday
        self.assertTrue(non_working_day.applies_to_date(date(2024, 1, 12)))  # Friday

        # Test non-Fridays
        self.assertFalse(non_working_day.applies_to_date(date(2024, 1, 4)))  # Thursday
        self.assertFalse(non_working_day.applies_to_date(date(2024, 1, 6)))  # Saturday

    def test_monthly_pattern(self):
        """Test monthly recurring pattern."""
        # 15th of every month off
        non_working_day = EmployeeNonWorkingDay.objects.create(
            employee=self.user,
            pattern="monthly",
            day_of_month=15,
            reason="Medical appointment",
        )

        self.assertTrue(non_working_day.applies_to_date(date(2024, 1, 15)))
        self.assertTrue(non_working_day.applies_to_date(date(2024, 2, 15)))
        self.assertTrue(non_working_day.applies_to_date(date(2024, 12, 15)))

        self.assertFalse(non_working_day.applies_to_date(date(2024, 1, 14)))
        self.assertFalse(non_working_day.applies_to_date(date(2024, 1, 16)))

    def test_validity_period(self):
        """Test validity period constraints."""
        non_working_day = EmployeeNonWorkingDay.objects.create(
            employee=self.user,
            pattern="specific",
            date=date(2024, 6, 15),
            valid_from=date(2024, 6, 1),
            valid_until=date(2024, 6, 30),
            reason="Temporary leave",
        )

        # Within validity period
        self.assertTrue(non_working_day.applies_to_date(date(2024, 6, 15)))

        # Outside validity period (same date but different year)
        non_working_day.pattern = "weekly"
        non_working_day.weekday = date(2024, 6, 15).weekday()
        non_working_day.date = None
        non_working_day.save()

        # Test dates before and after validity period
        self.assertFalse(non_working_day.applies_to_date(date(2024, 5, 15)))  # Before
        self.assertFalse(non_working_day.applies_to_date(date(2024, 7, 15)))  # After
