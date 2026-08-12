"""add composite index for events consumption queue

Revision ID: 002_add_events_consumption_index
Revises: 001_initial_schema
Create Date: 2026-08-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '002_add_events_consumption_index'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index supporting: WHERE status = 'PENDING' AND event_type = ANY(...) ORDER BY created_at ASC
    op.create_index('idx_events_status_type_created', 'events', ['status', 'event_type', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_events_status_type_created', table_name='events')
