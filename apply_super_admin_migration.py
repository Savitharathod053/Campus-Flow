from app import create_app
from config import Config
from models import db, CollegeDepartment, Department, User, FacultyProfile
from sqlalchemy import text

def run_migration():
    app = create_app(Config)
    with app.app_context():
        print("Applying Super Admin, Departments & Audit Logs migration to SQL Server...")

        # 1. Create table departments if not exists
        db.session.execute(text("""
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
        END
        """))

        # 2. Create table audit_logs if not exists
        db.session.execute(text("""
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
        END
        """))

        # 3. Alter announcements table
        db.session.execute(text("""
        IF OBJECT_ID(N'dbo.announcements', N'U') IS NOT NULL
        BEGIN
            ALTER TABLE dbo.announcements ALTER COLUMN event_id INT NULL;

            IF COL_LENGTH(N'dbo.announcements', N'target_audience') IS NULL
            BEGIN
                ALTER TABLE dbo.announcements ADD target_audience VARCHAR(50) NOT NULL CONSTRAINT DF_announcements_target_audience DEFAULT 'ALL';
            END;

            IF COL_LENGTH(N'dbo.announcements', N'target_department') IS NULL
            BEGIN
                ALTER TABLE dbo.announcements ADD target_department VARCHAR(100) NULL;
            END;

            IF COL_LENGTH(N'dbo.announcements', N'is_active') IS NULL
            BEGIN
                ALTER TABLE dbo.announcements ADD is_active BIT NOT NULL CONSTRAINT DF_announcements_is_active DEFAULT 1;
            END;
        END
        """))

        db.session.commit()
        print("Schema tables and columns updated successfully.")

        # 4. Seed initial departments if empty
        dept_data = [
            ("CSE", "Computer Science & Engineering", "Department of Computer Science & Engineering"),
            ("IT", "Information Technology", "Department of Information Technology"),
            ("CSD", "Computer Science & Engineering in Data Science", "Department of Computer Science & Engineering in Data Science"),
            ("CSM", "Computer Science & Engineering in AI and ML", "Department of Computer Science & Engineering in Artificial Intelligence & Machine Learning"),
            ("ECE", "Electronics & Communication Engineering", "Department of Electronics & Communication Engineering"),
            ("EEE", "Electrical & Electronics Engineering", "Department of Electrical & Electronics Engineering"),
            ("MECH", "Mechanical Engineering", "Department of Mechanical Engineering"),
            ("CIVILS", "Civil Engineering", "Department of Civil Engineering"),
        ]

        for code, name, desc in dept_data:
            dept = CollegeDepartment.query.filter_by(code=code).first()
            if not dept:
                # Find matching faculty admin for HOD if available
                fp = FacultyProfile.query.filter_by(department=code).first()
                hod_id = fp.user_id if fp else None
                new_dept = CollegeDepartment(
                    code=code,
                    name=name,
                    description=desc,
                    hod_id=hod_id,
                    is_active=True
                )
                db.session.add(new_dept)
                print(f"Added department: {code} - {name} (HOD user_id: {hod_id})")

        db.session.commit()
        print("Department seeding completed.")

if __name__ == '__main__':
    run_migration()
