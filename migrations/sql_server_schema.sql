-- ==============================================================================
-- Campus Flow - Safe Idempotent Microsoft SQL Server (SSMS) Schema Script
-- ==============================================================================
-- This script safely checks whether tables, columns, constraints, and indexes
-- exist before creating them. It NEVER drops tables or alters/deletes existing data.
-- Run in SQL Server Management Studio (SSMS) against your database (e.g. fastfest).
-- ==============================================================================

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

-- 1. USERS TABLE
IF OBJECT_ID(N'[dbo].[users]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[users] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [email] NVARCHAR(120) NOT NULL,
        [password_hash] NVARCHAR(255) NOT NULL,
        [name] NVARCHAR(100) NOT NULL,
        [phone] NVARCHAR(20) NULL,
        [role] NVARCHAR(20) NOT NULL DEFAULT 'STUDENT',
        [is_active] BIT NOT NULL DEFAULT 1,
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_users_email] UNIQUE ([email])
    );
    CREATE NONCLUSTERED INDEX [IX_users_email] ON [dbo].[users]([email]);
    PRINT '[+] Table [dbo].[users] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[users] already exists. Preserved.';
END
GO

-- 2. STUDENT PROFILES
IF OBJECT_ID(N'[dbo].[student_profiles]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[student_profiles] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [user_id] INT NOT NULL,
        [roll_number] NVARCHAR(50) NOT NULL,
        [department] NVARCHAR(100) NOT NULL,
        [year] INT NOT NULL,
        [section] NVARCHAR(10) NOT NULL,
        [college_id_card] NVARCHAR(255) NULL,
        CONSTRAINT [UQ_student_profiles_user_id] UNIQUE ([user_id]),
        CONSTRAINT [UQ_student_profiles_roll_number] UNIQUE ([roll_number]),
        CONSTRAINT [FK_student_profiles_user] FOREIGN KEY ([user_id]) 
            REFERENCES [dbo].[users]([id]) ON DELETE CASCADE
    );
    CREATE NONCLUSTERED INDEX [IX_student_profiles_roll_number] ON [dbo].[student_profiles]([roll_number]);
    PRINT '[+] Table [dbo].[student_profiles] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[student_profiles] already exists. Preserved.';
END
GO

-- 3. ORGANIZER PROFILES
IF OBJECT_ID(N'[dbo].[organizer_profiles]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[organizer_profiles] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [user_id] INT NOT NULL,
        [organization_name] NVARCHAR(150) NOT NULL,
        [department] NVARCHAR(100) NOT NULL,
        [designation] NVARCHAR(100) NULL,
        [is_verified] BIT NOT NULL DEFAULT 0,
        [status] NVARCHAR(20) NOT NULL DEFAULT 'PENDING',
        [rejection_reason] NVARCHAR(255) NULL,
        [approved_by_id] INT NULL,
        [approved_at] DATETIME NULL,
        CONSTRAINT [UQ_organizer_profiles_user_id] UNIQUE ([user_id]),
        CONSTRAINT [FK_organizer_profiles_user] FOREIGN KEY ([user_id]) 
            REFERENCES [dbo].[users]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_organizer_profiles_approved_by] FOREIGN KEY ([approved_by_id]) 
            REFERENCES [dbo].[users]([id])
    );
    PRINT '[+] Table [dbo].[organizer_profiles] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[organizer_profiles] already exists. Preserved.';
END
GO

-- 4. FACULTY PROFILES
IF OBJECT_ID(N'[dbo].[faculty_profiles]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[faculty_profiles] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [user_id] INT NOT NULL,
        [employee_id] NVARCHAR(50) NOT NULL,
        [department] NVARCHAR(100) NOT NULL,
        [designation] NVARCHAR(100) NOT NULL,
        CONSTRAINT [UQ_faculty_profiles_user_id] UNIQUE ([user_id]),
        CONSTRAINT [UQ_faculty_profiles_employee_id] UNIQUE ([employee_id]),
        CONSTRAINT [FK_faculty_profiles_user] FOREIGN KEY ([user_id]) 
            REFERENCES [dbo].[users]([id]) ON DELETE CASCADE
    );
    PRINT '[+] Table [dbo].[faculty_profiles] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[faculty_profiles] already exists. Preserved.';
