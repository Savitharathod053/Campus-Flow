-- ==============================================================================
-- Campus Flow: Super Admin, Departments & Audit Logs Migration for SQL Server
-- Idempotent, safe migration script.
-- ==============================================================================

-- 1. Create 'departments' table if it does not exist
IF OBJECT_ID(N'dbo.departments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.departments (
        id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        code VARCHAR(20) NOT NULL,
        name NVARCHAR(150) NOT NULL,
        description NVARCHAR(MAX) NULL,
        hod_id INT NULL,
        is_active BIT NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        updated_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT UQ_departments_code UNIQUE (code),
        CONSTRAINT FK_departments_hod FOREIGN KEY (hod_id) REFERENCES dbo.users(id)
    );
    CREATE INDEX IX_departments_code ON dbo.departments(code);
    CREATE INDEX IX_departments_is_active ON dbo.departments(is_active);
    PRINT 'Table dbo.departments created.';
END
ELSE
BEGIN
    PRINT 'Table dbo.departments already exists.';
END;

-- 2. Create 'audit_logs' table if it does not exist
IF OBJECT_ID(N'dbo.audit_logs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.audit_logs (
        id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        admin_id INT NULL,
        action VARCHAR(60) NOT NULL,
        target_type VARCHAR(50) NOT NULL,
        target_id INT NULL,
        target_name NVARCHAR(150) NULL,
        details NVARCHAR(MAX) NULL,
        ip_address VARCHAR(45) NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT FK_audit_logs_admin FOREIGN KEY (admin_id) REFERENCES dbo.users(id)
    );
    CREATE INDEX IX_audit_logs_action ON dbo.audit_logs(action);
    CREATE INDEX IX_audit_logs_target_type ON dbo.audit_logs(target_type);
    CREATE INDEX IX_audit_logs_created_at ON dbo.audit_logs(created_at);
    CREATE INDEX IX_audit_logs_admin_id ON dbo.audit_logs(admin_id);
    PRINT 'Table dbo.audit_logs created.';
END
ELSE
BEGIN
    PRINT 'Table dbo.audit_logs already exists.';
END;

-- 3. Update 'announcements' table to allow NULL event_id and add target audience columns
IF OBJECT_ID(N'dbo.announcements', N'U') IS NOT NULL
BEGIN
    -- Allow event_id to be NULL
    ALTER TABLE dbo.announcements ALTER COLUMN event_id INT NULL;

    -- Add target_audience column if missing
    IF COL_LENGTH(N'dbo.announcements', N'target_audience') IS NULL
    BEGIN
        ALTER TABLE dbo.announcements ADD target_audience VARCHAR(50) NOT NULL CONSTRAINT DF_announcements_target_audience DEFAULT 'ALL';
        CREATE INDEX IX_announcements_target_audience ON dbo.announcements(target_audience);
        PRINT 'Added target_audience to dbo.announcements.';
    END;

    -- Add target_department column if missing
    IF COL_LENGTH(N'dbo.announcements', N'target_department') IS NULL
    BEGIN
        ALTER TABLE dbo.announcements ADD target_department VARCHAR(100) NULL;
        PRINT 'Added target_department to dbo.announcements.';
    END;

    -- Add is_active column if missing
    IF COL_LENGTH(N'dbo.announcements', N'is_active') IS NULL
    BEGIN
        ALTER TABLE dbo.announcements ADD is_active BIT NOT NULL CONSTRAINT DF_announcements_is_active DEFAULT 1;
        PRINT 'Added is_active to dbo.announcements.';
    END;
END;
