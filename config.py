import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

def get_database_uri():
    """
    Retrieve and normalize the relational database connection URI.
    Supports Render PostgreSQL (internal & external), Microsoft SQL Server (local SSMS / MSSQL), MySQL, and SQLite.
    Automatically handles driver, SSL negotiation, and connection parameters.
    """
    # Check all standard environment variable names used by cloud providers (Render, Supabase, Neon, Railway)
    raw_uri = (
        os.environ.get('DATABASE_URL') or
        os.environ.get('DATABASE_INTERNAL_URL') or
        os.environ.get('DATABASE_EXTERNAL_URL') or
        os.environ.get('POSTGRES_URL') or
        os.environ.get('POSTGRESQL_URL') or
        os.environ.get('SQLALCHEMY_DATABASE_URI') or
        os.environ.get('DATABASE_URI') or
        os.environ.get('DB_URI')
    )
    
    if not raw_uri or not raw_uri.strip():
        # If running locally on Windows without cloud DATABASE_URL, use local SQL Server
        if os.name == 'nt' and not os.environ.get('RENDER'):
            return 'mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes'
        # On Linux / Cloud container fallback to SQLite instance database
        db_path = BASE_DIR / 'instance' / 'fastfest.db'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f'sqlite:///{db_path}'
    
    uri = raw_uri.strip().strip("'\"")
    
    # Normalize PostgreSQL schemes to target psycopg2-binary
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

    # SSL Mode handling for PostgreSQL:
    # Render internal database connections (e.g. dpg-xxxx:5432) do NOT support SSL and will fail with
    # "psycopg2.OperationalError: server does not support SSL, but SSL was required" if sslmode=require is set.
    # External hosts (e.g. *.render.com, *.neon.tech, *.supabase.co) require SSL.
    if uri.startswith("postgresql") and "sslmode=" not in uri:
        from urllib.parse import urlparse
        try:
            cleaned_target = uri.replace("postgresql+psycopg2://", "http://", 1).replace("postgresql://", "http://", 1)
            parsed = urlparse(cleaned_target)
            host = (parsed.hostname or '').lower()
            
            # An internal host on Render/Docker has no dots in hostname (e.g. 'dpg-cxxxxxx-a') or is localhost
            is_internal_network = (
                host in ('localhost', '127.0.0.1') or
                ('.' not in host and host != '') or
                host.endswith('.internal') or
                host.endswith('.local')
            )
            
            delimiter = "&" if "?" in uri else "?"
            if is_internal_network:
                # Internal private network: use prefer so connection succeeds whether SSL is present or not
                uri = f"{uri}{delimiter}sslmode=prefer"
            else:
                # External remote host across public internet: enforce TLS
                uri = f"{uri}{delimiter}sslmode=require"
        except Exception:
            delimiter = "&" if "?" in uri else "?"
            uri = f"{uri}{delimiter}sslmode=prefer"
    
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
    MAIL_DEV_REDIRECT_ENABLED = os.environ.get('MAIL_DEV_REDIRECT_ENABLED', 'True').strip().lower() in ('true', '1', 't', 'yes')
    MAIL_LIVE_TEST_RECIPIENT = (os.environ.get('MAIL_LIVE_TEST_RECIPIENT') or os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")

    # Razorpay Payment Gateway Configuration (Test Mode by default)
    RAZORPAY_KEY_ID = (os.environ.get('RAZORPAY_KEY_ID') or 'rzp_test_campusflow_dummy').strip().strip("'\"")
    RAZORPAY_KEY_SECRET = (os.environ.get('RAZORPAY_KEY_SECRET') or 'campusflow_test_secret_key_2026').strip().strip("'\"")
    RAZORPAY_WEBHOOK_SECRET = (os.environ.get('RAZORPAY_WEBHOOK_SECRET') or 'campusflow_webhook_secret_2026').strip().strip("'\"")
    RAZORPAY_CURRENCY = (os.environ.get('RAZORPAY_CURRENCY') or 'INR').strip().strip("'\"")
