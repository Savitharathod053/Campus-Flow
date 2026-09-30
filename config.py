import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

def get_database_uri():
    """
    Retrieve and normalize the relational database connection URI.
    Supports Supabase PostgreSQL, Railway PostgreSQL, and local environments.
    Automatically handles driver, SSL negotiation, and connection parameters.
    """
    # Check all standard environment variable names used by cloud providers (Railway, Supabase, Neon, Render)
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
    
    is_prod = bool(
        os.environ.get('RAILWAY_ENVIRONMENT') or
        os.environ.get('RAILWAY_STATIC_URL') or
        os.environ.get('RENDER') or
        os.environ.get('FLASK_ENV', '').lower() == 'production' or
        os.environ.get('ENVIRONMENT', '').lower() == 'production'
    )
    
    if not raw_uri or not raw_uri.strip():
        if is_prod:
            raise RuntimeError(
                "[Campus Flow Configuration Error] Database configuration missing: DATABASE_URL is not set. "
                "Please configure DATABASE_URL in your Railway / cloud environment variables."
            )
        # If running locally on Windows without cloud DATABASE_URL, use local SQL Server
        if os.name == 'nt':
            return 'mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes'
        # On Linux / Local container fallback to SQLite instance database
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
    # Supabase and external remote hosts require TLS/SSL.
    # Internal private networks (e.g. Docker / internal localhost) allow non-SSL.
    if uri.startswith("postgresql") and "sslmode=" not in uri:
        from urllib.parse import urlparse
        try:
            cleaned_target = uri.replace("postgresql+psycopg2://", "http://", 1).replace("postgresql://", "http://", 1)
            parsed = urlparse(cleaned_target)
            host = (parsed.hostname or '').lower()
            
            # An internal host on a local container has no dots in hostname or is localhost
            is_internal_network = (
                host in ('localhost', '127.0.0.1') or
                ('.' not in host and host != '') or
                host.endswith('.internal') or
                host.endswith('.local')
            )
            
            delimiter = "&" if "?" in uri else "?"
            if is_internal_network:
                uri = f"{uri}{delimiter}sslmode=prefer"
            else:
                # Supabase / External hosted PostgreSQL: enforce TLS
                uri = f"{uri}{delimiter}sslmode=require"
        except Exception:
            delimiter = "&" if "?" in uri else "?"
            uri = f"{uri}{delimiter}sslmode=require"
    
    return uri



