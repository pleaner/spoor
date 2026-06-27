"""The database persistence layer for the evaluate + categorise stages.

Everything that touches Postgres lives here (and in ``spoor.models``); the deterministic
core never imports any of it. Requires the optional ``db`` extra
(``pip install -e ".[db]"``): SQLModel, SQLAlchemy, Alembic, and psycopg2.
"""
