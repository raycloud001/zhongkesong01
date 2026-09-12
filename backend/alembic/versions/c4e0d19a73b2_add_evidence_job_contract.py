"""add versioned evidence job contract payload

Revision ID: c4e0d19a73b2
Revises: 7b8d4a2f6c10
"""
from alembic import op
import sqlalchemy as sa


revision = "c4e0d19a73b2"
down_revision = "7b8d4a2f6c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_matches") as batch_op:
        batch_op.add_column(sa.Column("contract_version", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("structured_payload", sa.JSON(), nullable=True))
        for column_name, column_type in (
            ("job_template_version_id", sa.String()),
            ("match_status", sa.String()),
            ("evidence_sufficiency", sa.String()),
            ("current_basis", sa.Text()),
            ("potential_basis", sa.Text()),
            ("tasks", sa.JSON()),
            ("gaps", sa.JSON()),
            ("risks", sa.JSON()),
            ("validation_task", sa.JSON()),
            ("industry_context", sa.JSON()),
        ):
            batch_op.alter_column(column_name, existing_type=column_type, nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("job_matches") as batch_op:
        for column_name, column_type in (
            ("job_template_version_id", sa.String()),
            ("match_status", sa.String()),
            ("evidence_sufficiency", sa.String()),
            ("current_basis", sa.Text()),
            ("potential_basis", sa.Text()),
            ("tasks", sa.JSON()),
            ("gaps", sa.JSON()),
            ("risks", sa.JSON()),
            ("validation_task", sa.JSON()),
            ("industry_context", sa.JSON()),
        ):
            batch_op.alter_column(column_name, existing_type=column_type, nullable=False)
        batch_op.drop_column("structured_payload")
        batch_op.drop_column("contract_version")
