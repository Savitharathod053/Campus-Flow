"""add_registration_start_date_and_event_requests_schema

Revision ID: 8b2c4e6a1f3d
Revises: 76f5e6687c78
Create Date: 2026-09-22 19:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = '8b2c4e6a1f3d'
down_revision = '76f5e6687c78'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())
    dialect_name = bind.dialect.name.lower()
    is_postgres = 'postgres' in dialect_name
    is_mssql = 'mssql' in dialect_name

    # 1. EVENT_REQUESTS TABLE
    if 'event_requests' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('event_requests')}
        
        # Operational timing
        if 'registration_start_date' not in existing_cols:
            op.add_column('event_requests', sa.Column('registration_start_date', sa.DateTime(), nullable=True))
        if 'registration_deadline' not in existing_cols:
            op.add_column('event_requests', sa.Column('registration_deadline', sa.DateTime(), nullable=True))
            
        # Financial & content
        if 'registration_fee' not in existing_cols:
            op.add_column('event_requests', sa.Column('registration_fee', sa.Float(), server_default='0.0', nullable=False))
        if 'is_free' not in existing_cols:
            bool_default = sa.text('true' if is_postgres else ('1' if is_mssql else '1'))
            op.add_column('event_requests', sa.Column('is_free', sa.Boolean(), server_default=bool_default, nullable=False))
        if 'poster_image' not in existing_cols:
            op.add_column('event_requests', sa.Column('poster_image', sa.String(length=255), nullable=True))
        if 'rules' not in existing_cols:
            op.add_column('event_requests', sa.Column('rules', sa.Text(), nullable=True))
        if 'contact_info' not in existing_cols:
            op.add_column('event_requests', sa.Column('contact_info', sa.String(length=200), nullable=True))
        if 'faculty_coordinator' not in existing_cols:
            op.add_column('event_requests', sa.Column('faculty_coordinator', sa.String(length=150), nullable=True))
        if 'faculty_coordinator_contact' not in existing_cols:
            op.add_column('event_requests', sa.Column('faculty_coordinator_contact', sa.String(length=100), nullable=True))
            
        # Eligibility
        if 'allowed_departments' not in existing_cols:
            op.add_column('event_requests', sa.Column('allowed_departments', sa.String(length=255), server_default='ALL', nullable=False))
        if 'allowed_years' not in existing_cols:
            op.add_column('event_requests', sa.Column('allowed_years', sa.String(length=50), server_default='ALL', nullable=False))
        if 'allowed_sections' not in existing_cols:
            op.add_column('event_requests', sa.Column('allowed_sections', sa.String(length=50), server_default='ALL', nullable=False))
        if 'eligibility_notes' not in existing_cols:
            op.add_column('event_requests', sa.Column('eligibility_notes', sa.String(length=255), nullable=True))
            
        # Team config
        if 'registration_type' not in existing_cols:
            op.add_column('event_requests', sa.Column('registration_type', sa.String(length=20), server_default='INDIVIDUAL', nullable=False))
        if 'min_team_size' not in existing_cols:
            op.add_column('event_requests', sa.Column('min_team_size', sa.Integer(), server_default='2', nullable=False))
        if 'max_team_size' not in existing_cols:
            op.add_column('event_requests', sa.Column('max_team_size', sa.Integer(), server_default='4', nullable=False))
        if 'team_payment_type' not in existing_cols:
            op.add_column('event_requests', sa.Column('team_payment_type', sa.String(length=20), server_default='FREE', nullable=False))
        if 'require_full_team' not in existing_cols:
            bool_false = sa.text('false' if is_postgres else ('0' if is_mssql else '0'))
            op.add_column('event_requests', sa.Column('require_full_team', sa.Boolean(), server_default=bool_false, nullable=False))
            
        # Payment details
        if 'upi_id' not in existing_cols:
            op.add_column('event_requests', sa.Column('upi_id', sa.String(length=100), nullable=True))
        if 'upi_number' not in existing_cols:
            op.add_column('event_requests', sa.Column('upi_number', sa.String(length=20), nullable=True))
        if 'upi_qr_image' not in existing_cols:
            op.add_column('event_requests', sa.Column('upi_qr_image', sa.String(length=255), nullable=True))
        if 'payment_instructions' not in existing_cols:
            op.add_column('event_requests', sa.Column('payment_instructions', sa.Text(), nullable=True))
            
        # Attendance
        if 'enable_attendance' not in existing_cols:
            bool_true = sa.text('true' if is_postgres else ('1' if is_mssql else '1'))
            op.add_column('event_requests', sa.Column('enable_attendance', sa.Boolean(), server_default=bool_true, nullable=False))
        if 'min_attendance_percentage' not in existing_cols:
            op.add_column('event_requests', sa.Column('min_attendance_percentage', sa.Float(), server_default='0.0', nullable=False))
            
        # Approvals & Linkage
        if 'hod_reviewer_id' not in existing_cols:
            op.add_column('event_requests', sa.Column('hod_reviewer_id', sa.Integer(), nullable=True))
        if 'hod_approval_status' not in existing_cols:
            op.add_column('event_requests', sa.Column('hod_approval_status', sa.String(length=30), server_default='pending', nullable=False))
        if 'hod_decision_at' not in existing_cols:
            op.add_column('event_requests', sa.Column('hod_decision_at', sa.DateTime(), nullable=True))
        if 'hod_rejection_reason' not in existing_cols:
            op.add_column('event_requests', sa.Column('hod_rejection_reason', sa.Text(), nullable=True))
        if 'dean_reviewer_id' not in existing_cols:
            op.add_column('event_requests', sa.Column('dean_reviewer_id', sa.Integer(), nullable=True))
        if 'dean_approval_status' not in existing_cols:
            op.add_column('event_requests', sa.Column('dean_approval_status', sa.String(length=30), server_default='pending', nullable=False))
        if 'dean_decision_at' not in existing_cols:
            op.add_column('event_requests', sa.Column('dean_decision_at', sa.DateTime(), nullable=True))
        if 'dean_rejection_reason' not in existing_cols:
            op.add_column('event_requests', sa.Column('dean_rejection_reason', sa.Text(), nullable=True))
        if 'overall_status' not in existing_cols:
            op.add_column('event_requests', sa.Column('overall_status', sa.String(length=30), server_default='pending_hod_approval', nullable=False))
        if 'event_id' not in existing_cols:
            op.add_column('event_requests', sa.Column('event_id', sa.Integer(), nullable=True))

        # Safe backfill for registration_start_date from created_at
        try:
            bind.execute(text("UPDATE event_requests SET registration_start_date = created_at WHERE registration_start_date IS NULL"))
        except Exception:
            pass

    # 2. EVENTS TABLE
    if 'events' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('events')}
        if 'registration_start_date' not in existing_cols:
            op.add_column('events', sa.Column('registration_start_date', sa.DateTime(), nullable=True))
            
        # Safe backfill for events.registration_start_date from created_at
        try:
            bind.execute(text("UPDATE events SET registration_start_date = created_at WHERE registration_start_date IS NULL"))
        except Exception:
            pass


def downgrade():
    pass
