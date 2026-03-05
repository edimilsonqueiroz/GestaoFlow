from datetime import datetime, time
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Tabela associativa Reservation ↔ TimeSlot ────────────────────────────────
reservation_slots = db.Table(
    'reservation_slots',
    db.Column('reservation_id', db.Integer, db.ForeignKey('reservations.id', ondelete='CASCADE'), primary_key=True),
    db.Column('timeslot_id',    db.Integer, db.ForeignKey('timeslots.id',    ondelete='CASCADE'), primary_key=True),
)


# ─── User ─────────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id                = db.Column(db.Integer, primary_key=True)
    name              = db.Column(db.String(100), nullable=False)
    email             = db.Column(db.String(150), unique=True, nullable=False)
    password_hash     = db.Column(db.String(256), nullable=False)
    role              = db.Column(db.String(20), default='user', index=True)
    is_active_account = db.Column(db.Boolean, default=True, index=True)
    was_approved      = db.Column(db.Boolean, default=True)   # False = aguardando aprovação do admin
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    tasks         = db.relationship('Task', backref='assignee',  lazy=True, foreign_keys='Task.assigned_to')
    created_tasks = db.relationship('Task', backref='creator',   lazy=True, foreign_keys='Task.created_by')

    def set_password(self, pw):  self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

    @property
    def is_admin(self):   return self.role == 'admin'
    @property
    def initials(self):
        p = self.name.split()
        return (p[0][0] + p[-1][0]).upper() if len(p) > 1 else p[0][0].upper()
    @property
    def first_name(self): return self.name.split()[0]

    def task_stats(self):
        total = len(self.tasks)
        done  = sum(1 for t in self.tasks if t.status == 'done')
        ip    = sum(1 for t in self.tasks if t.status == 'in_progress')
        pend  = sum(1 for t in self.tasks if t.status == 'pending')
        return {'total': total, 'done': done, 'in_progress': ip, 'pending': pend,
                'progress': int(done / total * 100) if total else 0}

    def __repr__(self): return f'<User {self.email}>'


