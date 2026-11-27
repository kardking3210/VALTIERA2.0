"""Add personalized risk profile and allocation controls."""
from alembic import op
from sqlalchemy import inspect, Column, String, Float, Integer
from sqlalchemy.types import JSON

revision="0004_personalized_risk"
down_revision="0003_revoked_sessions"
branch_labels=None
depends_on=None

def upgrade():
    cols={c["name"] for c in inspect(op.get_bind()).get_columns("risk_settings")}
    additions=[("risk_profile",String(20),"'moderate'"),("max_leverage_pct",Float(),"100"),("asset_class_limits",JSON(),"'{}'"),("volatility_tolerance",String(20),"'moderate'"),("liquidity_floor_usd",Float(),"0"),("investment_horizon_months",Integer(),"12")]
    for name,type_,default in additions:
        if name not in cols: op.add_column("risk_settings",Column(name,type_,nullable=False,server_default=default))

def downgrade():
    cols={c["name"] for c in inspect(op.get_bind()).get_columns("risk_settings")}
    for name in ("investment_horizon_months","liquidity_floor_usd","volatility_tolerance","asset_class_limits","max_leverage_pct","risk_profile"):
        if name in cols: op.drop_column("risk_settings",name)