class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'campus-flow-secure-college-event-secret-key-2026')
    
    # Relational Database URI (Supabase PostgreSQL / Hosted PostgreSQL)
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_timeout': 30,
    }
    
    # Upload Directories
    UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
    POSTER_FOLDER = UPLOAD_FOLDER / 'posters'
    QRCODE_FOLDER = UPLOAD_FOLDER / 'qrcodes'
    CERTIFICATE_FOLDER = UPLOAD_FOLDER / 'certificates'
    PAYMENT_PROOF_FOLDER = UPLOAD_FOLDER / 'payment_proofs'
    ORGANIZER_QR_FOLDER = UPLOAD_FOLDER / 'organizer_qrs'
    
    # Persistent Cloud Storage (Supabase Storage)
    SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip().rstrip('/')
    SUPABASE_SERVICE_ROLE_KEY = (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('SUPABASE_KEY') or '').strip()
    SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY
    SUPABASE_STORAGE_BUCKET = (os.environ.get('SUPABASE_STORAGE_BUCKET') or os.environ.get('STORAGE_BUCKET') or 'payment-proofs').strip().strip("'\"")
    STORAGE_BUCKET = SUPABASE_STORAGE_BUCKET
    
    # Frontend URL (Vercel deployment URL or comma-separated origins for CORS)
    FRONTEND_URL = os.environ.get('FRONTEND_URL', '').strip()
    
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
    
    # Session & Cookie Configuration (Optimized for cross-domain Vercel frontend <-> Railway backend)
    _is_production = bool(
        os.environ.get('RAILWAY_ENVIRONMENT') or
        os.environ.get('RAILWAY_ENVIRONMENT_NAME') or
        os.environ.get('RAILWAY_PROJECT_ID') or
        os.environ.get('RAILWAY_PUBLIC_DOMAIN') or
        os.environ.get('RAILWAY_STATIC_URL') or
        os.environ.get('RENDER') or
        os.environ.get('FLASK_ENV', '').lower() == 'production' or
        os.environ.get('ENVIRONMENT', '').lower() == 'production'
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True if _is_production else (os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1', 't'))
    # Cross-site cookie (None) requires Secure=True; for local development over HTTP Lax is used
    SESSION_COOKIE_SAMESITE = 'None' if (_is_production and SESSION_COOKIE_SECURE) else 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

    # Email / SMTP & HTTPS API Configuration
    RESEND_API_KEY = (os.environ.get('RESEND_API_KEY') or os.environ.get('RESEND_KEY') or os.environ.get('RESEND_TOKEN') or os.environ.get('RESEND') or '').strip().strip("'\"")
    BREVO_API_KEY = (os.environ.get('BREVO_API_KEY') or os.environ.get('SENDINBLUE_API_KEY') or '').strip().strip("'\"")

    SMTP_HOST = (os.environ.get('SMTP_HOST') or os.environ.get('MAIL_SERVER') or 'smtp.gmail.com').strip().strip("'\"")
    try:
        SMTP_PORT = int(str(os.environ.get('SMTP_PORT') or os.environ.get('MAIL_PORT') or '587').strip().strip("'\""))
    except (ValueError, TypeError):
        SMTP_PORT = 587
    SMTP_USE_TLS = (os.environ.get('SMTP_USE_TLS') or os.environ.get('MAIL_USE_TLS') or 'True').strip().lower() in ('true', '1', 't', 'yes')
    SMTP_USE_SSL = (os.environ.get('SMTP_USE_SSL') or os.environ.get('MAIL_USE_SSL') or 'False').strip().lower() in ('true', '1', 't', 'yes')
    SMTP_USERNAME = (os.environ.get('SMTP_USERNAME') or os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")
    
    _raw_pw = (os.environ.get('SMTP_PASSWORD') or os.environ.get('MAIL_PASSWORD') or '').strip().strip("'\"")
    # For Gmail, strip all internal spaces from 16-character App Passwords
    SMTP_PASSWORD = "".join(_raw_pw.split()) if ('gmail' in SMTP_HOST.lower() or 'google' in SMTP_HOST.lower()) else _raw_pw

    SMTP_FROM_EMAIL = (os.environ.get('SMTP_FROM_EMAIL') or os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_FROM') or SMTP_USERNAME or 'noreply@campusflow.edu').strip().strip("'\"")
    SMTP_FROM_NAME = (os.environ.get('SMTP_FROM_NAME') or os.environ.get('MAIL_FROM_NAME') or 'Campus Flow').strip().strip("'\"")

    # Backward compatibility aliases for existing services and templates
    MAIL_SERVER = SMTP_HOST
    MAIL_PORT = SMTP_PORT
    MAIL_USE_TLS = SMTP_USE_TLS
    MAIL_USE_SSL = SMTP_USE_SSL
    MAIL_USERNAME = SMTP_USERNAME
    MAIL_PASSWORD = SMTP_PASSWORD
    MAIL_DEFAULT_SENDER = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>" if SMTP_FROM_NAME and '<' not in SMTP_FROM_EMAIL else SMTP_FROM_EMAIL

    # Dev redirection: strictly disabled by default in production so college emails reach recipients
    _default_redirect = 'False' if _is_production else 'True'
    MAIL_DEV_REDIRECT_ENABLED = os.environ.get('MAIL_DEV_REDIRECT_ENABLED', _default_redirect).strip().lower() in ('true', '1', 't', 'yes')
    MAIL_LIVE_TEST_RECIPIENT = (os.environ.get('MAIL_LIVE_TEST_RECIPIENT') or SMTP_USERNAME or '').strip().strip("'\"")

