from typing import Iterable

from sqlalchemy import inspect, text


REQUIRED_COLUMNS = {
    "customers": [
        ("profile_picture", "VARCHAR(500)", False, None),
    ],
    "conversations": [
        ("is_starred", "BOOLEAN", False, "FALSE"),
        ("starred_at", "TIMESTAMP", True, None),
    ],
    "quick_replies": [
        ("name", "VARCHAR(100)", False, None),
        ("content", "TEXT", False, None),
        ("category", "VARCHAR(50)", False, "'general'"),
        ("is_shared", "BOOLEAN", False, "FALSE"),
        ("created_by", "UUID", True, None),
    ],
}


def _column_def_sql(table_name: str, column_name: str, column_type: str, has_default: bool, default_value: str | None) -> str:
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
    if has_default and default_value is not None:
        sql += f" DEFAULT {default_value}"
    return sql


def ensure_required_columns(connection_or_engine) -> None:
    """Add missing columns for inbox/customer features without failing on older databases."""
    inspector = inspect(connection_or_engine)
    if not inspector.get_table_names():
        return

    def execute_sql(sql: str) -> None:
        if hasattr(connection_or_engine, "execute"):
            connection_or_engine.execute(text(sql))
        else:
            with connection_or_engine.begin() as conn:
                conn.execute(text(sql))

    for table_name, columns in REQUIRED_COLUMNS.items():
        if table_name not in inspector.get_table_names():
            continue

        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type, has_default, default_value in columns:
            if column_name in existing_columns:
                continue

            sql = _column_def_sql(table_name, column_name, column_type, has_default, default_value)
            execute_sql(sql)
