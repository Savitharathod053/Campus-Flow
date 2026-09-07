"""
Migration script for Multi-Session Attendance System in Campus Flow.
Safely migrates SQL Server / SQLite databases and backfills legacy events.
"""
import sys
import logging
from datetime import datetime
from sqlalchemy import text
from app import create_app
from models import db, Event, AttendanceRecord, AttendanceSession, AttendanceSessionStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AttendanceMigration")

app = create_app()

def run_migration():
    with app.app_context():
        engine = db.engine
        dialect_name = engine.dialect.name.lower()
        logger.info(f"Running Attendance Sessions migration on dialect: {dialect_name}")

        with engine.begin() as conn:
            # 1. Update events table
            if 'sqlite' in dialect_name:
                # Check columns in sqlite
                res = conn.execute(text("PRAGMA table_info(events)")).fetchall()
                col_names = [r[1] for r in res]
                if 'enable_attendance' not in col_names:
                    conn.execute(text("ALTER TABLE events ADD COLUMN enable_attendance BOOLEAN DEFAULT 1 NOT NULL"))
                if 'min_attendance_percentage' not in col_names:
                    conn.execute(text("ALTER TABLE events ADD COLUMN min_attendance_percentage FLOAT DEFAULT 0.0 NOT NULL"))
            else:
                # SQL Server / MSSQL
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns 
                        WHERE object_id = OBJECT_ID(N'events') AND name = 'enable_attendance'
                    )
                    BEGIN
                        ALTER TABLE events ADD enable_attendance BIT NOT NULL CONSTRAINT DF_events_enable_att DEFAULT 1;
                    END
                """))
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns 
                        WHERE object_id = OBJECT_ID(N'events') AND name = 'min_attendance_percentage'
                    )
                    BEGIN
                        ALTER TABLE events ADD min_attendance_percentage FLOAT NOT NULL CONSTRAINT DF_events_min_att DEFAULT 0.0;
                    END
                """))

            logger.info("Events table updated with attendance configuration columns.")

            # 2. Create attendance_sessions table if not exists
            if 'sqlite' in dialect_name:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS attendance_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id INTEGER NOT NULL,
                        session_name VARCHAR(120) NOT NULL,
                        session_number INTEGER DEFAULT 1 NOT NULL,
                        event_date DATE NULL,
                        start_time TIME NULL,
                        end_time TIME NULL,
                        status VARCHAR(30) DEFAULT 'UPCOMING' NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                        CONSTRAINT uq_event_session_number UNIQUE (event_id, session_number)
                    )
                """))
            else:
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'attendance_sessions')
                    BEGIN
                        CREATE TABLE attendance_sessions (
                            id INT IDENTITY(1,1) PRIMARY KEY,
                            event_id INT NOT NULL,
                            session_name NVARCHAR(120) NOT NULL,
                            session_number INT NOT NULL DEFAULT 1,
                            event_date DATE NULL,
                            start_time TIME NULL,
                            end_time TIME NULL,
                            status NVARCHAR(30) NOT NULL DEFAULT 'UPCOMING',
                            created_at DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
                            updated_at DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
                            CONSTRAINT FK_att_sessions_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
                            CONSTRAINT uq_event_session_number UNIQUE (event_id, session_number)
                        );
                        CREATE INDEX ix_attendance_sessions_event_id ON attendance_sessions(event_id);
                        CREATE INDEX ix_attendance_sessions_status ON attendance_sessions(status);
                    END
                """))

            logger.info("attendance_sessions table verified/created.")

            # 3. Update attendance_records table
            if 'sqlite' in dialect_name:
                res = conn.execute(text("PRAGMA table_info(attendance_records)")).fetchall()
                col_names = [r[1] for r in res]
                if 'session_id' not in col_names:
                    conn.execute(text("ALTER TABLE attendance_records ADD COLUMN session_id INTEGER NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE"))
                if 'status' not in col_names:
                    conn.execute(text("ALTER TABLE attendance_records ADD COLUMN status VARCHAR(20) DEFAULT 'PRESENT' NOT NULL"))
                if 'remarks' not in col_names:
                    conn.execute(text("ALTER TABLE attendance_records ADD COLUMN remarks VARCHAR(255) NULL"))
            else:
                # SQL Server: Add session_id, status, remarks
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns 
                        WHERE object_id = OBJECT_ID(N'attendance_records') AND name = 'session_id'
                    )
                    BEGIN
                        ALTER TABLE attendance_records ADD session_id INT NULL;
                        ALTER TABLE attendance_records ADD CONSTRAINT FK_att_records_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE NO ACTION;
                        CREATE INDEX ix_attendance_records_session_id ON attendance_records(session_id);
                    END
                """))
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns 
                        WHERE object_id = OBJECT_ID(N'attendance_records') AND name = 'status'
                    )
                    BEGIN
                        ALTER TABLE attendance_records ADD status NVARCHAR(20) NOT NULL CONSTRAINT DF_att_records_status DEFAULT 'PRESENT';
                    END
                """))
                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns 
                        WHERE object_id = OBJECT_ID(N'attendance_records') AND name = 'remarks'
                    )
                    BEGIN
                        ALTER TABLE attendance_records ADD remarks NVARCHAR(255) NULL;
                    END
                """))

                # Drop old unique constraint on registration_id if exists
                conn.execute(text("""
                    DECLARE @ConstraintName nvarchar(200)
                    SELECT TOP 1 @ConstraintName = tc.constraint_name 
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = 'attendance_records' 
                      AND tc.constraint_type = 'UNIQUE'
                      AND kcu.column_name = 'registration_id'
                    
                    IF @ConstraintName IS NOT NULL
                    BEGIN
                        EXEC('ALTER TABLE attendance_records DROP CONSTRAINT [' + @ConstraintName + ']')
                    END
                """))

            logger.info("attendance_records table updated.")

        # 4. Backfill existing events with legacy attendance records
        events = Event.query.all()
        for ev in events:
            if ev.attendance_sessions.count() == 0:
                # Create default Session 1
                default_session = AttendanceSession(
                    event_id=ev.id,
                    session_name="General Attendance",
                    session_number=1,
                    event_date=ev.start_time.date() if ev.start_time else None,
                    start_time=ev.start_time.time() if ev.start_time else None,
                    end_time=ev.end_time.time() if ev.end_time else None,
                    status=AttendanceSessionStatus.ACTIVE
                )
                db.session.add(default_session)
                db.session.flush()

                # Link existing records for this event
                records = AttendanceRecord.query.filter_by(event_id=ev.id, session_id=None).all()
                for rec in records:
                    rec.session_id = default_session.id
                    rec.status = 'PRESENT'

        db.session.commit()
        logger.info(f"Backfill complete for {len(events)} events.")
        logger.info("Multi-Session Attendance migration completed successfully!")

if __name__ == '__main__':
    run_migration()
