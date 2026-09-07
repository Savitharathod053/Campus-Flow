import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

def get_database_uri():
    """
    Retrieve and normalize the relational database connection URI.
    Supports Microsoft SQL Server (SSMS / MSSQL), PostgreSQL, MySQL, and SQLite.
    Automatically handles driver and connection parameters for SQL Server / SSMS.
    """
    uri = os.environ.get('DATABASE_URL')
    if not uri:
        # If running on Windows with local SQL Server:
        if os.name == 'nt':
            return 'mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes'
        # On Linux / Cloud (e.g. Render, Heroku, Container) fallback to SQLite instance database
        db_path = BASE_DIR / 'instance' / 'fastfest.db'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f'sqlite:///{db_path}'
    
    # Normalize mssql:// or sqlserver:// dialect scheme to mssql+pyodbc://
    if uri.startswith("mssql://"):
        uri = uri.replace("mssql://", "mssql+pyodbc://", 1)
    elif uri.startswith("sqlserver://"):
        uri = uri.replace("sqlserver://", "mssql+pyodbc://", 1)
    elif uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    elif uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    
    return uri


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'campus-flow-secure-college-event-secret-key-2026')
    
    # Relational Database URI (Microsoft SQL Server / SSMS)
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Upload Directories
    UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
    POSTER_FOLDER = UPLOAD_FOLDER / 'posters'
    QRCODE_FOLDER = UPLOAD_FOLDER / 'qrcodes'
    CERTIFICATE_FOLDER = UPLOAD_FOLDER / 'certificates'
    PAYMENT_PROOF_FOLDER = UPLOAD_FOLDER / 'payment_proofs'
    ORGANIZER_QR_FOLDER = UPLOAD_FOLDER / 'organizer_qrs'
    
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB max upload for bulk certificates/ZIP
    
    # Certificate Module & OCR Settings
    ALLOWED_CERTIFICATE_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'zip'}
    ALLOWED_PAYMENT_PROOF_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    MAX_PAYMENT_PROOF_SIZE = 10 * 1024 * 1024  # 10 MB
    ROLL_NUMBER_REGEX_PATTERN = os.environ.get(
        'ROLL_NUMBER_REGEX_PATTERN',
        r'(?:roll\s*(?:no|number|num)?|student\s*id|reg(?:istration)?\s*(?:no|number|num)?|enrollment\s*(?:no|number|num)?|uid)\s*[:\-#.\s]\s*([A-Za-z0-9\-_/]{3,30})'
    )
    TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '')
    
    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV', '').lower() == 'production' and os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1', 't')
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

    # Email / SMTP Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', '1', 't', 'yes')
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() in ('true', '1', 't', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME', '')
