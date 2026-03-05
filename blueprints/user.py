from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Task, Equipment, Reservation

user_bp = Blueprint('user', __name__)


@user_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin.dashboard'))

    # Expirar reservas passadas
    now = datetime.now()
    expired = Reservation.query.filter(Reservation.status == 'confirmed').all()
    for r in expired:
        if datetime.combine(r.date, r.end_time) <= now:
            r.status = 'expired'
    db.session.commit()

    tasks  = Task.query.filter_by(assigned_to=current_user.id).order_by(Task.created_at.desc()).all()
    stats  = current_user.task_stats()

    # Equipamentos ativos com status atual
    equipments = Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all()
    today = date.today()
    for eq in equipments:
        if today.weekday() >= 5:
            eq._status_now  = 'weekend'
            eq._ongoing_res = None
        else:
            ongoing = next(
                (r for r in eq.active_reservations_on(today)
                 if datetime.combine(r.date, r.start_time) <= now < datetime.combine(r.date, r.end_time)),
                None
            )
            eq._status_now  = 'busy' if ongoing else 'free'
            eq._ongoing_res = ongoing

    return render_template('user/dashboard.html', tasks=tasks, stats=stats, equipments=equipments)


@user_bp.route('/tasks/<int:task_id>/update-status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    if task.assigned_to != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    status = request.json.get('status')
    if status not in ('pending', 'in_progress', 'done'):
        return jsonify({'error': 'Status inválido'}), 400
    task.status     = status
    task.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'status': status})