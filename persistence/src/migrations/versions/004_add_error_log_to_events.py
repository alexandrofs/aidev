"""add error_log to events table

Revision ID: 004_add_error_log_to_events
Revises: 003_agent_memory_event_id
Create Date: 2026-08-16

Adiciona a coluna error_log (TEXT, nullable) na tabela events para
armazenar informacoes de erro e rastreamento de falhas de execucao.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_error_log_to_events'
down_revision: Union[str, None] = '003_agent_memory_event_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'events',
        sa.Column('error_log', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('events', 'error_log')
