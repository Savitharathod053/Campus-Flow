# Campus Flow - College Event Management & Registration Platform

A centralized, production-grade web application for college campuses to manage event discovery, student registrations, custom application questions, online payments, verifiable QR ticketing, camera-based attendance tracking, and AI/OCR-powered certificate distribution.

---

## Overview

**Campus Flow** eliminates fragmented Google Forms and WhatsApp coordination by providing a single, unified campus platform.

- **Students** discover events, register with eligibility checks, complete payments, receive verifiable QR tickets, and access official certificates in their personal vault.
- **Organizers** create multi-stage events, define custom registration questionnaires, monitor real-time participant rosters, scan QR codes via camera for attendance, and bulk-upload external certificates with automated OCR roll number matching.
- **Administrators & Faculty** approve organizer accounts and event proposals, enforce department guidelines, monitor college-wide analytics, and manage system access.

---

## Key Features

### 1. Student Portal
- **Discovery & Search**: Filter upcoming and past events by department, year eligibility, event track (Workshop, Hackathon, Seminar, Cultural, etc.), and pricing.
- **Custom Questionnaires**: Dynamic responses for team names, GitHub profiles, dietary needs, or T-shirt sizes.
- **Direct UPI & QR Payments**: Direct peer-to-organizer UPI payment support (UPI QR code, UPI ID, UPI Phone number) with student payment-proof submission.
- **Smart Payment Verification Engine**: Automated OCR text extraction, transaction ID matching, amount reconciliation, duplicate payment detection (UTR & image hashing), and image fraud/manipulation analysis (EXIF & ELA heuristics).
- **Organizer Verification Dashboard**: One-click verify and reject workflow with fraud risk assessment badges (LOW, MEDIUM, HIGH) before issuing cryptographic tickets.
- **Digital QR Tickets**: High-resolution, cryptographic QR tickets printable or scannable on mobile phones (generated strictly upon payment verification).
- **My Certificates Vault**: Secure private access and download for official participation certificates.

### 2. Organizer Portal
- **Event Lifecycle Management**: Create events with venue, timestamps, deadlines, participant limits, registration fees, UPI QR/ID payment configuration, rules, and posters.
- **Payment Verification Queue**: Review submitted payment proofs, detected amounts vs expected fees, UTR reference IDs, fraud risk scores, and approve or reject submissions.
- **Department Approvals**: Automatic routing to department faculty admins for verification.
- **Live Attendance Scanner**: In-browser camera QR code scanner with instant duplicate entry detection and sound notifications.
- **Roster Export**: Instant export to styled Microsoft Excel (`.xlsx`) and CSV reports with all custom form answers.
- **Certificate Upload & OCR Processing**:
  - Bulk upload external PDF or image certificates (or single ZIP archive).
  - Built-in text extraction and OCR (using Tesseract and PyPDF).
  - Automated regex and candidate matching against student roll numbers.
  - Manual review modal for unmatched certificates and duplicate resolution.

### 3. Admin & Faculty Portal
- **Department Verification**: Department-specific faculty approval queues for organizer applications and events.
- **College-wide Analytics**: Real-time metrics on total revenue, department-wise participation, attendance percentages, and registration counts.
- **User & Event Moderation**: Active status toggles and permanent event cleanup.
- **Safe Expiration Cleanup**: Deletion of expired events only after all certificates have been delivered to students.

---

## Technology Stack

- **Backend Framework**: Python 3.11+ / Flask 3.0+
- **Database Engine**: Microsoft SQL Server (MSSQL / SSMS) via SQLAlchemy 2.0 & PyODBC
- **Database Migrations**: Flask-Migrate / Alembic
- **WSGI Production Server**: Waitress (Windows) / Gunicorn (Linux/Containers)
- **Frontend / UI**: Bootstrap 5.3, Bootstrap Icons, HTML5, CSS3, Vanilla JS
- **Document, OCR & Fraud Processing**: PyPDF, Tesseract-OCR, Pillow, QRCode
- **Data Export**: OpenPyXL, Pandas
- **Payment Verification Engine**: Direct UPI / QR Proof Engine with OCR extraction and ELA image fraud heuristics

---

## Project Structure