END
GO

-- 5. EVENTS TABLE
IF OBJECT_ID(N'[dbo].[events]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[events] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [title] NVARCHAR(150) NOT NULL,
        [slug] NVARCHAR(200) NOT NULL,
        [organizer_id] INT NOT NULL,
        [event_type] NVARCHAR(50) NOT NULL,
        [department] NVARCHAR(100) NOT NULL,
        [faculty_coordinator] NVARCHAR(100) NOT NULL,
        [faculty_coordinator_contact] NVARCHAR(100) NULL,
        [contact_info] NVARCHAR(100) NULL,
        [allowed_departments] NVARCHAR(255) NOT NULL DEFAULT 'ALL',
        [allowed_years] NVARCHAR(50) NOT NULL DEFAULT 'ALL',
        [allowed_sections] NVARCHAR(50) NOT NULL DEFAULT 'ALL',
        [eligibility_notes] NVARCHAR(500) NULL,
        [registration_type] NVARCHAR(20) NOT NULL DEFAULT 'INDIVIDUAL',
        [min_team_size] INT NOT NULL DEFAULT 2,
        [max_team_size] INT NOT NULL DEFAULT 4,
        [team_payment_type] NVARCHAR(20) NOT NULL DEFAULT 'FREE',
        [require_full_team] BIT NOT NULL DEFAULT 0,
        [description] NVARCHAR(MAX) NOT NULL,
        [rules] NVARCHAR(MAX) NULL,
        [poster_image] NVARCHAR(255) NULL,
        [venue] NVARCHAR(150) NOT NULL,
        [registration_start_date] DATETIME NULL,
        [start_time] DATETIME NOT NULL,
        [end_time] DATETIME NOT NULL,
        [registration_deadline] DATETIME NOT NULL,
        [max_participants] INT NOT NULL DEFAULT 100,
        [registration_fee] FLOAT NOT NULL DEFAULT 0.0,
        [is_free] BIT NOT NULL DEFAULT 1,
        [upi_qr_image] NVARCHAR(255) NULL,
        [upi_id] NVARCHAR(100) NULL,
        [upi_number] NVARCHAR(20) NULL,
        [account_holder_name] NVARCHAR(100) NULL,
        [enable_attendance] BIT NOT NULL DEFAULT 1,
        [min_attendance_percentage] FLOAT NOT NULL DEFAULT 0.0,
        [status] NVARCHAR(25) NOT NULL DEFAULT 'DRAFT',
        [rejection_reason] NVARCHAR(255) NULL,
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_events_slug] UNIQUE ([slug]),
        CONSTRAINT [FK_events_organizer] FOREIGN KEY ([organizer_id]) 
            REFERENCES [dbo].[users]([id]) ON DELETE CASCADE
    );
    CREATE NONCLUSTERED INDEX [IX_events_slug] ON [dbo].[events]([slug]);
    CREATE NONCLUSTERED INDEX [IX_events_status] ON [dbo].[events]([status]);
    PRINT '[+] Table [dbo].[events] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[events] already exists. Preserved.';
END
GO

-- 6. CUSTOM REGISTRATION FIELDS
IF OBJECT_ID(N'[dbo].[custom_registration_fields]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[custom_registration_fields] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [field_label] NVARCHAR(100) NOT NULL,
        [field_name] NVARCHAR(50) NOT NULL,
        [field_type] NVARCHAR(20) NOT NULL DEFAULT 'text',
        [is_required] BIT NOT NULL DEFAULT 0,
        [placeholder] NVARCHAR(150) NULL,
        [options] NVARCHAR(MAX) NULL,
        [display_order] INT NOT NULL DEFAULT 0,
        CONSTRAINT [FK_custom_registration_fields_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]) ON DELETE CASCADE
    );
    PRINT '[+] Table [dbo].[custom_registration_fields] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[custom_registration_fields] already exists. Preserved.';
