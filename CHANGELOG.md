# Changelog

## Unreleased
- Fix task lifecycle management for real-time subscriptions and ensure background tasks are cancelled when a config entry unloads.
- Centralize Nest client authentication handling and reuse it across entities.
- Improve robustness of sensor and binary sensor conversions when device data is missing or malformed.
- Correct typing issues for area mappings and preset lookups to better reflect actual data structures.
- Generate stable device configuration URLs with proper path handling.
