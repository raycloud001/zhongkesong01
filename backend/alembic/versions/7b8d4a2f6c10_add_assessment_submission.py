"""add assessment workflow records"""
from alembic import op
import sqlalchemy as sa
revision="7b8d4a2f6c10"; down_revision="3f0e2c1a9b74"; branch_labels=None; depends_on=None
def upgrade():
    op.create_table("assessment_events",sa.Column("id",sa.String(),nullable=False),sa.Column("owner_id",sa.String(),nullable=False),sa.Column("session_id",sa.String(),nullable=False),sa.Column("client_event_id",sa.String(),nullable=False),sa.Column("event_type",sa.String(),nullable=False),sa.Column("metadata_json",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.ForeignKeyConstraint(["owner_id"],["users.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["session_id"],["assessment_sessions.id"],ondelete="CASCADE"),sa.PrimaryKeyConstraint("id"),sa.UniqueConstraint("owner_id","client_event_id",name="uq_assessment_event_client"))
    op.create_table("assessment_submissions",sa.Column("id",sa.String(),nullable=False),sa.Column("owner_id",sa.String(),nullable=False),sa.Column("session_id",sa.String(),nullable=False),sa.Column("idempotency_key",sa.String(),nullable=False),sa.Column("job_id",sa.String(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.ForeignKeyConstraint(["job_id"],["report_generation_jobs.id"],ondelete="RESTRICT"),sa.ForeignKeyConstraint(["owner_id"],["users.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["session_id"],["assessment_sessions.id"],ondelete="CASCADE"),sa.PrimaryKeyConstraint("id"),sa.UniqueConstraint("owner_id","session_id","idempotency_key",name="uq_assessment_submit_key"),sa.UniqueConstraint("session_id",name="uq_assessment_submit_session"))
def downgrade():
    op.drop_table("assessment_submissions"); op.drop_table("assessment_events")