END
GO

-- 7. TEAMS TABLE
IF OBJECT_ID(N'[dbo].[teams]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[teams] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [team_name] NVARCHAR(100) NOT NULL,
        [team_lead_id] INT NOT NULL,
        [status] NVARCHAR(30) NOT NULL DEFAULT 'PENDING',
        [payment_status] NVARCHAR(30) NOT NULL DEFAULT 'NOT_REQUIRED',
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [FK_teams_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]),
        CONSTRAINT [FK_teams_lead] FOREIGN KEY ([team_lead_id]) 
            REFERENCES [dbo].[users]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_teams_status] ON [dbo].[teams]([status]);
    PRINT '[+] Table [dbo].[teams] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[teams] already exists. Preserved.';
END
GO

-- 8. TEAM MEMBERS
IF OBJECT_ID(N'[dbo].[team_members]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[team_members] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [team_id] INT NOT NULL,
        [student_id] INT NOT NULL,
        [role] NVARCHAR(20) NOT NULL DEFAULT 'MEMBER',
        [status] NVARCHAR(20) NOT NULL DEFAULT 'PENDING',
        [joined_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_team_student_member] UNIQUE ([team_id], [student_id]),
        CONSTRAINT [FK_team_members_team] FOREIGN KEY ([team_id]) 
            REFERENCES [dbo].[teams]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_team_members_student] FOREIGN KEY ([student_id]) 
            REFERENCES [dbo].[users]([id])
    );
    PRINT '[+] Table [dbo].[team_members] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[team_members] already exists. Preserved.';
END
GO

-- 9. TEAM INVITATIONS
IF OBJECT_ID(N'[dbo].[team_invitations]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[team_invitations] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [team_id] INT NOT NULL,
        [event_id] INT NOT NULL,
        [invited_email] NVARCHAR(150) NOT NULL,
        [invited_student_id] INT NULL,
        [token] NVARCHAR(100) NOT NULL,
        [status] NVARCHAR(20) NOT NULL DEFAULT 'PENDING',
        [expires_at] DATETIME NOT NULL,
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [responded_at] DATETIME NULL,
        CONSTRAINT [UQ_team_invitations_token] UNIQUE ([token]),
        CONSTRAINT [FK_team_invitations_team] FOREIGN KEY ([team_id]) 
            REFERENCES [dbo].[teams]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_team_invitations_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]),
        CONSTRAINT [FK_team_invitations_student] FOREIGN KEY ([invited_student_id]) 
            REFERENCES [dbo].[users]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_team_invitations_email] ON [dbo].[team_invitations]([invited_email]);
    CREATE NONCLUSTERED INDEX [IX_team_invitations_token] ON [dbo].[team_invitations]([token]);
    PRINT '[+] Table [dbo].[team_invitations] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[team_invitations] already exists. Preserved.';
END
GO

-- 10. EVENT REGISTRATIONS
IF OBJECT_ID(N'[dbo].[event_registrations]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[event_registrations] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [student_id] INT NOT NULL,
        [team_id] INT NULL,
        [registration_code] NVARCHAR(30) NOT NULL,
        [qr_code_image] NVARCHAR(255) NULL,
        [status] NVARCHAR(20) NOT NULL DEFAULT 'CONFIRMED',
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_event_registrations_code] UNIQUE ([registration_code]),
        CONSTRAINT [UQ_event_student_reg] UNIQUE ([event_id], [student_id]),
        CONSTRAINT [FK_event_registrations_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_event_registrations_student] FOREIGN KEY ([student_id]) 
            REFERENCES [dbo].[users]([id]),
        CONSTRAINT [FK_event_registrations_team] FOREIGN KEY ([team_id]) 
            REFERENCES [dbo].[teams]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_event_registrations_code] ON [dbo].[event_registrations]([registration_code]);
    PRINT '[+] Table [dbo].[event_registrations] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[event_registrations] already exists. Preserved.';
END
GO

