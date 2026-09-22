import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, session, jsonify
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from models import db, User
from routes import (
    auth_bp, public_bp, student_bp, organizer_bp,
    admin_bp, payment_bp, cert_bp, faculty_bp, hod_bp, dean_bp
)
from services.notification_service import get_unread_count, get_user_notifications, mark_as_read, mark_all_as_read

migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Reverse proxy support for Render / Cloudflare (ensures correct HTTPS redirects and secure cookies)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Enable Cross-Origin Resource Sharing with credentials support if available
    try:
        from flask_cors import CORS
        CORS(app, supports_credentials=True)
    except ImportError:
        pass

    # Initialize Database and Migrations
    db.init_app(app)
    migrate.init_app(app, db)

    # Ensure Upload Directories Exist
    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        app.config['POSTER_FOLDER'],
        app.config['QRCODE_FOLDER'],
        app.config['CERTIFICATE_FOLDER'],
        app.config.get('PAYMENT_PROOF_FOLDER'),
        app.config.get('ORGANIZER_QR_FOLDER')
    ]
    for d in upload_dirs:
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)

    # Register Blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(organizer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(cert_bp)
    app.register_blueprint(faculty_bp)
    app.register_blueprint(hod_bp)
    app.register_blueprint(dean_bp)

    # Razorpay Webhook Global API Endpoint
    from routes.payment import handle_razorpay_webhook
    app.add_url_rule('/api/payments/webhook/razorpay', 'api_razorpay_webhook', handle_razorpay_webhook, methods=['POST'])

    # Health Check Endpoints
    @app.route('/health')
    def health():
        return jsonify({"status": "healthy"}), 200

    @app.route('/health/db')
    def health_db():
        from services.db_diagnostic import get_safe_db_info
        info = get_safe_db_info()
        status_code = 200 if info.get('connected') else 503
        return jsonify({
            "status": "connected" if info.get('connected') else "disconnected",
            "dialect": info.get('dialect'),
            "database": info.get('database'),
            "server": info.get('server')
        }), status_code

    # Pre-request schema assurance (idempotent, ensures tables exist on first request)
    @app.before_request
    def ensure_database_ready():
        from flask import request
        if request.endpoint == 'static':
            return
        from services.db_init import ensure_db_initialized
        try:
            ensure_db_initialized(app)
        except Exception as e:
            app.logger.warning(f"Database readiness check note: {e}")


    # Notification API Endpoints
    @app.route('/notifications/read/<int:notification_id>', methods=['POST'])
    def read_notification(notification_id):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        success = mark_as_read(notification_id, user_id=user_id)
        return jsonify({'success': success})

    @app.route('/notifications/read-all', methods=['POST'])
    def read_all_notifications():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        success = mark_all_as_read(user_id)
        return jsonify({'success': success})

    @app.route('/faculty/dashboard')
    def faculty_dashboard():
        from flask import redirect, url_for
        return redirect(url_for('admin.dashboard'))

    # Global Context Processor
    @app.context_processor
    def inject_global_vars():
        user = None
        unread_notifications_count = 0
        recent_notifications = []
        user_id = session.get('user_id')
        if user_id:
            try:
                user = db.session.get(User, user_id)
                if not user:
                    session.pop('user_id', None)
                else:
                    unread_notifications_count = get_unread_count(user.id)
                    recent_notifications = get_user_notifications(user.id, limit=6)
            except Exception as e:
                app.logger.error(f"Database error in inject_global_vars for user_id {user_id}: {e}", exc_info=True)
                user = None
        return {
            'current_user': user,
            'unread_notifications_count': unread_notifications_count,
            'recent_notifications': recent_notifications,
            'now': datetime.utcnow(),
            'app_name': 'Campus Flow'
        }

    # Custom Jinja Filters (All timestamps rendered in Indian Standard Time Asia/Kolkata)
    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%b %d, %Y - %I:%M %p'):
        if value is None:
            return ""
        from services.timezone_service import to_ist
        if isinstance(value, datetime):
            value = to_ist(value)
        elif isinstance(value, str):
            dt_conv = to_ist(value)
            if dt_conv:
                value = dt_conv
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)

    @app.template_filter('dateformat')
    def dateformat(value, format='%b %d, %Y'):
        if value is None:
            return ""
        from services.timezone_service import to_ist
        if isinstance(value, datetime):
            value = to_ist(value)
        elif isinstance(value, str):
            dt_conv = to_ist(value)
            if dt_conv:
                value = dt_conv
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)

    @app.template_filter('timeformat')
    def timeformat(value, format='%I:%M %p'):
        if value is None:
            return ""
        from services.timezone_service import to_ist
        if isinstance(value, datetime):
            value = to_ist(value)
        elif isinstance(value, str):
            dt_conv = to_ist(value)
            if dt_conv:
                value = dt_conv
        if hasattr(value, 'strftime'):
            return value.strftime(format)
        return str(value)

    # Error Handlers
    @app.errorhandler(400)
    def bad_request_error(error):
        return render_template('partials/400.html'), 400

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('partials/404.html'), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('partials/403.html'), 403

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        try:
            db.session.rollback()
        except Exception as rb_err:
            app.logger.warning(f"Rollback failed during 500 error handling: {rb_err}")
        try:
            return render_template('partials/500.html'), 500
        except Exception as render_err:
            app.logger.error(f"Secondary error rendering 500.html: {render_err}", exc_info=True)
            return (
                "<!DOCTYPE html><html><head><title>500 - Internal Server Error</title></head>"
                "<body style='font-family:sans-serif;text-align:center;padding:50px;'>"
                "<h1>500 - Internal Server Error</h1>"
                "<p>A database or server error occurred. Please contact your system administrator.</p>"
                "</body></html>",
                500
            )

    with app.app_context():
        try:
            from services.db_init import init_db_and_seed
            init_db_and_seed(app)
        except Exception as e:
            app.logger.warning(f"Note: Automatic database initialization encountered: {e}")

    # CLI Command to initialize and seed database
    @app.cli.command("init-db")
    def init_db_cli():
        """Initialize all tables and baseline users in the database."""
        from services.db_init import init_db_and_seed
        success = init_db_and_seed(app)
        if success:
            print("[SUCCESS] Database initialization and seeding completed successfully.")
        else:
            print("[FAILURE] Database initialization encountered an error.")

    # CLI Command to delete expired events
    @app.cli.command("delete-expired-events")
    def delete_expired_events_cli():
        """Delete all events whose end date has passed and all certificates were issued."""
        from services.event_service import delete_expired_events
        count, deleted_titles, skipped_titles = delete_expired_events(require_certificates_done=True)
        if count > 0:
            print(f"Deleted {count} expired event(s) (all certificates issued):")
            for t in deleted_titles:
                print(f" - {t}")
        else:
            print("No eligible expired events deleted.")

        if skipped_titles:
            print(f"Retained {len(skipped_titles)} event(s) because certificate submission to students is still pending:")
            for s in skipped_titles:
                print(f" - {s}")

    # CLI Command to inspect database connection and schema health
    @app.cli.command("check-db")
    def check_db_cli():
        """Run database connectivity and schema diagnostics."""
        from services.db_diagnostic import run_db_diagnostic
        run_db_diagnostic(app)

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0' if (os.environ.get('PORT') or os.environ.get('RENDER')) else '127.0.0.1'
    app.run(host=host, port=port, debug=False)

