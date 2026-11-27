"""Persist revoked bearer sessions to make logout effective."""
from alembic import op
from sqlalchemy import inspect, Column, String, Integer, DateTime, ForeignKey

revision="0003_revoked_sessions"
down_revision="0002_profiles_community"
branch_labels=None
depends_on=None

def upgrade():
    if "revoked_sessions" not in inspect(op.get_bind()).get_table_names():
        op.create_table("revoked_sessions",Column("token_hash",String(64),primary_key=True),Column("user_id",Integer,ForeignKey("users.id"),nullable=False),Column("expires_at",DateTime(timezone=True),nullable=False),Column("revoked_at",DateTime(timezone=True),nullable=False))
        op.create_index("ix_revoked_sessions_user_id","revoked_sessions",["user_id"])
        op.create_index("ix_revoked_sessions_expires_at","revoked_sessions",["expires_at"])

def downgrade():
    if "revoked_sessions" in inspect(op.get_bind()).get_table_names(): op.drop_table("revoked_sessions")
