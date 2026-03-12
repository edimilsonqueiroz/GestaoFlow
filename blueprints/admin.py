from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from blueprints.utils import parse_date as _parse_date_util
from models import User, Task, TaskAction, TaskAttachment, Reservation
from blueprints.emails import send_account_rejected, send_task_assigned, send_new_user_pending

admin_bp = Blueprint('admin', __name__)


# ─── Guard ────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acesso negado. Área restrita a administradores.', 'danger')
            return redirect(url_for('user.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ─── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    from datetime import date as _date, timedelta as _td
    import json as _json

    today = _date.today()
    total_users    = User.query.filter_by(role='user').count()
    total_tasks    = db.session.query(func.count(Task.id)).scalar()
    tasks_done     = db.session.query(func.count(Task.id)).filter_by(status='done').scalar()
    tasks_pending  = db.session.query(func.count(Task.id)).filter_by(status='pending').scalar()
    tasks_inprog   = db.session.query(func.count(Task.id)).filter_by(status='in_progress').scalar()
    tasks_overdue  = db.session.query(func.count(Task.id)).filter(
        Task.status   != 'done',
        Task.due_date <  today,
        Task.due_date.isnot(None),
    ).scalar()
    pending_approval = User.query.filter_by(role='user', was_approved=False).count()
    recent = Task.query.order_by(Task.created_at.desc()).limit(8).all()
    users  = User.query.filter_by(role='user').order_by(User.name).all()
    stats  = {
        'total_users':      total_users,
        'total_tasks':      total_tasks,
        'tasks_done':       tasks_done,
        'tasks_pending':    tasks_pending,
        'tasks_inprogress': tasks_inprog,
        'tasks_overdue':    tasks_overdue,
        'pending_approval': pending_approval,
    }

    # ── Dados para gráfico: tarefas criadas nos últimos 8 dias ───────────────
    days_labels, days_created, days_done_list = [], [], []
    for i in range(7, -1, -1):
        d = today - _td(days=i)
        days_labels.append(d.strftime('%d/%m'))
        days_created.append(
            db.session.query(func.count(Task.id))
            .filter(func.date(Task.created_at) == d).scalar() or 0
        )
        days_done_list.append(
            db.session.query(func.count(Task.id))
            .filter(Task.status == 'done', func.date(Task.updated_at) == d).scalar() or 0
        )

    chart_data = _json.dumps({
        'labels':  days_labels,
        'created': days_created,
        'done':    days_done_list,
    })

    unassigned = Task.query.filter(
        Task.assigned_to.is_(None),
        Task.status != 'done'
    ).order_by(Task.created_at.desc()).all()

    # ── Gráfico de reservas por dia da semana ─────────────────────────────────
    from models import LabReservation
    from blueprints.utils import week_days as _week_days, parse_date as _parse_date_util2

    _DIAS_PT = ['Segunda','Terça','Quarta','Quinta','Sexta']

    res_week_ref = request.args.get('res_week')
    res_ref      = _parse_date_util2(res_week_ref) or today
    res_days     = _week_days(res_ref)   # lista de 5 dates (seg–sex)
    monday_this  = today - _td(days=today.weekday())

    # Seletor: semana atual + 4 anteriores
    week_options = []
    for i in range(4, -1, -1):
        mon = monday_this - _td(weeks=i)
        fri = mon + _td(days=4)
        week_options.append({
            'value': mon.isoformat(),
            'label': f"{mon.strftime('%d/%m')} – {fri.strftime('%d/%m/%Y')}",
        })

    # Contagem por dia — equipamentos e laboratórios separados
    res_labels       = []
    res_equip_counts = []
    res_lab_counts   = []
    active = ['confirmed', 'in_use', 'returned']

    for d in res_days:
        res_labels.append(f"{_DIAS_PT[d.weekday()]}\n{d.strftime('%d/%m')}")
        res_equip_counts.append(
            Reservation.query.filter(Reservation.date == d,
                                     Reservation.status.in_(active)).count()
        )
        res_lab_counts.append(
            LabReservation.query.filter(LabReservation.date == d,
                                        LabReservation.status.in_(active)).count()
        )

    monday_iso = res_days[0].isoformat()
    equip_chart_data = _json.dumps({
        'labels':       res_labels,
        'equipamentos': res_equip_counts,
        'laboratorios': res_lab_counts,
        'week_label':   f"{res_days[0].strftime('%d/%m')} – {res_days[4].strftime('%d/%m/%Y')}",
    })

    return render_template('admin/dashboard.html',
        users=users, recent_tasks=recent, stats=stats,
        chart_data=chart_data, unassigned_tasks=unassigned,
        equip_chart_data=equip_chart_data,
        equip_has_data=True,
        res_week_ref=monday_iso,
        week_options=week_options,
        prev_week=(res_days[0] - _td(weeks=1)).isoformat(),
        next_week=(res_days[0] + _td(weeks=1)).isoformat(),
        is_current_week=(res_days[0] == monday_this))


# ─── Tasks ────────────────────────────────────────────────────────────────────

@admin_bp.route('/tasks')
@login_required
@admin_required
def tasks():
    page       = request.args.get('page', 1, type=int)
    per_page   = 20
    q          = request.args.get('q', '').strip()
    f_status   = request.args.get('status', '')
    f_priority = request.args.get('priority', '')
    f_user     = request.args.get('user_id', '', type=str)

    query = Task.query
    if q:
        query = query.filter(Task.title.ilike(f'%{q}%'))
    if f_status:
        query = query.filter(Task.status == f_status)
    if f_priority:
        query = query.filter(Task.priority == f_priority)
    if f_user:
        query = query.filter(Task.assigned_to == int(f_user))

    pagination = query.order_by(Task.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    users      = User.query.filter_by(role='user', is_active_account=True).order_by(User.name).all()
    return render_template('admin/tasks.html',
        tasks=pagination.items, pagination=pagination,
        users=users, q=q, f_status=f_status, f_priority=f_priority, f_user=f_user)


@admin_bp.route('/tasks/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_task():
    users = User.query.filter_by(role='user', is_active_account=True).all()
    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority    = request.form.get('priority', 'medium')
        assigned_to = request.form.get('assigned_to') or None
        due_date    = _parse_date_util(request.form.get('due_date'))
        if not title:
            flash('O título da tarefa é obrigatório.', 'danger')
        else:
            task = Task(
                title=title,
                description=description,
                priority=priority,
                assigned_to=int(assigned_to) if assigned_to else None,
                due_date=due_date,
                created_by=current_user.id,
            )
            db.session.add(task)
            db.session.commit()
            if task.assigned_to and task.assignee:
                send_task_assigned(task, task.assignee)
            flash('Tarefa criada com sucesso!', 'success')
            return redirect(url_for('admin.tasks'))
    return render_template('admin/task_form.html', users=users, task=None)


@admin_bp.route('/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_task(task_id):
    task  = Task.query.get_or_404(task_id)
    users = User.query.filter_by(role='user', is_active_account=True).all()
    if request.method == 'POST':
        task.title       = request.form.get('title', '').strip()
        task.description = request.form.get('description', '').strip()
        task.priority    = request.form.get('priority', 'medium')
        task.status      = request.form.get('status', 'pending')
        assigned_to      = request.form.get('assigned_to')
        task.assigned_to = int(assigned_to) if assigned_to else None
        task.due_date    = _parse_date_util(request.form.get('due_date'))
        task.updated_at  = datetime.utcnow()
        db.session.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
        return redirect(url_for('admin.tasks'))
    actions = (TaskAction.query
               .filter_by(task_id=task_id)
               .order_by(TaskAction.created_at.asc())
               .all())
    return render_template('admin/task_form.html', users=users, task=task, actions=actions)




@admin_bp.route('/tasks/<int:task_id>/action', methods=['POST'])
@login_required
@admin_required
def add_task_action_admin(task_id):
    """Admin pode registrar ação em qualquer tarefa, mesmo concluída."""
    from blueprints.utils import save_attachment, allowed_attachment
    task = Task.query.get_or_404(task_id)

    description = request.form.get('description', '').strip()
    new_status  = request.form.get('new_status', task.status).strip()
    files       = request.files.getlist('attachments')

    if not description:
        flash('A descrição da ação é obrigatória.', 'danger')
        return redirect(url_for('admin.edit_task', task_id=task_id))

    if new_status not in ('pending', 'in_progress', 'done'):
        new_status = task.status

    old_status  = task.status
    action = TaskAction(
        task_id=task_id,
        user_id=current_user.id,
        description=description,
        old_status=old_status,
        new_status=new_status,
    )
    db.session.add(action)
    db.session.flush()

    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_attachment(f.filename):
            flash(f'{f.filename}: tipo não permitido.', 'warning')
            continue
        try:
            info = save_attachment(f, task_id)
            att  = TaskAttachment(
                action_id=action.id,
                filename=info['filename'],
                filepath=info['filepath'],
                filetype=info['filetype'],
            )
            db.session.add(att)
        except ValueError as e:
            flash(str(e), 'warning')

    task.status     = new_status
    task.updated_at = datetime.utcnow()
    db.session.commit()
    flash('Ação registrada com sucesso!', 'success')
    return redirect(url_for('admin.edit_task', task_id=task_id))

@admin_bp.route('/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash('Tarefa removida com sucesso.', 'success')
    return redirect(url_for('admin.tasks'))


# ─── Users ────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    page     = request.args.get('page', 1, type=int)
    per_page = 20
    q        = request.args.get('q', '').strip()
    f_status = request.args.get('status', '')   # 'active' | 'inactive' | ''

    pending = (User.query
               .filter_by(role='user', was_approved=False)
               .order_by(User.created_at.asc())
               .all())

    uq = User.query.filter_by(role='user', was_approved=True)
    if q:
        uq = uq.filter(User.name.ilike(f'%{q}%') | User.email.ilike(f'%{q}%'))
    if f_status == 'active':
        uq = uq.filter_by(is_active_account=True)
    elif f_status == 'inactive':
        uq = uq.filter_by(is_active_account=False)

    pagination = uq.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/users.html',
        pending=pending, users=pagination.items,
        pagination=pagination, q=q, f_status=f_status)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_account = not user.is_active_account
    db.session.commit()
    status = 'ativado' if user.is_active_account else 'desativado'
    flash(f'Usuário {user.name} foi {status}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_account = True
    user.was_approved       = True
    db.session.commit()
    flash(f'Acesso de {user.name} aprovado com sucesso!', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_user(user_id):
    """Rejeita cadastro pendente e remove o usuário."""
    user = User.query.get_or_404(user_id)
    if user.was_approved:
        flash('Este usuário já foi aprovado anteriormente.', 'danger')
        return redirect(url_for('admin.users'))
    name = user.name
    send_account_rejected(user)
    db.session.delete(user)
    db.session.commit()
    flash(f'Cadastro de {name} rejeitado e removido.', 'info')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    Task.query.filter_by(assigned_to=user_id).update({'assigned_to': None})
    db.session.delete(user)
    db.session.commit()
    flash(f'Usuário {user.name} foi removido.', 'success')
    return redirect(url_for('admin.users'))


# ─── Admin Profile ────────────────────────────────────────────────────────────

@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@admin_required
def profile():
    user = current_user

    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        email   = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm  = request.form.get('confirm_password', '').strip()

        if not name or not email:
            flash('Nome e e-mail são obrigatórios.', 'danger')
            return render_template('admin/profile.html', user=user)

        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user.id:
            flash('Este e-mail já está sendo usado por outro usuário.', 'danger')
            return render_template('admin/profile.html', user=user)

        user.name  = name
        user.email = email

        if password:
            if password != confirm:
                flash('As senhas não coincidem.', 'danger')
                return render_template('admin/profile.html', user=user)
            if len(password) < 6:
                flash('A nova senha deve ter no mínimo 6 caracteres.', 'danger')
                return render_template('admin/profile.html', user=user)
            user.set_password(password)
            flash('Perfil atualizado e senha redefinida com sucesso!', 'success')
        else:
            flash('Perfil atualizado com sucesso!', 'success')

        db.session.commit()
        return redirect(url_for('admin.profile'))

    return render_template('admin/profile.html', user=user)




# ─── User Create / Edit ───────────────────────────────────────────────────────

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        role     = request.form.get('role', 'user')

        if not name or not email or not password:
            flash('Preencha todos os campos obrigatórios.', 'danger')
        elif password != confirm:
            flash('As senhas não coincidem.', 'danger')
        elif len(password) < 6:
            flash('A senha deve ter no mínimo 6 caracteres.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Este e-mail já está em uso.', 'danger')
        else:
            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'Usuário {name} cadastrado com sucesso!', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        email   = request.form.get('email', '').strip().lower()
        role    = request.form.get('role', user.role)
        password = request.form.get('password', '').strip()
        confirm  = request.form.get('confirm_password', '').strip()

        if not name or not email:
            flash('Nome e e-mail são obrigatórios.', 'danger')
            return render_template('admin/user_form.html', user=user)

        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user_id:
            flash('Este e-mail já está sendo usado por outro usuário.', 'danger')
            return render_template('admin/user_form.html', user=user)

        user.name  = name
        user.email = email
        user.role  = role

        if password:
            if password != confirm:
                flash('As senhas não coincidem.', 'danger')
                return render_template('admin/user_form.html', user=user)
            if len(password) < 6:
                flash('A nova senha deve ter no mínimo 6 caracteres.', 'danger')
                return render_template('admin/user_form.html', user=user)
            user.set_password(password)
            flash(f'Usuário {name} atualizado e senha redefinida!', 'success')
        else:
            flash(f'Dados de {name} atualizados com sucesso!', 'success')

        db.session.commit()
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=user)