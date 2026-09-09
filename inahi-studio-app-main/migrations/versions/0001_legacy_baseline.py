"""Adopt the complete legacy schema, or initialize an empty target."""
from alembic import op, context
from persistence.models import legacy_metadata

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = depends_on = None

def upgrade():
    legacy_metadata.create_all(op.get_bind(), checkfirst=not context.is_offline_mode())

def downgrade():
    # Removing the baseline would delete customer data. Restore a verified backup instead.
    raise ValueError("Baseline conservada: no se permite DROP automático; restaurar una copia verificada")