```
campus_flow/
│
├── app.py                      # Flask Application Factory & Error Handlers
├── config.py                   # Centralized Configuration & Database Connection
├── wsgi.py                     # Production WSGI Entry Point (Gunicorn / Waitress)
├── run.py                      # Local Development Server Runner
├── create_admin.py             # Secure Production Administrator Creation CLI
├── reset_database.py           # Production-Safe Database Reset & Clean Init Utility
├── backup_database.py          # Database Export & Backup Utility
├── create_mssql_db.py          # Automated SQL Server Database Creator
├── delete_expired_events.py    # Expired Events Cleanup Service
├── requirements.txt            # Production Python Dependencies
├── Procfile                    # Cloud Deployment Process Definition
├── Dockerfile                  # Containerized Production Image
├── .dockerignore               # Docker Build Ignored Patterns
├── .gitignore                  # Git Version Control Exclusion Rules
├── .env.example                # Environment Configuration Template
├── README.md                   # Comprehensive System Documentation
│
├── models/                     # SQLAlchemy Relational Models
│   ├── __init__.py
│   ├── user.py                 # User, StudentProfile, OrganizerProfile, FacultyProfile
│   ├── event.py                # Event, EventStatus, EventType, CustomRegistrationField
│   ├── registration.py         # EventRegistration, RegistrationStatus, CustomFieldResponse
│   ├── payment.py              # Payment, PaymentStatus
│   ├── attendance.py           # AttendanceRecord, VerificationMethod
│   ├── announcement.py         # Event Announcements
│   └── certificate.py          # Certificate, CertificateStatus
│
├── routes/                     # Blueprint Route Controllers
│   ├── __init__.py
│   ├── auth.py                 # Authentication, Role Decorators, Registration
│   ├── public.py               # Landing Page, Event Search, Health Check (/health)
│   ├── student.py              # Student Dashboard, Event Registration, Tickets, Certs
│   ├── organizer.py            # Organizer Portal, Event Management, Scanner, Cert Uploads
│   ├── admin.py                # Faculty Admin Dashboard, Approvals, Reports, User Mgmt
│   ├── payment.py              # UPI Checkout, Proof Submission & Secure Proof Viewing
│   └── certificates.py         # Public Certificate Verification Route
│
├── services/                   # Business Logic & Infrastructure Services
│   ├── cert_service.py         # Certificate Generator
│   ├── cert_upload_service.py  # Bulk Upload & Student Matching Pipeline
│   ├── ocr_service.py          # PyPDF Text Extraction & Tesseract OCR
│   ├── event_service.py        # Event Lifecycle & File Cleanup
│   ├── export_service.py       # Excel / CSV Roster Generation
│   ├── qr_service.py           # QR Code Generator for Tickets
│   └── payment_verification_service.py # OCR Verification, Duplicate Check & Image Fraud Analysis
│
├── static/                     # Static Assets
│   ├── css/style.css           # Modern Campus Flow Theme
│   ├── js/app.js               # Flash Alert Handling & UI Helpers
│   ├── js/qr_scanner.js        # HTML5 In-Browser Camera Scanner
│   └── uploads/                # Managed Storage (Posters, QR Codes, Certificates)
│       ├── posters/
│       ├── qrcodes/
│       └── certificates/
│
└── templates/                  # Jinja2 HTML Templates
    ├── base.html               # Global Layout, Navbar & Footer
    ├── admin/                  # Faculty Admin Views
    ├── auth/                   # Login, Registration & Profile Views
    ├── certificates/           # Verification Page
    ├── organizer/              # Organizer Views, Scanner & Cert Management
    ├── partials/               # Production Error Pages (400, 403, 404, 500)
    ├── public/                 # Public Directory & Detail Views
    └── student/                # Student Dashboard, Tickets & Cert Vault
```

---

## Installation & Setup

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.11, 3.12, 3.14)
- **Microsoft SQL Server (SSMS)** (2016, 2019, 2022 or Azure SQL)
- **ODBC Driver 18 for SQL Server** (or ODBC Driver 17)
- **Tesseract-OCR** (Optional for image certificate OCR)

### 2. Clone & Virtual Environment Setup
```powershell
# Navigate to project directory
cd fastfest

# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt
```

---

## Environment Variables Configuration

Create a `.env` file in the project root based on `.env.example`:

```ini
FLASK_APP=app.py
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5000

# Generate a strong key: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your_generated_random_64_character_production_secret_key

# Microsoft SQL Server Database Connection (Windows Authentication)
DATABASE_URL=mssql+pyodbc://@localhost/campus_flow?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes

# Organizer Payment Proofs & QR Storage Configuration
PAYMENT_PROOF_FOLDER=static/uploads/payment_proofs
ORGANIZER_QR_FOLDER=static/uploads/organizer_qrs
MAX_PAYMENT_PROOF_SIZE_MB=10

# OCR Configuration
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
SESSION_COOKIE_SECURE=True
```

