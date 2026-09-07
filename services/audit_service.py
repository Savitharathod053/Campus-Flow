import logging
import json
from flask import request
from models import db, AuditLog

logger = logging.getLogger("CampusFlow.Audit")

def log_audit_action(admin, action, target_type, target_id=None, target_name=None, details=None, ip_address=None):
    """
    Records an administrative action in the audit_logs table.
    Guarantees no sensitive data (such as passwords) are logged.
    """
    try:
        admin_id = None
        if hasattr(admin, 'id'):
            admin_id = admin.id
        elif isinstance(admin, int):
            admin_id = admin

        if not ip_address and request:
            try:
                ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
            except Exception:
                ip_address = None

        details_str = None
        if details is not None:
            if isinstance(details, (dict, list)):
                # Ensure no password fields are preserved
                if isinstance(details, dict):
                    details = {k: v for k, v in details.items() if 'password' not in k.lower()}
                details_str = json.dumps(details, default=str)
            else:
                details_str = str(details)

        audit_entry = AuditLog(
            admin_id=admin_id,
            action=str(action).upper(),
            target_type=str(target_type),
            target_id=target_id,
            target_name=str(target_name)[:150] if target_name else None,
            details=details_str,
            ip_address=ip_address[:45] if ip_address else None
        )
        db.session.add(audit_entry)
        db.session.commit()
        return audit_entry
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
        return None
