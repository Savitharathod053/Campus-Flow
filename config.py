import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

def get_database_uri():
    """
    Retrieve and normalize the relational database connection URI.
    Supports Microsoft SQL Server (SSMS / MSSQL), MySQL, PostgreSQL, and SQLite.
    Automatically handles driver and connection parameters for SQL Server / SSMS.
    """
    uri = os.environ.get('DATABASE_URL')
    if not uri:
        # Default local Microsoft SQL Server (SSMS) connection with Windows Authentication
        return 'mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes'
    
    # Normalize mysql:// dialect scheme to mysql+pymysql://
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    # Normalize legacy/cloud postgres:// dialect scheme to postgresql://
    elif uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    # Normalize mssql:// or sqlserver:// dialect scheme to mssql+pyodbc://
    elif uri.startswith("mssql://"):
        uri = uri.replace("mssql://", "mssql+pyodbc://", 1)
    elif uri.startswith("sqlserver://"):
        uri = uri.replace("sqlserver://", "mssql+pyodbc://", 1)
    
    return uri


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fastfest-secure-college-event-secret-key-2026')
    
    # Relational Database URI (SQL Server / SSMS)
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload Directories
    UPLOAD_FOLDER = BASE_DIR / 'static' / 'uploads'
    POSTER_FOLDER = UPLOAD_FOLDER / 'posters'
    QRCODE_FOLDER = UPLOAD_FOLDER / 'qrcodes'
    CERTIFICATE_FOLDER = UPLOAD_FOLDER / 'certificates'
    
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB max upload for bulk certificates/ZIP
    
    # Certificate Module & OCR Settings
    ALLOWED_CERTIFICATE_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'zip'}
    ROLL_NUMBER_REGEX_PATTERN = os.environ.get(
        'ROLL_NUMBER_REGEX_PATTERN',
        r'(?:roll\s*(?:no|number|num)?|student\s*id|reg(?:istration)?\s*(?:no|number|num)?|enrollment\s*(?:no|number|num)?|uid)\s*[:\-#.\s]\s*([A-Za-z0-9\-_/]{3,30})'
    )
    TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '')
    
    # Razorpay Payment Gateway Credentials
    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_placeholder_key')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', 'rzp_test_placeholder_secret')
    # When True, simulated test payments work out-of-the-box without needing real Razorpay API keys
    RAZORPAY_SANDBOX_SIMULATION = os.environ.get('RAZORPAY_SANDBOX_SIMULATION', 'True').lower() in ('true', '1', 't')
    
    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV', '').lower() == 'production' and os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1', 't')
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days
