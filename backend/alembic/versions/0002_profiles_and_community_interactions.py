"""Legacy revision retained to preserve the installed migration chain.

The social research network was removed from the product before this schema
was released. New installations do not create community tables or profiles.
"""
revision = "0002_profiles_community"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
