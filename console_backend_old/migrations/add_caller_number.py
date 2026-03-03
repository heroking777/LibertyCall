"""Add caller_number column to calls table.

This migration adds the caller_number column to the calls table.
Run this script manually if Alembic is not set up.

Usage:
    python -m console_backend.migrations.add_caller_number
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from console_backend.database import engine
from sqlalchemy import text


def upgrade():
    """Add caller_number column to calls table."""
    with engine.connect() as conn:
        # Check if column already exists
        inspector = __import__("sqlalchemy").inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("calls")]
        
        if "caller_number" in columns:
            print("caller_number column already exists. Skipping migration.")
            return
        
        # Add column
        conn.execute(text("ALTER TABLE calls ADD COLUMN caller_number VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_calls_caller_number ON calls(caller_number)"))
        conn.commit()
        print("Successfully added caller_number column to calls table.")


def downgrade():
    """Remove caller_number column from calls table."""
    with engine.connect() as conn:
        # SQLite does not support DROP COLUMN directly
        # This would require recreating the table, which is complex
        print("SQLite does not support DROP COLUMN. Manual migration required.")
        print("To remove caller_number column, you need to:")
        print("1. Create a new table without caller_number")
        print("2. Copy data from old table to new table")
        print("3. Drop old table and rename new table")


if __name__ == "__main__":
    upgrade()

