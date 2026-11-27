"""Add isolated simulated paper account and order ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0006_paper_execution"
down_revision = "0005_remove_social_research"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("cash", sa.Float(), nullable=False, server_default="100000"),
        sa.Column("positions", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_accounts_user_id", "paper_accounts", ["user_id"], unique=False)
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("asset_class", sa.String(16), nullable=False, server_default="crypto"),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("fee_bps", sa.Float(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_paper_orders_user_id", "paper_orders", ["user_id"], unique=False)

def downgrade():
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_accounts_user_id", table_name="paper_accounts")
    op.drop_table("paper_accounts")
