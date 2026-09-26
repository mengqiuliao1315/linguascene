"""当前模型基线：建齐表，并给旧库补 token_version 等缺失列。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-26
"""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.schema_sync import apply_schema

    apply_schema(op.get_bind())


def downgrade() -> None:
    pass
