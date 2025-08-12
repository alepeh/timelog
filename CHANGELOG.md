# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **US-C08: Vehicle Usage and Mileage Tracking** - Complete vehicle tracking system for time entries
  - Vehicle and VehicleUsage models with comprehensive validation
  - Enhanced TimeEntryForm with vehicle selection and mileage input
  - Real-time JavaScript for distance calculation and field toggling
  - Vehicle information display in time entry list and calendar views
  - Advanced filtering by vehicle type and date ranges
  - Vehicle usage statistics dashboard with kilometers tracking
  - Mobile-responsive design for vehicle components
  - Admin interface with role-based permissions for vehicle management
  - Comprehensive test coverage (157 tests, 91% coverage)

### Changed
- Enhanced time entry list view with vehicle usage data and filtering
- Updated calendar view to display vehicle information in tooltips and day details
- Improved mobile responsiveness across all vehicle-related UI components

### Technical
- Added Vehicle and VehicleUsage models with proper database constraints
- Implemented query optimization with select_related and prefetch_related
- Added German localization for all vehicle-related UI elements
- Enhanced form validation with business rule enforcement

---

## Previous Releases

### [Completed Features]
- **US-E03**: Django Admin & Superuser Setup
- **US-E01**: Database choice enforcement (PostgreSQL prod, SQLite dev)
- **US-C01**: Basic time tracking functionality
- **US-C02**: Lunch break tracking
- **US-C03**: Pollution level tracking
- **US-C06**: Time entry validation and plausibility checks
- **US-C07**: Monthly calendar overview