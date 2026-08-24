from flask import Blueprint, render_template, abort
from models import Certificate

cert_bp = Blueprint('certificates', __name__, url_prefix='/certificate')

@cert_bp.route('/verify/<certificate_code>')
def verify(certificate_code):
    clean_code = certificate_code.replace('FASTFEST-CERT-VERIFY:', '').strip()
    cert = Certificate.query.filter_by(certificate_code=clean_code).first()

    if not cert:
        return render_template('certificates/verify_result.html', is_valid=False, certificate_code=clean_code), 404

    return render_template('certificates/verify_result.html', is_valid=True, cert=cert)