# ─── TimeSlot ─────────────────────────────────────────────────────────────────
class TimeSlot(db.Model):
    __tablename__ = 'timeslots'

    id          = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(100), nullable=False)   # ex: "Manhã", "1º Horário"
    start_time  = db.Column(db.Time, nullable=False)
    end_time    = db.Column(db.Time, nullable=False)
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def time_range(self):
        return f"{self.start_time.strftime('%H:%M')} – {self.end_time.strftime('%H:%M')}"

    @property
    def label(self):
        return f"{self.description} ({self.time_range})"

    @property
    def duration_minutes(self):
        from datetime import date
        s = datetime.combine(date.today(), self.start_time)
        e = datetime.combine(date.today(), self.end_time)
        return int((e - s).total_seconds() // 60)

    def __repr__(self): return f'<TimeSlot {self.id}: {self.label}>'


# ─── Equipment ────────────────────────────────────────────────────────────────
class Equipment(db.Model):
    __tablename__ = 'equipment'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    category    = db.Column(db.String(50), default='outros')
    description = db.Column(db.Text)
    photo       = db.Column(db.String(200))   # caminho relativo: uploads/equipment/nome.jpg
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    reservations = db.relationship('Reservation', backref='equipment', lazy=True, cascade='all, delete-orphan')

    @property
    def category_label(self):
        MAP = {
            'datashow':    '📽️ Datashow',
            'caixa_de_som':'🔊 Caixa de Som',
            'microfone':   '🎤 Microfone',
            'camera':      '📷 Câmera',
            'notebook':    '💻 Notebook',
            'tv':          '📺 TV / Monitor',
            'outros':      '📦 Outros',
        }
        return MAP.get(self.category, self.category.replace('_', ' ').title())

    @property
    def category_icon(self):
        MAP = {
            'datashow':    'fa-projector',
            'caixa_de_som':'fa-volume-up',
            'microfone':   'fa-microphone',
            'camera':      'fa-camera',
            'notebook':    'fa-laptop',
            'tv':          'fa-tv',
            'outros':      'fa-box',
        }
        return MAP.get(self.category, 'fa-box')

    def active_reservations_on(self, target_date):
        return Reservation.query.filter_by(
            equipment_id=self.id, date=target_date, status='confirmed'
        ).order_by(Reservation.start_time).all()

    def occupied_slot_ids_on(self, target_date):
        """Retorna set de timeslot_ids já reservados (confirmados) na data."""
        occupied = set()
        for res in self.active_reservations_on(target_date):
            for ts in res.slots:
                occupied.add(ts.id)
        return occupied

    def is_available_at(self, target_date, start_t, end_t):
        conflicts = Reservation.query.filter(
            Reservation.equipment_id == self.id,
            Reservation.date   == target_date,
            Reservation.status == 'confirmed',
            Reservation.start_time < end_t,
            Reservation.end_time   > start_t,
        ).first()
        return conflicts is None

    def __repr__(self): return f'<Equipment {self.id}: {self.name}>'


# ─── Reservation ──────────────────────────────────────────────────────────────
class Reservation(db.Model):
    __tablename__ = 'reservations'

    id           = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'),     nullable=False)
    date         = db.Column(db.Date,    nullable=False, index=True)
    start_time   = db.Column(db.Time,    nullable=False)   # min(slots.start_time)
    end_time     = db.Column(db.Time,    nullable=False)   # max(slots.end_time)
    notes        = db.Column(db.String(300))
    status       = db.Column(db.String(20), default='confirmed', index=True)  # confirmed|cancelled|expired
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user  = db.relationship('User', backref='reservations', lazy=True)
    slots = db.relationship('TimeSlot', secondary=reservation_slots, lazy='subquery',
                            backref=db.backref('reservations', lazy=True))

    @property
    def start_datetime(self): return datetime.combine(self.date, self.start_time)
    @property
    def end_datetime(self):   return datetime.combine(self.date, self.end_time)
    @property
    def time_range(self):     return f"{self.start_time.strftime('%H:%M')} – {self.end_time.strftime('%H:%M')}"
    @property
    def is_ongoing(self):
        now = datetime.now()
        return self.status == 'confirmed' and self.start_datetime <= now < self.end_datetime
    @property
    def weekday_label(self):
        return ['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'][self.date.weekday()]
    @property
    def period_label(self):
        h = self.start_time.hour
        return '🌅 Manhã' if h < 12 else ('🌇 Tarde' if h < 18 else '🌃 Noite')
    @property
    def slots_label(self):
        return ', '.join(s.description for s in sorted(self.slots, key=lambda x: x.start_time))

    def __repr__(self): return f'<Reservation {self.id}: {self.date} {self.time_range}>'


# ─── Tabela associativa LabReservation ↔ TimeSlot ────────────────────────────
lab_reservation_slots = db.Table(
    'lab_reservation_slots',
    db.Column('lab_reservation_id', db.Integer, db.ForeignKey('lab_reservations.id', ondelete='CASCADE'), primary_key=True),
    db.Column('timeslot_id',        db.Integer, db.ForeignKey('timeslots.id',         ondelete='CASCADE'), primary_key=True),
)


# ─── Lab ──────────────────────────────────────────────────────────────────────
class Lab(db.Model):
    __tablename__ = 'labs'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    location    = db.Column(db.String(100))          # bloco / sala / andar
    capacity    = db.Column(db.Integer, default=0)   # nº de computadores / lugares
    description = db.Column(db.Text)
    photo       = db.Column(db.String(200))          # uploads/labs/nome.jpg
    is_active   = db.Column(db.Boolean, default=True, index=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    reservations = db.relationship('LabReservation', backref='lab', lazy=True,
                                   cascade='all, delete-orphan')

    def active_reservations_on(self, target_date):
        return LabReservation.query.filter_by(
            lab_id=self.id, date=target_date, status='confirmed'
        ).order_by(LabReservation.start_time).all()

    def occupied_slot_ids_on(self, target_date):
        occupied = set()
        for res in self.active_reservations_on(target_date):
            for ts in res.slots:
                occupied.add(ts.id)
        return occupied

    def __repr__(self): return f'<Lab {self.id}: {self.name}>'


# ─── LabReservation ───────────────────────────────────────────────────────────
class LabReservation(db.Model):
    __tablename__ = 'lab_reservations'

    id         = db.Column(db.Integer, primary_key=True)
    lab_id     = db.Column(db.Integer, db.ForeignKey('labs.id'),   nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    date       = db.Column(db.Date,    nullable=False, index=True)
    start_time = db.Column(db.Time,    nullable=False)
    end_time   = db.Column(db.Time,    nullable=False)
    notes      = db.Column(db.String(300))
    status     = db.Column(db.String(20), default='confirmed', index=True)  # confirmed|cancelled|expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user  = db.relationship('User', backref='lab_reservations', lazy=True)
    slots = db.relationship('TimeSlot', secondary=lab_reservation_slots,
                            lazy='subquery',
                            backref=db.backref('lab_reservations', lazy=True))

    @property
    def start_datetime(self): return datetime.combine(self.date, self.start_time)
    @property
    def end_datetime(self):   return datetime.combine(self.date, self.end_time)
    @property
    def time_range(self):     return f"{self.start_time.strftime('%H:%M')} – {self.end_time.strftime('%H:%M')}"
    @property
    def is_ongoing(self):
        now = datetime.now()
        return self.status == 'confirmed' and self.start_datetime <= now < self.end_datetime
    @property
    def weekday_label(self):
        return ['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo'][self.date.weekday()]
    @property
    def period_label(self):
        h = self.start_time.hour
        return '🌅 Manhã' if h < 12 else ('🌇 Tarde' if h < 18 else '🌃 Noite')
    @property
    def slots_label(self):
        return ', '.join(s.description for s in sorted(self.slots, key=lambda x: x.start_time))

    def __repr__(self): return f'<LabReservation {self.id}: {self.date} {self.time_range}>'


# ─── Task ─────────────────────────────────────────────────────────────────────
class Task(db.Model):
    __tablename__ = 'tasks'

    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status      = db.Column(db.String(20), default='pending', index=True)
    priority    = db.Column(db.String(20), default='medium', index=True)
    due_date    = db.Column(db.Date)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    @property
    def is_overdue(self):
        return bool(self.due_date and self.status != 'done' and self.due_date < datetime.utcnow().date())
    @property
    def status_label(self):
        return {'pending':'Pendente','in_progress':'Em Andamento','done':'Concluída'}.get(self.status, self.status)
    @property
    def priority_label(self):
        return {'low':'Baixa','medium':'Média','high':'Alta','urgent':'Urgente'}.get(self.priority, self.priority)
    def __repr__(self): return f'<Task {self.id}: {self.title}>'