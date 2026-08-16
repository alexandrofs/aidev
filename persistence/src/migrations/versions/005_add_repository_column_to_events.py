"""add repository column and indexes to events table

Revision ID: 005_add_repository_column_to_events
Revises: 004_add_error_log_to_events
Create Date: 2026-08-16

Adiciona a coluna repository (VARCHAR(255), nullable) na tabela events e cria
os indices idx_events_repository e idx_events_repository_status para suporte multi-repo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_repository_to_events'
down_revision: Union[str, None] = '004_add_error_log_to_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'events',
        sa.Column('repository', sa.String(255), nullable=True)
    )
    op.create_index(
        'idx_events_repository',
        'events',
        ['repository']
    )
    op.create_index(
        'idx_events_repository_status',
        'events',
        ['repository', 'status']
    )


def downgrade() -> None:
    op.drop_index('idx_events_repository_status', table_name='events')
    op.drop_index('idx_events_repository', table_name='events')
    op.drop_column('events', 'repository')
