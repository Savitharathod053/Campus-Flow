"""add_extracted_transaction_id_and_missing_schema_columns

Revision ID: 76f5e6687c78
Revises: 
Create Date: 2026-09-13 21:54:04.769689

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '76f5e6687c78'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. PAYMENTS TABLE
    if 'payments' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('payments')}
        if 'extracted_transaction_id' not in existing_cols:
            op.add_column('payments', sa.Column('extracted_transaction_id', sa.String(length=100), nullable=True))
        if 'expected_amount' not in existing_cols:
            op.add_column('payments', sa.Column('expected_amount', sa.Float(), nullable=True))
        if 'detected_amount' not in existing_cols:
            op.add_column('payments', sa.Column('detected_amount', sa.Float(), nullable=True))
        if 'screenshot_hash' not in existing_cols:
            op.add_column('payments', sa.Column('screenshot_hash', sa.String(length=64), nullable=True))
        if 'fraud_risk' not in existing_cols:
            op.add_column('payments', sa.Column('fraud_risk', sa.String(length=20), server_default='LOW', nullable=True))
        if 'fraud_details' not in existing_cols:
            op.add_column('payments', sa.Column('fraud_details', sa.Text(), nullable=True))
        if 'ocr_extracted_data' not in existing_cols:
            op.add_column('payments', sa.Column('ocr_extracted_data', sa.Text(), nullable=True))
        if 'verification_reason' not in existing_cols:
            op.add_column('payments', sa.Column('verification_reason', sa.Text(), nullable=True))
        if 'notes' not in existing_cols:
            op.add_column('payments', sa.Column('notes', sa.Text(), nullable=True))
        if 'submitted_at' not in existing_cols:
            op.add_column('payments', sa.Column('submitted_at', sa.DateTime(), nullable=True))
        if 'verified_at' not in existing_cols:
            op.add_column('payments', sa.Column('verified_at', sa.DateTime(), nullable=True))
        if 'verified_by_id' not in existing_cols:
            op.add_column('payments', sa.Column('verified_by_id', sa.Integer(), nullable=True))
        if 'team_id' not in existing_cols:
            op.add_column('payments', sa.Column('team_id', sa.Integer(), nullable=True))
        if 'event_id' not in existing_cols:
            op.add_column('payments', sa.Column('event_id', sa.Integer(), nullable=True))
        if 'student_id' not in existing_cols:
            op.add_column('payments', sa.Column('student_id', sa.Integer(), nullable=True))
        if 'organizer_id' not in existing_cols:
            op.add_column('payments', sa.Column('organizer_id', sa.Integer(), nullable=True))

    # 2. EVENTS TABLE
    if 'events' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('events')}
        if 'registration_type' not in existing_cols:
            op.add_column('events', sa.Column('registration_type', sa.String(length=20), server_default='INDIVIDUAL', nullable=False))
        if 'min_team_size' not in existing_cols:
            op.add_column('events', sa.Column('min_team_size', sa.Integer(), server_default='2', nullable=False))
        if 'max_team_size' not in existing_cols:
            op.add_column('events', sa.Column('max_team_size', sa.Integer(), server_default='4', nullable=False))
        if 'team_payment_type' not in existing_cols:
            op.add_column('events', sa.Column('team_payment_type', sa.String(length=20), server_default='FREE', nullable=False))
        if 'require_full_team' not in existing_cols:
            op.add_column('events', sa.Column('require_full_team', sa.Boolean(), server_default=sa.text('false' if 'postgres' in bind.dialect.name.lower() else '0'), nullable=False))
        if 'upi_id' not in existing_cols:
            op.add_column('events', sa.Column('upi_id', sa.String(length=100), nullable=True))
        if 'upi_number' not in existing_cols:
            op.add_column('events', sa.Column('upi_number', sa.String(length=20), nullable=True))
        if 'upi_qr_image' not in existing_cols:
            op.add_column('events', sa.Column('upi_qr_image', sa.String(length=255), nullable=True))
        if 'payment_instructions' not in existing_cols:
            op.add_column('events', sa.Column('payment_instructions', sa.Text(), nullable=True))
        if 'enable_attendance' not in existing_cols:
            op.add_column('events', sa.Column('enable_attendance', sa.Boolean(), server_default=sa.text('true' if 'postgres' in bind.dialect.name.lower() else '1'), nullable=False))
        if 'min_attendance_percentage' not in existing_cols:
            op.add_column('events', sa.Column('min_attendance_percentage', sa.Float(), server_default='0.0', nullable=False))
        if 'department_id' not in existing_cols:
            op.add_column('events', sa.Column('department_id', sa.Integer(), nullable=True))
        if 'is_published' not in existing_cols:
            op.add_column('events', sa.Column('is_published', sa.Boolean(), server_default=sa.text('false' if 'postgres' in bind.dialect.name.lower() else '0'), nullable=False))
        if 'hod_approved' not in existing_cols:
            op.add_column('events', sa.Column('hod_approved', sa.Boolean(), server_default=sa.text('false' if 'postgres' in bind.dialect.name.lower() else '0'), nullable=False))
        if 'dean_approved' not in existing_cols:
            op.add_column('events', sa.Column('dean_approved', sa.Boolean(), server_default=sa.text('false' if 'postgres' in bind.dialect.name.lower() else '0'), nullable=False))
        if 'event_request_id' not in existing_cols:
            op.add_column('events', sa.Column('event_request_id', sa.Integer(), nullable=True))
        if 'rejection_reason' not in existing_cols:
            op.add_column('events', sa.Column('rejection_reason', sa.Text(), nullable=True))
        if 'allowed_departments' not in existing_cols:
            op.add_column('events', sa.Column('allowed_departments', sa.String(length=255), server_default='ALL', nullable=False))
        if 'allowed_years' not in existing_cols:
            op.add_column('events', sa.Column('allowed_years', sa.String(length=50), server_default='ALL', nullable=False))
        if 'allowed_sections' not in existing_cols:
            op.add_column('events', sa.Column('allowed_sections', sa.String(length=50), server_default='ALL', nullable=False))
        if 'eligibility_notes' not in existing_cols:
            op.add_column('events', sa.Column('eligibility_notes', sa.String(length=255), nullable=True))

    # 3. ORGANIZER_PROFILES TABLE
    if 'organizer_profiles' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('organizer_profiles')}
        if 'roll_number' not in existing_cols:
            op.add_column('organizer_profiles', sa.Column('roll_number', sa.String(length=50), nullable=True))
        if 'rejection_reason' not in existing_cols:
            op.add_column('organizer_profiles', sa.Column('rejection_reason', sa.String(length=255), nullable=True))
        if 'approved_by_id' not in existing_cols:
            op.add_column('organizer_profiles', sa.Column('approved_by_id', sa.Integer(), nullable=True))
        if 'approved_at' not in existing_cols:
            op.add_column('organizer_profiles', sa.Column('approved_at', sa.DateTime(), nullable=True))

    # 4. EVENT_REGISTRATIONS TABLE
    if 'event_registrations' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('event_registrations')}
        if 'team_id' not in existing_cols:
            op.add_column('event_registrations', sa.Column('team_id', sa.Integer(), nullable=True))

    # 5. CERTIFICATES TABLE
    if 'certificates' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('certificates')}
        if 'extracted_name' not in existing_cols:
            op.add_column('certificates', sa.Column('extracted_name', sa.String(length=150), nullable=True))
        if 'confidence_score' not in existing_cols:
            op.add_column('certificates', sa.Column('confidence_score', sa.Float(), server_default='0.0', nullable=True))
        if 'assigned_by_id' not in existing_cols:
            op.add_column('certificates', sa.Column('assigned_by_id', sa.Integer(), nullable=True))
        if 'extracted_text' not in existing_cols:
            op.add_column('certificates', sa.Column('extracted_text', sa.Text(), nullable=True))
        if 'file_type' not in existing_cols:
            op.add_column('certificates', sa.Column('file_type', sa.String(length=20), server_default='pdf', nullable=False))
        if 'original_filename' not in existing_cols:
            op.add_column('certificates', sa.Column('original_filename', sa.String(length=255), nullable=True))

    # 6. ATTENDANCE_RECORDS TABLE
    if 'attendance_records' in existing_tables:
        existing_cols = {c['name'] for c in insp.get_columns('attendance_records')}
        if 'session_id' not in existing_cols:
            op.add_column('attendance_records', sa.Column('session_id', sa.Integer(), nullable=True))


def downgrade():
    pass

