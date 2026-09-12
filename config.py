import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

def get_database_uri():
    """
    Retrieve and normalize the relational database connection URI.
    Supports Render PostgreSQL, Microsoft SQL Server (local SSMS / MSSQL), MySQL, and SQLite.
    Automatically handles driver and connection parameters for Render PostgreSQL and SQL Server.
    """
    raw_uri = os.environ.get('DATABASE_URL')
    if not raw_uri or not raw_uri.strip():
        # If running on Windows with local SQL Server:
        if os.name == 'nt':
            return 'mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes'
        # On Linux / Cloud fallback to SQLite instance database
        db_path = BASE_DIR / 'instance' / 'fastfest.db'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f'sqlite:///{db_path}'
    
    uri = raw_uri.strip().strip("'\"")
    
    # Render / Heroku provides postgres:// or postgresql:// scheme.
    # In SQLAlchemy 2.0+, 'postgres://' is not recognized; 'postgresql+psycopg2://' explicitly
    # targets the psycopg2-binary driver installed in requirements.txt.
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql+psycopg2://", 1)
    elif uri.startswith("postgresql://") and not uri.startswith("postgresql+"):
        uri = uri.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif uri.startswith("mssql://"):
        uri = uri.replace("mssql://", "mssql+pyodbc://", 1)
    elif uri.startswith("sqlserver://"):
        uri = uri.replace("sqlserver://", "mssql+pyodbc://", 1)
    elif uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)

    # If connecting to a remote PostgreSQL instance (e.g. Render external database URL)
    # and sslmode is not specified, append sslmode=require for secure TLS connectivity.
    if uri.startswith("postgresql") and "@localhost" not in uri and "@127.0.0.1" not in uri and "sslmode=" not in uri:
        delimiter = "&" if "?" in uri else "?"
        uri = f"{uri}{delimiter}sslmode=require"
    
    return uri


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'campus-flow-secure-college-event-secret-key-2026')
    
    # Relational Database URI (Render PostgreSQL / Microsoft SQL Server)
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
    MAIL_SERVER = (os.environ.get('MAIL_SERVER') or 'smtp.gmail.com').strip().strip("'\"")
    try:
        MAIL_PORT = int((os.environ.get('MAIL_PORT') or '587').strip().strip("'\""))
    except (ValueError, TypeError):
        MAIL_PORT = 587
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').strip().lower() in ('true', '1', 't', 'yes')
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').strip().lower() in ('true', '1', 't', 'yes')
    MAIL_USERNAME = (os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")
    MAIL_PASSWORD = (os.environ.get('MAIL_PASSWORD') or '').strip().strip("'\"")
    MAIL_DEFAULT_SENDER = (os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")
