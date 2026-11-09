from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Parent class for all tables. Alembic reads Base.metadata to autogenerate migrations."""


# Tables (tenants, endpoints, events, delivery_attempts) are added in M1 and M2.
