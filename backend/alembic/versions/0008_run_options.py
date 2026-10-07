"""Опции прогона извлечения (оверлей поверх рецепта).

Revision ID: 0008_run_options
Revises: 0007_assistant_thread
Create Date: 2026-10-05 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_run_options"
down_revision: Union[str, None] = "0007_assistant_thread"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        batch.add_column(
            sa.Column("options_json", sa.Text(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        batch.drop_column("options_json")
