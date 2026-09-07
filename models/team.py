from datetime import datetime, timedelta
import secrets
from .user import db

class TeamStatus:
    PENDING = 'PENDING'
    COMPLETE = 'COMPLETE'
    FULL = 'FULL'
    CANCELLED = 'CANCELLED'

    CHOICES = [PENDING, COMPLETE, FULL, CANCELLED]


class TeamPaymentStatus:
    NOT_REQUIRED = 'NOT_REQUIRED'
    PENDING = 'PENDING'
    PAID = 'PAID'
    FAILED = 'FAILED'
    REFUNDED = 'REFUNDED'

    CHOICES = [NOT_REQUIRED, PENDING, PAID, FAILED, REFUNDED]


class TeamRole:
    TEAM_LEAD = 'TEAM_LEAD'
    MEMBER = 'MEMBER'

    CHOICES = [TEAM_LEAD, MEMBER]


class TeamMemberStatus:
    PENDING = 'PENDING'
    CONFIRMED = 'CONFIRMED'
    DECLINED = 'DECLINED'
    REMOVED = 'REMOVED'

    CHOICES = [PENDING, CONFIRMED, DECLINED, REMOVED]


class InvitationStatus:
    PENDING = 'PENDING'
    ACCEPTED = 'ACCEPTED'
    DECLINED = 'DECLINED'
    EXPIRED = 'EXPIRED'
    CANCELLED = 'CANCELLED'

    CHOICES = [PENDING, ACCEPTED, DECLINED, EXPIRED, CANCELLED]


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    team_name = db.Column(db.String(100), nullable=False)
    team_lead_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    status = db.Column(db.String(30), default=TeamStatus.PENDING, nullable=False, index=True)
    payment_status = db.Column(db.String(30), default=TeamPaymentStatus.NOT_REQUIRED, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    event = db.relationship('Event', back_populates='teams')
    lead = db.relationship('User', foreign_keys=[team_lead_id])
    members = db.relationship('TeamMember', back_populates='team', cascade='all, delete-orphan')
    invitations = db.relationship('TeamInvitation', back_populates='team', cascade='all, delete-orphan')
    registrations = db.relationship('EventRegistration', back_populates='team')
    payments = db.relationship('Payment', back_populates='team', cascade='all, delete-orphan')

    @property
    def confirmed_members(self):
        return [m for m in self.members if m.status == TeamMemberStatus.CONFIRMED]

    @property
    def pending_members(self):
        return [m for m in self.members if m.status == TeamMemberStatus.PENDING]

    @property
    def declined_members(self):
        return [m for m in self.members if m.status == TeamMemberStatus.DECLINED]

    @property
    def total_confirmed_count(self):
        return len(self.confirmed_members)

    @property
    def is_complete(self):
        if not self.event:
            return False
        return self.total_confirmed_count >= (self.event.min_team_size or 1)

    @property
    def is_full(self):
        if not self.event:
            return False
        return self.total_confirmed_count >= (self.event.max_team_size or 4)

    @property
    def can_invite_more(self):
        if not self.event:
            return False
        active_pending_invites = [i for i in self.invitations if i.is_active]
        return (self.total_confirmed_count + len(active_pending_invites)) < self.event.max_team_size

    @property
    def is_paid(self):
        if not self.event or self.event.is_free or (self.event.registration_fee or 0) == 0:
            return True
        if getattr(self.event, 'team_payment_type', None) == 'FREE':
            return True
        if self.payment_status in ['PAID', 'SUCCESS']:
            return True
        if any(p.status in ['SUCCESS', 'PAID', 'COMPLETED'] for p in self.payments):
            return True
        # For PER_PERSON model, if all confirmed members have valid paid/confirmed registrations
        if getattr(self.event, 'team_payment_type', None) == 'PER_PERSON':
            confirmed_members = self.confirmed_members
            if confirmed_members:
                paid_count = 0
                for m in confirmed_members:
                    r = next((reg for reg in self.registrations if reg.student_id == m.student_id), None)
                    if r and (r.is_confirmed or (r.payment and r.payment.status in ['SUCCESS', 'PAID', 'COMPLETED'])):
                        paid_count += 1
                if paid_count == len(confirmed_members):
                    return True
        return False

    @property
    def payment_status_display(self):
        if not self.event or self.event.is_free or (self.event.registration_fee or 0) == 0 or getattr(self.event, 'team_payment_type', None) == 'FREE':
            return 'FREE'
        if self.payment_status in ['PAID', 'SUCCESS'] or self.is_paid:
            return 'PAID'
        if self.payment_status == 'REFUNDED':
            return 'REFUNDED'
        if self.payment_status == 'FAILED':
            return 'FAILED'
        return 'PENDING'

    def recalculate_status(self):
        """Updates team status according to event min/max team sizing rules."""
        if self.status == TeamStatus.CANCELLED:
            return self.status

        confirmed_count = self.total_confirmed_count
        max_size = self.event.max_team_size if self.event else 4
        min_size = self.event.min_team_size if self.event else 2

        if confirmed_count >= max_size:
            self.status = TeamStatus.FULL
        elif confirmed_count >= min_size:
            self.status = TeamStatus.COMPLETE
        else:
            self.status = TeamStatus.PENDING
            
        return self.status

    def __repr__(self):
        return f'<Team {self.team_name} (Event {self.event_id}) - {self.status}>'


class TeamMember(db.Model):
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default=TeamRole.MEMBER, nullable=False)
    status = db.Column(db.String(20), default=TeamMemberStatus.PENDING, nullable=False, index=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('team_id', 'student_id', name='uq_team_student_member'),
    )

    team = db.relationship('Team', back_populates='members')
    student = db.relationship('User', foreign_keys=[student_id])

    @property
    def is_lead(self):
        return self.role == TeamRole.TEAM_LEAD

    @property
    def is_confirmed(self):
        return self.status == TeamMemberStatus.CONFIRMED

    def __repr__(self):
        return f'<TeamMember Team:{self.team_id} Student:{self.student_id} Role:{self.role} Status:{self.status}>'


class TeamInvitation(db.Model):
    __tablename__ = 'team_invitations'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    invited_email = db.Column(db.String(150), nullable=False, index=True)
    invited_student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    token = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default=InvitationStatus.PENDING, nullable=False, index=True)
    
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    team = db.relationship('Team', back_populates='invitations')
    event = db.relationship('Event')
    invited_student = db.relationship('User', foreign_keys=[invited_student_id])

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    @property
    def is_active(self):
        if self.status != InvitationStatus.PENDING:
            return False
        if self.is_expired:
            return False
        return True

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)

    @classmethod
    def create_invitation(cls, team_id, event_id, email, student_id=None, valid_days=3):
        return cls(
            team_id=team_id,
            event_id=event_id,
            invited_email=email.strip().lower(),
            invited_student_id=student_id,
            token=cls.generate_token(),
            status=InvitationStatus.PENDING,
            expires_at=datetime.utcnow() + timedelta(days=valid_days)
        )

    def __repr__(self):
        return f'<TeamInvitation Team:{self.team_id} Email:{self.invited_email} Status:{self.status}>'
