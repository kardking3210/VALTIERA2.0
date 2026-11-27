"""Track per-order partial fills in the simulated paper ledger."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_paper_partial_fills"
down_revision = "0006_paper_execution"
branch_labels = None
depends_on = None

def upgrade():
    columns={c["name"] for c in inspect(op.get_bind()).get_columns("paper_orders")}
    if "filled_quantity" not in columns:
        op.add_column("paper_orders",sa.Column("filled_quantity",sa.Float(),nullable=False,server_default="0"))
    if "average_fill_price" not in columns:
        op.add_column("paper_orders",sa.Column("average_fill_price",sa.Float(),nullable=True))

def downgrade():
    columns={c["name"] for c in inspect(op.get_bind()).get_columns("paper_orders")}
    if "average_fill_price" in columns: op.drop_column("paper_orders","average_fill_price")
    if "filled_quantity" in columns: op.drop_column("paper_orders","filled_quantity")
