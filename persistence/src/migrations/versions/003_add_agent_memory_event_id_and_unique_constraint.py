"""add event_id to agent_memory and unique constraint for idempotency

Revision ID: 003_agent_memory_event_id
Revises: 002_add_events_consumption_index
Create Date: 2026-08-12

Resolve F5 do code review da Story 2.3: INSERT sem ON CONFLICT causava duplicatas
em retries de evento. Adiciona coluna event_id nullable e constraint única
(story_id, memory_type, event_id) para garantir idempotência no UPSERT.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_agent_memory_event_id'
down_revision: Union[str, None] = '002_add_events_consumption_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adiciona coluna event_id nullable para rastrear qual evento gerou cada registro de memória
    op.add_column(
        'agent_memory',
        sa.Column('event_id', sa.String(length=255), nullable=True)
    )

    # Índice para consultas por event_id
    op.create_index(
        'idx_agent_memory_event_id',
        'agent_memory',
        ['event_id'],
        unique=False
    )

    # Unique constraint para garantir idempotência em retries:
    # Um único registro por (story_id, memory_type, event_id) quando event_id for fornecido.
    # Usamos um índice parcial único (WHERE event_id IS NOT NULL) para permitir
    # múltiplos registros sem event_id (compatibilidade retroativa com SQLite em testes).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_story_type_event
        ON agent_memory (story_id, memory_type, event_id)
        WHERE event_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_memory_story_type_event")
    op.drop_index('idx_agent_memory_event_id', table_name='agent_memory')
    op.drop_column('agent_memory', 'event_id')
