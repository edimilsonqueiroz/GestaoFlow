from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from extensions import db
from blueprints.utils import parse_date as _parse_date_util
from models import User, Task

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
    from datetime import date as _date
    total_users    = User.query.filter_by(role='user').count()
    total_tasks    = db.session.query(func.count(Task.id)).scalar()
    tasks_done     = db.session.query(func.count(Task.id)).filter_by(status='done').scalar()
    tasks_pending  = db.session.query(func.count(Task.id)).filter_by(status='pending').scalar()
    tasks_inprog   = db.session.query(func.count(Task.id)).filter_by(status='in_progress').scalar()
    tasks_overdue  = db.session.query(func.count(Task.id)).filter(
        Task.status   != 'done',
        Task.due_date <  _date.today(),
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
    return render_template('admin/dashboard.html', users=users, recent_tasks=recent, stats=stats)


# ─── Tasks ────────────────────────────────────────────────────────────────────

@admin_bp.route('/tasks')
@login_required
@admin_required
def tasks():
    all_tasks = Task.query.order_by(Task.created_at.desc()).all()
    users     = User.query.filter_by(role='user', is_active_account=True).all()
    return render_template('admin/tasks.html', tasks=all_tasks, users=users)


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
    return render_template('admin/task_form.html', users=users, task=task)


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
    pending = (User.query
               .filter_by(role='user', was_approved=False)
               .order_by(User.created_at.asc())
               .all())
    active_users = (User.query
                    .filter_by(role='user', was_approved=True)
                    .order_by(User.created_at.desc())
                    .all())
    return render_template('admin/users.html', pending=pending, users=active_users)


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