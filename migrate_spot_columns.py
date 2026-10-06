from app import create_app, db
from sqlalchemy import inspect, text

app = create_app()
with app.app_context():
    insp = inspect(db.engine)
    ev_cols = [c['name'] for c in insp.get_columns('events')]
    reg_cols = [c['name'] for c in insp.get_columns('event_registrations')]
    
    with db.engine.connect() as conn:
        if 'spot_registration_slots' not in ev_cols:
            print('Adding spot_registration_slots to events...')
            conn.execute(text('ALTER TABLE events ADD spot_registration_slots INT NOT NULL DEFAULT 0'))
        if 'spot_registration_closed' not in ev_cols:
            print('Adding spot_registration_closed to events...')
            conn.execute(text('ALTER TABLE events ADD spot_registration_closed BIT NOT NULL DEFAULT 0'))
        if 'spot_empty_slot_notification_sent' not in ev_cols:
            print('Adding spot_empty_slot_notification_sent to events...')
            conn.execute(text('ALTER TABLE events ADD spot_empty_slot_notification_sent BIT NOT NULL DEFAULT 0'))
        if 'registration_type' not in reg_cols:
            print('Adding registration_type to event_registrations...')
            conn.execute(text("ALTER TABLE event_registrations ADD registration_type VARCHAR(20) NOT NULL DEFAULT 'ONLINE'"))
        conn.commit()
    print('DB schema migration check completed successfully!')
