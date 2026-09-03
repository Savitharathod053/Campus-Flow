from datetime import datetime
from .user import db

class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    team_name = db.Column(db.String(100), nullable=False)
    team_lead_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(30), default='PENDING', nullable=False)
    payment_status = db.Column(db.String(30), default='PENDING', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    event = db.relationship('Event', backref=db.backref('teams', lazy='dynamic', cascade='all, delete-orphan'))
    lead = db.relationship('User', foreign_keys=[team_lead_id])
    members = db.relationship('TeamMember', back_populates='team', cascade='all, delete-orphan')
    invitations = db.relationship('TeamInvitation', back_populates='team', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Team {self.team_name} (Event:{self.event_id})>'


class TeamMember(db.Model):
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='MEMBER', nullable=False)
    status = db.Column(db.String(20), default='JOINED', nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    team = db.relationship('Team', back_populates='members')
    student = db.relationship('User', foreign_keys=[student_id])

    def __repr__(self):
        return f'<TeamMember Team:{self.team_id} Student:{self.student_id} ({self.role})>'


class TeamInvitation(db.Model):
    __tablename__ = 'team_invitations'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    invited_email = db.Column(db.String(150), nullable=False)
    invited_student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    token = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    team = db.relationship('Team', back_populates='invitations')
    event = db.relationship('Event')
    invited_student = db.relationship('User', foreign_keys=[invited_student_id])

    def __repr__(self):
        return f'<TeamInvitation Team:{self.team_id} Email:{self.invited_email} ({self.status})>'
