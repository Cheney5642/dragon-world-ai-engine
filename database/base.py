"""Shared SQLAlchemy declarative base for all Dragon World ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single metadata registry for the PostgreSQL runtime schema."""
