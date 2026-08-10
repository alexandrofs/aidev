"""initial schema for events agent_memory and audit_logs

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tabela events
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='PENDING', nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_events_status_type', 'events', ['status', 'event_type'], unique=False)
    op.create_index('idx_events_event_id', 'events', ['event_id'], unique=True)

    # 2. Tabela agent_memory
    op.create_table(
        'agent_memory',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('story_id', sa.String(length=255), nullable=False),
        sa.Column('memory_type', sa.String(length=50), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_agent_memory_story_type', 'agent_memory', ['story_id', 'memory_type'], unique=False)

    # 3. Tabela audit_logs
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('event_id', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=False),
        sa.Column('actor', sa.String(length=255), nullable=False),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_audit_logs_event_id', 'audit_logs', ['event_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_audit_logs_event_id', table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index('idx_agent_memory_story_type', table_name='agent_memory')
    op.drop_table('agent_memory')

    op.drop_index('idx_events_event_id', table_name='events')
    op.drop_index('idx_events_status_type', table_name='events')
    op.drop_table('events')