---

## Microsoft SQL Server (MSSQL / SSMS) Setup

### 1. Create the Database Automatically
Run the built-in database creator:
```powershell
python create_mssql_db.py --dbname campus_flow
```
Or create it manually in SQL Server Management Studio (SSMS):
```sql
CREATE DATABASE campus_flow;
```

### 2. Initialize Clean Production Schema
Run the database reset tool to create all tables and relationships with no demo data:
```powershell
python reset_database.py --confirm
```

---

## Creating the First Administrator

To securely create the initial Faculty Administrator account without default passwords:

```powershell
python create_admin.py
```
You will be prompted for:
- **Administrator Name** (e.g. Dr. A. Sharma)
- **Email** (e.g. admin@college.edu)
- **Password** (Secured with Werkzeug pbkdf2/bcrypt hashing)
- **Department** (e.g. Computer Science / General)

Or pass arguments directly:
```powershell
python create_admin.py --name "Dean of Academics" --email "admin@college.edu" --password "YourStrongPassword@2026" --department "General"
```

---

## Production Deployment Architecture

Campus Flow is architected for modern cloud deployment across three decoupled services:
- **Frontend**: Vercel (Global Edge CDN, static asset caching, SPA/API rewrites)
- **Backend**: Railway (Python Flask WSGI container with Gunicorn)
- **Database & Storage**: Supabase (Hosted PostgreSQL database + persistent Cloud Storage)

```
[Browser / Mobile] 
        │
        ├── (Static Assets / HTML) ──────────► [Vercel Edge]
        │
        └── (API / Auth / Logic / Forms) ────► [Railway Flask Backend]
                                                       │
                           ┌───────────────────────────┴───────────────────────────┐
                           ▼                                                       ▼
            [Supabase PostgreSQL DB]                                [Supabase Storage Bucket]
            (Registrations, Users, Events)                           (Payment Proofs, QRs, Posters)
```

---

### Step 1: Setting Up Supabase (Database & Storage)