-- 11. CUSTOM FIELD RESPONSES
IF OBJECT_ID(N'[dbo].[custom_field_responses]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[custom_field_responses] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [registration_id] INT NOT NULL,
        [field_id] INT NOT NULL,
        [field_value] NVARCHAR(MAX) NULL,
        CONSTRAINT [FK_custom_field_responses_registration] FOREIGN KEY ([registration_id]) 
            REFERENCES [dbo].[event_registrations]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_custom_field_responses_field] FOREIGN KEY ([field_id]) 
            REFERENCES [dbo].[custom_registration_fields]([id])
    );
    PRINT '[+] Table [dbo].[custom_field_responses] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[custom_field_responses] already exists. Preserved.';
END
GO

-- 12. PAYMENTS TABLE (Configured without cascade cycles for SQL Server)
IF OBJECT_ID(N'[dbo].[payments]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[payments] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [registration_id] INT NULL,
        [team_id] INT NULL,
        [event_id] INT NULL,
        [student_id] INT NULL,
        [organizer_id] INT NULL,
        [amount] FLOAT NOT NULL,
        [currency] NVARCHAR(10) NOT NULL DEFAULT 'INR',
        [expected_amount] FLOAT NULL,
        [detected_amount] FLOAT NULL,
        [transaction_id] NVARCHAR(100) NULL,
        [payment_method] NVARCHAR(50) NULL,
        [payment_screenshot] NVARCHAR(255) NULL,
        [screenshot_hash] NVARCHAR(64) NULL,
        [status] NVARCHAR(20) NOT NULL DEFAULT 'PENDING',
        [fraud_risk] NVARCHAR(20) NULL DEFAULT 'LOW',
        [fraud_details] NVARCHAR(MAX) NULL,
        [ocr_extracted_data] NVARCHAR(MAX) NULL,
        [verification_reason] NVARCHAR(MAX) NULL,
        [notes] NVARCHAR(MAX) NULL,
        [submitted_at] DATETIME NULL DEFAULT GETUTCDATE(),
        [verified_at] DATETIME NULL,
        [verified_by_id] INT NULL,
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_payments_registration_id] UNIQUE ([registration_id]),
        CONSTRAINT [FK_payments_registration] FOREIGN KEY ([registration_id]) 
            REFERENCES [dbo].[event_registrations]([id]),
        CONSTRAINT [FK_payments_team] FOREIGN KEY ([team_id]) 
            REFERENCES [dbo].[teams]([id]),
        CONSTRAINT [FK_payments_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]),
        CONSTRAINT [FK_payments_student] FOREIGN KEY ([student_id]) 
            REFERENCES [dbo].[users]([id]),
        CONSTRAINT [FK_payments_organizer] FOREIGN KEY ([organizer_id]) 
            REFERENCES [dbo].[users]([id]),
        CONSTRAINT [FK_payments_verified_by] FOREIGN KEY ([verified_by_id]) 
            REFERENCES [dbo].[users]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_payments_status] ON [dbo].[payments]([status]);
    PRINT '[+] Table [dbo].[payments] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[payments] already exists. Preserved.';
END
GO

-- 13. ATTENDANCE SESSIONS
IF OBJECT_ID(N'[dbo].[attendance_sessions]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[attendance_sessions] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [session_name] NVARCHAR(120) NOT NULL,
        [session_number] INT NOT NULL DEFAULT 1,
        [event_date] DATE NULL,
        [start_time] TIME NULL,
        [end_time] TIME NULL,
        [status] NVARCHAR(30) NOT NULL DEFAULT 'UPCOMING',
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_event_session_number] UNIQUE ([event_id], [session_number]),
        CONSTRAINT [FK_attendance_sessions_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]) ON DELETE CASCADE
    );
    CREATE NONCLUSTERED INDEX [IX_attendance_sessions_event] ON [dbo].[attendance_sessions]([event_id]);
    PRINT '[+] Table [dbo].[attendance_sessions] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[attendance_sessions] already exists. Preserved.';
END
GO

