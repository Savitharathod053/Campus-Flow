web: python migrate_production_schema.py && gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120
