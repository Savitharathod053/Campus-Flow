from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, session
from flask_migrate import Migrate
from config import Config
from models import db, User
from routes import auth_bp, public_bp, student_bp, organizer_bp, admin_bp, payment_bp, cert_bp

migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize Database and Migrations
    db.init_app(app)
    migrate.init_app(app, db)

    # Ensure Upload Directories Exist
    upload_dirs = [
        app.config['UPLOAD_FOLDER'],
        app.config['POSTER_FOLDER'],
        app.config['QRCODE_FOLDER'],
        app.config['CERTIFICATE_FOLDER']
    ]
    for d in upload_dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

    # Register Blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(organizer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(cert_bp)

    # Global Context Processor
    @app.context_processor
    def inject_global_vars():
        user = None
        user_id = session.get('user_id')
        if user_id:
            user = db.session.get(User, user_id)
        return {
            'current_user': user,
            'now': datetime.utcnow(),
            'app_name': 'FastFest'
        }

    # Custom Jinja Filters
    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%b %d, %Y - %I:%M %p'):
        if value is None:
            return ""
        return value.strftime(format)

    @app.template_filter('dateformat')
    def dateformat(value, format='%b %d, %Y'):
        if value is None:
            return ""
        return value.strftime(format)

    @app.template_filter('timeformat')
    def timeformat(value, format='%I:%M %p'):
        if value is None:
            return ""
        return value.strftime(format)

    # Error Handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('partials/404.html'), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('partials/403.html'), 403

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('partials/500.html'), 500

    # Auto create tables on initial startup if not using raw migration scripts
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning(f"Note: db.create_all() encountered: {e}")

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

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