-- 14. ATTENDANCE RECORDS
IF OBJECT_ID(N'[dbo].[attendance_records]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[attendance_records] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [registration_id] INT NOT NULL,
        [event_id] INT NOT NULL,
        [student_id] INT NOT NULL,
        [session_id] INT NULL,
        [marked_by_id] INT NULL,
        [scanned_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [verification_method] NVARCHAR(30) NOT NULL DEFAULT 'QR_SCAN',
        [status] NVARCHAR(20) NOT NULL DEFAULT 'PRESENT',
        [remarks] NVARCHAR(255) NULL,
        CONSTRAINT [UQ_event_session_student_attendance] UNIQUE ([event_id], [session_id], [student_id]),
        CONSTRAINT [FK_attendance_records_registration] FOREIGN KEY ([registration_id]) 
            REFERENCES [dbo].[event_registrations]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_attendance_records_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]),
        CONSTRAINT [FK_attendance_records_session] FOREIGN KEY ([session_id]) 
            REFERENCES [dbo].[attendance_sessions]([id]),
        CONSTRAINT [FK_attendance_records_student] FOREIGN KEY ([student_id]) 
            REFERENCES [dbo].[users]([id]),
        CONSTRAINT [FK_attendance_records_marked_by] FOREIGN KEY ([marked_by_id]) 
            REFERENCES [dbo].[users]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_attendance_records_reg] ON [dbo].[attendance_records]([registration_id]);
    PRINT '[+] Table [dbo].[attendance_records] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[attendance_records] already exists. Preserved.';
END
GO

-- 15. ANNOUNCEMENTS
IF OBJECT_ID(N'[dbo].[announcements]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[announcements] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [author_id] INT NOT NULL,
        [title] NVARCHAR(200) NOT NULL,
        [message] NVARCHAR(MAX) NOT NULL,
        [is_pinned] BIT NOT NULL DEFAULT 0,
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [FK_announcements_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_announcements_author] FOREIGN KEY ([author_id]) 
            REFERENCES [dbo].[users]([id])
    );
    PRINT '[+] Table [dbo].[announcements] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[announcements] already exists. Preserved.';
END
GO

-- 16. CERTIFICATES
IF OBJECT_ID(N'[dbo].[certificates]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[certificates] (
        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [event_id] INT NOT NULL,
        [student_id] INT NULL,
        [registration_id] INT NULL,
        [certificate_code] NVARCHAR(64) NOT NULL,
        [roll_number] NVARCHAR(50) NULL,
        [file_path] NVARCHAR(255) NOT NULL,
        [original_filename] NVARCHAR(255) NOT NULL,
        [file_type] NVARCHAR(20) NOT NULL DEFAULT 'pdf',
        [extracted_text] NVARCHAR(MAX) NULL,
        [status] NVARCHAR(30) NOT NULL DEFAULT 'UNMATCHED',
        [assigned_by_id] INT NULL,
        [upload_date] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [created_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        [updated_at] DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT [UQ_certificates_code] UNIQUE ([certificate_code]),
        CONSTRAINT [FK_certificates_event] FOREIGN KEY ([event_id]) 
            REFERENCES [dbo].[events]([id]) ON DELETE CASCADE,
        CONSTRAINT [FK_certificates_student] FOREIGN KEY ([student_id]) 
            REFERENCES [dbo].[users]([id]),
        CONSTRAINT [FK_certificates_registration] FOREIGN KEY ([registration_id]) 
            REFERENCES [dbo].[event_registrations]([id]),
        CONSTRAINT [FK_certificates_assigned_by] FOREIGN KEY ([assigned_by_id]) 
            REFERENCES [dbo].[users]([id])
    );
    CREATE NONCLUSTERED INDEX [IX_certificates_code] ON [dbo].[certificates]([certificate_code]);
    PRINT '[+] Table [dbo].[certificates] created successfully.';
END
ELSE
BEGIN
    PRINT '[*] Table [dbo].[certificates] already exists. Preserved.';
END
GO

PRINT '==============================================================================';
PRINT 'Campus Flow Microsoft SQL Server Schema Verification Completed Successfully.';
PRINT '==============================================================================';
GO
