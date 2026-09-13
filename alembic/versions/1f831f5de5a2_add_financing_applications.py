"""add_financing_applications

Revision ID: 1f831f5de5a2
Revises: c3d4e5f6a7b8
Create Date: 2026-09-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f831f5de5a2'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'financing_document_requirements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_financing_document_requirements_id'), 'financing_document_requirements', ['id'], unique=False)

    op.create_table(
        'financing_applications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('employment_status', sa.Enum(
            'employed', 'self_employed', 'business_owner', 'unemployed', 'retired', 'student',
            name='financing_employment_status'
        ), nullable=False),
        sa.Column('employer_name', sa.String(length=255), nullable=True),
        sa.Column('job_title', sa.String(length=255), nullable=True),
        sa.Column('monthly_income', sa.Numeric(15, 2), nullable=False),
        sa.Column('employment_duration_months', sa.Integer(), nullable=True),
        sa.Column('additional_notes', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum(
            'pending_review', 'approved', 'rejected', 'revoked',
            name='financing_application_status'
        ), nullable=False, server_default='pending_review'),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('revoked_by', sa.UUID(), nullable=True),
        sa.Column('revoked_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['revoked_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_financing_applications_id'), 'financing_applications', ['id'], unique=False)
    op.create_index(op.f('ix_financing_applications_user_id'), 'financing_applications', ['user_id'], unique=False)

    op.create_table(
        'financing_application_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('application_id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('document_url', sa.Text(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('uploaded_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['financing_applications.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requirement_id'], ['financing_document_requirements.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_financing_application_documents_id'), 'financing_application_documents', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_financing_application_documents_id'), table_name='financing_application_documents')
    op.drop_table('financing_application_documents')
    op.drop_index(op.f('ix_financing_applications_user_id'), table_name='financing_applications')
    op.drop_index(op.f('ix_financing_applications_id'), table_name='financing_applications')
    op.drop_table('financing_applications')
    op.drop_index(op.f('ix_financing_document_requirements_id'), table_name='financing_document_requirements')
    op.drop_table('financing_document_requirements')
    sa.Enum(name='financing_application_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='financing_employment_status').drop(op.get_bind(), checkfirst=True)
