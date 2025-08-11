import calendar
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from django.db.models import Q

from .models import EmployeeNonWorkingDay, PublicHoliday, TimeEntry, User


class CalendarDay:
    """Represents a single day in the calendar with all its attributes."""

    def __init__(self, date: date, user: User):
        self.date = date
        self.user = user
        self.time_entry: Optional[TimeEntry] = None
        self.is_weekend = date.weekday() >= 5  # Saturday=5, Sunday=6
        self.is_public_holiday = False
        self.public_holiday_name = ""
        self.is_employee_non_working_day = False
        self.employee_non_working_reason = ""

    @property
    def is_workday(self) -> bool:
        """Check if this is a regular workday (no weekend/holiday/non-working)."""
        return not (
            self.is_weekend
            or self.is_public_holiday
            or self.is_employee_non_working_day
        )

    @property
    def has_time_entry(self) -> bool:
        """Check if there is a time entry for this day."""
        return self.time_entry is not None

    @property
    def is_missing_entry(self) -> bool:
        """Check if this workday is missing a time entry."""
        return self.is_workday and not self.has_time_entry

    @property
    def css_classes(self) -> List[str]:
        """Get CSS classes for styling this day."""
        classes = ["calendar-day"]

        if self.is_weekend:
            classes.append("weekend")
        elif self.is_public_holiday:
            classes.append("public-holiday")
        elif self.is_employee_non_working_day:
            classes.append("employee-non-working")
        elif self.has_time_entry:
            classes.append("has-entry")
        elif self.is_workday:
            classes.append("missing-entry")

        return classes

    @property
    def display_info(self) -> str:
        """Get display information for this day."""
        if self.is_public_holiday:
            return self.public_holiday_name
        elif self.is_employee_non_working_day and self.employee_non_working_reason:
            return self.employee_non_working_reason
        elif self.has_time_entry:
            return f"{self.time_entry.total_work_hours:.1f}h"
        return ""

    @property
    def tooltip_text(self) -> str:
        """Get tooltip text for this day."""
        if self.is_public_holiday:
            return f"Feiertag: {self.public_holiday_name}"
        elif self.is_employee_non_working_day:
            reason = self.employee_non_working_reason or "Nicht-Arbeitstag"
            return f"Nicht-Arbeitstag: {reason}"
        elif self.has_time_entry:
            entry = self.time_entry
            return (
                f"Arbeitszeit: {entry.start_time.strftime('%H:%M')} - "
                f"{entry.end_time.strftime('%H:%M')} "
                f"({entry.total_work_hours:.1f}h)\n"
                f"Pause: {entry.lunch_break_minutes} Min\n"
                f"Verschmutzung: {entry.get_pollution_level_display()}"
            )
        elif self.is_weekend:
            day_name = "Samstag" if self.date.weekday() == 5 else "Sonntag"
            return f"Wochenende: {day_name}"
        else:
            return "Fehlender Zeiteintrag"


