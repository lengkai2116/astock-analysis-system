"""创建 system_config 和 sync_log 表

Revision ID: 001_create_system_config
Revises: None
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON

# revision identifiers, used by Alembic.
revision = '001_create_system_config'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # system_config 表
    op.create_table(
        'system_config',
        sa.Column('key', sa.String(128), primary_key=True),
        sa.Column('value', JSON, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # sync_log 表
    op.create_table(
        'sync_log',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sync_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('finished_at', sa.DateTime, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('records_added', sa.Integer, default=0),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('details', JSON, nullable=True),
    )


def downgrade():
    op.drop_table('sync_log')
    op.drop_table('system_config')
