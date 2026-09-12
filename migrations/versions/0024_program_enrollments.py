"""Program-level learner enrollment."""
from alembic import op
import sqlalchemy as sa

revision = '0024_program_enrollments'
down_revision = '0023_prompt_registry'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('program_enrollments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('program_id', sa.Integer, nullable=False),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='ENROLLED'),
        sa.Column('registered_at', sa.Float, nullable=False),
        sa.Column('cancelled_at', sa.Float),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('updated_at', sa.Float, nullable=False),
        sa.Column('registration_source', sa.String(32), nullable=False, server_default='PROGRAM'),
        sa.Column('created_by', sa.Integer),
        sa.UniqueConstraint('program_id','user_id', name='uq_program_enrollment_user'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']))
    op.create_index('idx_program_enrollments_user','program_enrollments',['user_id'])
    op.create_index('idx_program_enrollments_program','program_enrollments',['program_id'])

def downgrade():
    op.drop_index('idx_program_enrollments_program', table_name='program_enrollments')
    op.drop_index('idx_program_enrollments_user', table_name='program_enrollments')
    op.drop_table('program_enrollments')
