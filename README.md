# FastFest - College Event Management & Registration Platform

A secure, full-stack, production-grade Python web application built using **Flask**, **Microsoft SQL Server (SSMS 2022)** (via SQLAlchemy, Flask-Migrate & PyODBC), **Jinja2**, **Bootstrap 5**, **Razorpay**, **Pillow**, and **qrcode**.

FastFest replaces fragmented Google Forms and WhatsApp coordination with a single, centralized campus platform where students discover events, register with custom organizer questions, make payments, receive verifiable QR tickets, check in via camera scanner, and download official participation certificates.

---

## 🌟 Key Features by User Role

### 1. 🎓 Student Portal
- **Student Registration & Authentication**: Account setup with Roll Number / USN, Branch/Department, Year of Study (1st–4th), Section, Phone, and Password.
- **Dynamic Event Discovery**: Search and filter by Event Type, Organizing Department, Target Year, Free vs. Paid, and Timeline (Upcoming / Past).
- **Rich Event Details**: High-resolution posters, schedules, venue, faculty coordinator contacts, participant capacity counter, countdown deadlines, and rules.
- **Custom Event Registration**: Auto-loads student profile and renders custom questions defined by the organizer (e.g., Team Name, GitHub link, T-Shirt size, dietary preferences).
- **Integrated Payment Checkout**: Seamless Razorpay payment gateway integration for paid events with automatic instant Sandbox test simulation mode for local evaluation.
- **Digital Pass & Verifiable QR Ticket**: Generates a unique Ticket ID and high-resolution QR code pass with 1-click Print/PDF download.
- **Attendance & Announcement Tracking**: Real-time status updates when attendance is scanned at the venue entrance, plus pinned event broadcast alerts.
- **Automated E-Certificates**: Instant view, download, and public online verification of official participation certificates.

### 2. 👥 Organizer Portal
- **Organizer Dashboard**: Live overview of total events, active registrations, paid revenue, pending approvals, and check-in counts.
- **Event Creation & Proposal**: Comprehensive form with poster upload, venue, date/time range, registration deadlines, capacity, pricing, allowed branches/years/sections, and faculty coordinator assignment.
- **Custom Registration Form Builder**: Add, edit, and reorder custom dynamic fields (Single line text, Textarea, Dropdowns, URLs, Checkbox agreements, Numbers).
- **Approval Lifecycle Tracking**: Transparent workflow states (`DRAFT` → `PENDING_APPROVAL` → `APPROVED` → `REGISTRATION_OPEN` → `EVENT_COMPLETED`).
- **Participant Roster Management**: Searchable participant list filtered by branch, year, payment, and attendance status.
- **1-Click Roster Export**: Export attendee data directly into professionally formatted **Microsoft Excel (`.xlsx`)** spreadsheets or **CSV** files.
- **Live In-Browser Camera QR Scanner**: Built-in webcam/mobile camera QR code reader (powered by HTML5-QRCode & Web Audio API) with instant visual badges, chime feedback, and duplicate scan prevention.
- **Real-Time Announcement Broadcast**: Publish and pin urgent announcements (room changes, schedule updates, competition results) to registered participants.
- **Automated Certificate Engine**: 1-click batch generation of high-resolution certificates with student names, event metadata, and verification QR codes.

### 3. 🛡️ Faculty & Admin Portal
- **Central Administrative Dashboard**: College-wide event governance metrics, total students, total organizers, fee revenues, and pending proposals.
- **Event Review & Approval Workflow**: Inspect submitted event proposals; approve for student visibility or reject with structured feedback reasons.
- **All-Events Moderation Directory**: Oversight of all campus activities with status overrides and cancellation tools.
- **User Governance**: Searchable directory of all Students, Organizers, and Faculty with 1-click account activation / deactivation.
- **Comprehensive Analytics & Reports**:
  - Department-wise participation distribution.
  - Year-wise breakdown (1st, 2nd, 3rd, 4th year).
  - Event-wise registrations, verified turnout percentage, and financial collections.

---

## 🛠️ Technology Stack

| Layer | Technology | Details |
|---|---|---|
| **Backend Framework** | Python 3.10+ / Flask | Modular Blueprints, Werkzeug Security, Jinja2 Templates |
| **Relational Database** | Microsoft SQL Server / SSMS 2022 via PyODBC & SQLAlchemy | Enterprise-grade SQL Server database with Flask-Migrate / Alembic |
| **Frontend UI** | HTML5, CSS3, JavaScript | Bootstrap 5.3, Bootstrap Icons, Custom Design Tokens |
| **Payments** | Razorpay Checkout API | HMAC-SHA256 signature verification + Sandbox Simulation |
| **QR Code Engine** | Python `qrcode` + `Pillow` | High-ECC QR generation for tickets & certificate verification |
| **Certificate Generator**| Python `Pillow` (PIL) | High-resolution landscape graphic renderer |
| **Spreadsheet Exports** | Python `openpyxl` & `csv` | Formatted Excel `.xlsx` workbooks with custom answer columns |

---

## 🗄️ Database Architecture & Relational Schema