1. **Create Supabase Project**:
   - Go to [Supabase](https://supabase.com) and create a new project.
   - Note your database password and project reference ID.
2. **Obtain Database Connection String**:
   - Navigate to **Project Settings** -> **Database**.
   - Under **Connection string**, select **URI**.
   - Copy the URI (use port 6543 pooler or port 5432 direct):
     ```
     postgresql://postgres.[project-id]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require
     ```
3. **Configure Storage Bucket**:
   - Go to **Storage** -> **New Bucket**.
   - Name the bucket `payment-proofs` (or custom name configured in `SUPABASE_STORAGE_BUCKET`).
   - Toggle **Public Bucket** to **ON** (allows browser display of verified payment receipts and QR codes).
   - Under **Policies**, ensure public read access is enabled.
4. **Obtain API Credentials**:
   - Go to **Project Settings** -> **API**.
   - Copy **Project URL** (`SUPABASE_URL`).
   - Copy the `service_role` secret key (`SUPABASE_SERVICE_ROLE_KEY`). *Do not use the publishable anon key.*

---

### Step 2: Deploying Backend to Railway

1. **Create Railway Project**:
   - Log into [Railway](https://railway.app) and click **New Project** -> **Deploy from GitHub repo**.
   - Select the `Campus-Flow` repository.
2. **Set Environment Variables on Railway**:
   In your Railway service dashboard under **Variables**, set:
   - `DATABASE_URL`: Your Supabase PostgreSQL connection URI.
   - `SECRET_KEY`: A secure 64-character random string (`python -c "import secrets; print(secrets.token_hex(32))"`).
   - `FRONTEND_URL`: Your Vercel frontend URL (e.g. `https://your-campus-flow.vercel.app`).
   - `SESSION_COOKIE_SECURE`: `True`
   - `SUPABASE_URL`: Your Supabase Project URL.
   - `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase Service Role Key.
   - `SUPABASE_STORAGE_BUCKET`: `payment-proofs`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: Your email SMTP settings.
   - `MAIL_DEV_REDIRECT_ENABLED`: `False`
3. **Deployment**:
   - Railway will automatically detect `railway.json` and `Procfile`.
   - The deployment command runs database migrations (`python migrate_production_schema.py`) and binds Gunicorn to `0.0.0.0:$PORT`.
   - Healthcheck endpoint: `GET /health` (returns `{"status": "ok"}`).
4. **Copy Railway Public Domain**:
   - Under **Settings** -> **Networking**, generate a Railway public domain (e.g. `https://campus-flow-backend.up.railway.app`).

---

### Step 3: Deploying Frontend to Vercel

1. **Import Project to Vercel**:
   - Go to [Vercel](https://vercel.com) and click **Add New...** -> **Project**.
   - Import your `Campus-Flow` repository.
2. **Configure Build Settings**:
   - **Framework Preset**: Other / None
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
3. **Set Environment Variables on Vercel**:
   Under **Environment Variables**, add:
   - `VITE_API_URL`: Your Railway backend domain (e.g. `https://campus-flow-backend.up.railway.app`).
   - `BACKEND_URL`: Your Railway backend domain (e.g. `https://campus-flow-backend.up.railway.app`).
4. **Deploy**:
   - Click **Deploy**. Vercel will build the static assets, generate the runtime configuration, and configure edge rewrites pointing dynamic routes to Railway.
5. **Update Backend CORS**:
   - Copy your assigned Vercel URL (e.g. `https://campus-flow.vercel.app`).
   - In your Railway dashboard, verify `FRONTEND_URL` is set to this domain.

---

## Health Check Endpoints

Campus Flow provides built-in health monitoring endpoints for cloud uptime checks:
- **Application Health**: `GET /health` -> `{"status": "ok"}` (HTTP 200)
- **Database Connectivity**: `GET /health/db` -> `{"status": "connected", "dialect": "postgresql"}` (HTTP 200)

---

## Certificate Upload & OCR Workflow

1. **External Generation**: Organizers create certificate PDFs or images using their standard campus design tools.
2. **Bulk Upload**: In the Organizer Portal (`/organizer/events/<id>/certificates`), upload multiple PDF/image files or a single `.zip` archive.
3. **Text & Roll Number Extraction**:
   - For native PDFs: Fast text layer extraction via PyPDF.
   - For scanned images/PDFs: Optical Character Recognition (OCR) via Tesseract.
   - The engine searches for student roll numbers using known event registrant IDs and configurable regex patterns.
4. **Matching & Status**:
   - `MATCHED`: Student roll number identified in registration roster -> certificate automatically assigned.
   - `UNMATCHED`: Roll number not recognized -> organizer can manually assign to any registered student.
   - `DUPLICATE`: Multiple certificates detected for the same student -> organizer can choose to keep or overwrite.
5. **Student Access**: Students access only their verified certificates in the **My Certificates** tab and download with authenticated authorization checks.

---

## Security Architecture

- **Role-Based Access Control**: Strict decorators (`@student_required`, `@organizer_required`, `@admin_required`) prevent privilege escalation.
- **Certificate Access Guard**: Certificate download routes verify user session and ownership (`cert.student_id == user.id`), preventing unauthorized enumeration.
- **ZIP Slip & Path Traversal Protection**: Upload handlers validate canonical filesystem paths and sanitize filenames.
- **SQL Injection Prevention**: 100% parameterized queries via SQLAlchemy ORM.
- **CSRF & XSS Protection**: Jinja2 automatic contextual escaping and CSRF tokens across all form actions.
- **Secure Cookie Flags**: `HttpOnly`, `SameSite=Lax`, and `Secure` flags configured for session cookies.
- **Error Obfuscation**: Production error pages (400, 403, 404, 500) hide stack traces and server internals.

---

## Database Backup & Restore

### Backup
Create a full JSON export of all database tables and entities before any maintenance:
```powershell
python backup_database.py
```
Backups are saved to `backups/campus_flow_backup_<timestamp>.json`.

### Clean Reset
To clear all data and start with an empty database:
```powershell
python reset_database.py --confirm
```

---

## Troubleshooting

1. **pyodbc Connection Error to SQL Server**:
   - Ensure Microsoft SQL Server is running.
   - Verify `ODBC Driver 18 for SQL Server` is installed.
   - If using a self-signed local certificate, ensure `TrustServerCertificate=yes` is in `DATABASE_URL`.

2. **Tesseract OCR not recognized**:
   - Set the full path to `tesseract.exe` in `.env`:
     `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`

3. **Port already in use**:
   - Specify a different port using environment variable:
     `PORT=8000 python run.py`
