"""Compatibilité vers le lanceur d'applications."""

from application_launcher import (
	find_application,
	launch_application,
	register_application,
	register_application_alias,
)

__all__ = ("find_application", "launch_application", "register_application", "register_application_alias")