```
+------------------+         +----------------------------+
|      users       | <------ |      student_profiles      |
| (email, role,    |         | (roll_number, dept, year)  |
|  password_hash)  | <------ |     organizer_profiles     |
+------------------+         +----------------------------+
        |                                  |
        | 1:N                              | 1:N
        v                                  v
+------------------+         +----------------------------+
|      events      | <------ | custom_registration_fields |
| (title, venue,   |         | (label, type, required)    |
|  deadline, fee,  |         +----------------------------+
|  status, rules)  |                       |
+------------------+                       |
        |                                  |
        | 1:N                              v
+---------------------------------------------------------+
|                    event_registrations                  |
| (registration_code, qr_code, status [CONFIRMED/PENDING])|
|           * UNIQUE (event_id, student_id) *             |
+---------------------------------------------------------+
        |                |                 |
        | 1:1            | 1:1             | 1:1
        v                v                 v
+---------------+ +---------------+ +---------------------+
|   payments    | |  attendance_  | |    certificates     |
| (razorpay_id, | |    records    | |  (certificate_code, |
|  amount, stat)| |  (scanned_at) | |   generated_image)  |
+---------------+ +---------------+ +---------------------+
```

---

## 🚀 Quickstart & Microsoft SQL Server (SSMS) Setup

### 1. Prerequisites
- **Python 3.10+** installed.
- **Microsoft SQL Server** (2022, 2019, 2017, or SQL Express) + **SSMS** (SQL Server Management Studio).
- **ODBC Driver 18 for SQL Server** (or Driver 17).

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Create the Database in SQL Server / SSMS
You can create the database automatically using the provided script:
```bash
python create_mssql_db.py
```
Or in SQL Server Management Studio (SSMS):
```sql
CREATE DATABASE fastfest;
```

### 4. Configure Environment Variables (`.env`)
In your `.env` file in the project root:
```env
# Windows Authentication (Default for local SSMS)
DATABASE_URL=mssql+pyodbc://@localhost/fastfest?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes

SECRET_KEY=fastfest-secret-key-college-app-2026
FLASK_ENV=development
FLASK_DEBUG=1

RAZORPAY_KEY_ID=rzp_test_placeholder_key
RAZORPAY_KEY_SECRET=rzp_test_placeholder_secret
RAZORPAY_SANDBOX_SIMULATION=True
```

### 5. Migrate Existing SQLite Data OR Initialize Fresh Database

#### Option A: Migrate Existing Data into SQL Server
Safely transfer existing data into SQL Server:
```bash
# 1. Preview records with a dry-run
python migrate_sqlite_to_mssql.py --dry-run

# 2. Perform live migration
python migrate_sqlite_to_mssql.py
```

#### Option B: Fresh Database Initialization with Sample Demo Data
```bash
python seed_data.py
```

### 6. Start FastFest Local Server
```bash
python app.py
```
Open your browser and visit: **`http://127.0.0.1:5000`**

---

## 🔑 Pre-Configured Demo Credentials

| Role | Email | Password | Details |
|---|---|---|---|
| **Student** | `student1@college.edu` | `Pass@123` | Rahul Sharma (3rd Year CSE, Roll: 1MS21CS045) |
| **Student 2** | `student2@college.edu` | `Pass@123` | Ananya Rao (2nd Year ECE, Roll: 1MS22EC012) |
| **Organizer** | `organizer@college.edu` | `Pass@123` | Priya Patel (ACM Student Chapter Lead) |
| **Faculty Admin** | `admin@college.edu` | `Pass@123` | Dr. S. K. Narayanan (Dean of Student Affairs) |

---

## 💳 Razorpay Payment & Sandbox Testing

- **Live / Sandbox Keys**: Set your credentials in `.env`:
  ```env
  RAZORPAY_KEY_ID=rzp_test_your_key_id
  RAZORPAY_KEY_SECRET=your_key_secret
  RAZORPAY_SANDBOX_SIMULATION=True
  ```
- **Instant Test Simulator**: For local testing without needing a registered Razorpay merchant account, click the **"Simulate Successful Payment (Instant Test)"** button on checkout.

---

## 📸 QR Code Attendance Scanning Workflow

1. A student opens their digital pass at **`/student/ticket/<code>`** or prints it.
2. The event organizer logs in, navigates to the event in **Organizer Portal**, and clicks **"Launch Attendance Scanner"**.
3. Point the camera at the student's QR pass (or enter ticket code).
4. System verifies the ticket, records the check-in timestamp, and plays audio chime feedback.
5. Prevents duplicate scans automatically.

---

## 🏆 Automated Certificate Generation & Public Verification

1. In **Organizer Portal → Event Hub → Issue Certificates**, click **"Generate & Issue All Certificates"**.
2. Certificates are rendered with student name, event metadata, and verification QR codes.
3. Public verification available at `/certificate/verify/<certificate_code>`.

---

## 🧪 Database Migrations (Flask-Migrate / Alembic)

FastFest is equipped with **Flask-Migrate** for database schema evolution:

```bash
# Initialize migration repository (first time only)
flask db init

# Generate a new migration after editing models
flask db migrate -m "Description of schema changes"

# Apply migrations to SQL Server
flask db upgrade
```
