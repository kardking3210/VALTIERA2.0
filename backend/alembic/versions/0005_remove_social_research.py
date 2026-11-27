"""Remove community content, reactions, polls and public researcher profiles."""
from alembic import op
from sqlalchemy import inspect

revision = "0005_remove_social_research"
down_revision = "0004_personalized_risk"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table in ("poll_votes", "post_reactions", "topic_follows", "comments", "polls", "posts"):
        if table in tables:
            op.drop_table(table)
    columns = {column["name"] for column in inspector.get_columns("users")} if "users" in tables else set()
    for column in ("research_interests", "bio"):
        if column in columns:
            with op.batch_alter_table("users") as batch:
                batch.drop_column(column)

def downgrade():
    raise RuntimeError("The removed community data cannot be restored by an automatic downgrade.")