class MonthlyCalendar:
    """Manages calendar data for a specific month and user."""

    def __init__(self, year: int, month: int, user: User):
        self.year = year
        self.month = month
        self.user = user
        self.days: List[CalendarDay] = []
        self._load_calendar_data()

    @property
    def month_name(self) -> str:
        """Get German month name."""
        german_months = [
            "",
            "Januar",
            "Februar",
            "März",
            "April",
            "Mai",
            "Juni",
            "Juli",
            "August",
            "September",
            "Oktober",
            "November",
            "Dezember",
        ]
        return german_months[self.month]

    @property
    def title(self) -> str:
        """Get calendar title."""
        return f"{self.month_name} {self.year}"

    @property
    def prev_month(self) -> Tuple[int, int]:
        """Get previous month (year, month)."""
        if self.month == 1:
            return (self.year - 1, 12)
        return (self.year, self.month - 1)

    @property
    def next_month(self) -> Tuple[int, int]:
        """Get next month (year, month)."""
        if self.month == 12:
            return (self.year + 1, 1)
        return (self.year, self.month + 1)

    @property
    def stats(self) -> Dict[str, int]:
        """Get calendar statistics."""
        return {
            "total_days": len(self.days),
            "workdays": len([d for d in self.days if d.is_workday]),
            "entries_count": len([d for d in self.days if d.has_time_entry]),
            "missing_entries": len([d for d in self.days if d.is_missing_entry]),
            "weekends": len([d for d in self.days if d.is_weekend]),
            "holidays": len([d for d in self.days if d.is_public_holiday]),
            "non_working_days": len(
                [d for d in self.days if d.is_employee_non_working_day]
            ),
        }

    def _load_calendar_data(self):
        """Load all calendar data for the month."""
        # Get all days in the month
        _, last_day = calendar.monthrange(self.year, self.month)
        month_start = date(self.year, self.month, 1)
        month_end = date(self.year, self.month, last_day)

        # Create CalendarDay objects
        self.days = []
        current_date = month_start
        while current_date <= month_end:
            day = CalendarDay(current_date, self.user)
            self.days.append(day)
            current_date += timedelta(days=1)

        # Load time entries for this month
        time_entries = TimeEntry.objects.filter(
            user=self.user, date__gte=month_start, date__lte=month_end
        ).select_related("user")

        time_entries_by_date = {entry.date: entry for entry in time_entries}

        # Load public holidays
        public_holidays = PublicHoliday.get_holidays_for_year(self.year)
        public_holidays_by_date = {}

        for holiday in public_holidays:
            if holiday.is_recurring:
                # Check if this recurring holiday applies to our month
                if holiday.date.month == self.month:
                    holiday_date = date(self.year, holiday.date.month, holiday.date.day)
                    if month_start <= holiday_date <= month_end:
                        public_holidays_by_date[holiday_date] = holiday
            else:
                # One-time holiday
                if month_start <= holiday.date <= month_end:
                    public_holidays_by_date[holiday.date] = holiday

        # Load employee non-working days
        employee_non_working_days = EmployeeNonWorkingDay.objects.filter(
            employee=self.user
        ).filter(
            Q(
                # Specific dates within the month
                Q(pattern="specific", date__gte=month_start, date__lte=month_end)
            )
            | Q(
                # Weekly or monthly patterns (filter by validity period)
                Q(pattern__in=["weekly", "monthly"])
                & (
                    Q(valid_from__isnull=True) | Q(valid_from__lte=month_end)
                )  # Starts before month end
                & (
                    Q(valid_until__isnull=True) | Q(valid_until__gte=month_start)
                )  # Ends after month start
            )
        )

        # Apply data to calendar days
        for day in self.days:
            # Set time entry
            if day.date in time_entries_by_date:
                day.time_entry = time_entries_by_date[day.date]

            # Set public holiday
            if day.date in public_holidays_by_date:
                holiday = public_holidays_by_date[day.date]
                day.is_public_holiday = True
                day.public_holiday_name = holiday.name

            # Check employee non-working days
            for non_working_day in employee_non_working_days:
                if non_working_day.applies_to_date(day.date):
                    day.is_employee_non_working_day = True
                    day.employee_non_working_reason = non_working_day.reason or ""
                    break  # Only one reason per day

    def get_weeks(self) -> List[List[CalendarDay]]:
        """Get calendar days organized by weeks (starting Monday)."""
        weeks = []
        current_week = []

        # Start from the first Monday of the calendar
        first_day = self.days[0]
        days_to_start_of_week = first_day.date.weekday()

        # Add empty days from previous month if needed
        prev_month_start = first_day.date - timedelta(days=days_to_start_of_week)
        for i in range(days_to_start_of_week):
            prev_date = prev_month_start + timedelta(days=i)
            prev_day = CalendarDay(prev_date, self.user)
            # Mark as other month for styling
            setattr(prev_day, "is_other_month", True)
            current_week.append(prev_day)

        # Add all days of the month
        for day in self.days:
            current_week.append(day)

            # If Sunday (weekday 6), start new week
            if day.date.weekday() == 6:
                weeks.append(current_week)
                current_week = []

        # Add remaining days to complete the last week
        if current_week:
            last_day = self.days[-1]
            days_to_end_of_week = 6 - last_day.date.weekday()

            for i in range(1, days_to_end_of_week + 1):
                next_date = last_day.date + timedelta(days=i)
                next_day = CalendarDay(next_date, self.user)
                # Mark as other month for styling
                setattr(next_day, "is_other_month", True)
                current_week.append(next_day)

            weeks.append(current_week)

        return weeks


def get_current_month_calendar(user: User) -> MonthlyCalendar:
    """Get calendar for current month."""
    today = date.today()
    return MonthlyCalendar(today.year, today.month, user)


def get_month_calendar(year: int, month: int, user: User) -> MonthlyCalendar:
    """Get calendar for specific month."""
    return MonthlyCalendar(year, month, user)
