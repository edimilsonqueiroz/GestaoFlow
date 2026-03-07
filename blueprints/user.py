from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from extensions import db
from models import Task, TaskAction, TaskAttachment, Equipment, Reservation
from blueprints.utils import save_attachment, allowed_attachment

user_bp = Blueprint('user', __name__)

MAX_ATTACHMENTS_PER_ACTION = 5
MAX_FILE_MB = 10


@user_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin.dashboard'))

    now = datetime.now()
    # Expira reservas passadas
    expired = Reservation.query.filter(Reservation.status == 'confirmed').all()
    for r in expired:
        if datetime.combine(r.date, r.end_time) <= now:
            r.status = 'expired'
    db.session.commit()

    tasks = Task.query.filter_by(assigned_to=current_user.id).order_by(Task.created_at.desc()).all()
    stats = current_user.task_stats()

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
                None,
            )
            eq._status_now  = 'busy' if ongoing else 'free'
            eq._ongoing_res = ongoing

    return render_template('user/dashboard.html', tasks=tasks, stats=stats, equipments=equipments)


# ─── Detalhes + ações de uma tarefa ──────────────────────────────────────────

@user_bp.route('/tasks/<int:task_id>')
@login_required
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    if task.assigned_to != current_user.id and not current_user.is_admin:
        flash('Você não tem permissão para ver esta tarefa.', 'danger')
        return redirect(url_for('user.dashboard'))
    actions = (TaskAction.query
               .filter_by(task_id=task_id)
               .order_by(TaskAction.created_at.asc())
               .all())
    return render_template('user/task_detail.html', task=task, actions=actions)


@user_bp.route('/tasks/<int:task_id>/action', methods=['POST'])
@login_required
def add_task_action(task_id):
    """Registra uma ação (descrição + mudança de status + anexos) na tarefa."""
    task = Task.query.get_or_404(task_id)

    # Somente o responsável ou admin pode agir
    if task.assigned_to != current_user.id and not current_user.is_admin:
        flash('Sem permissão.', 'danger')
        return redirect(url_for('user.dashboard'))

    # Tarefa concluída: somente admin pode adicionar ações
    if task.status == 'done' and not current_user.is_admin:
        flash('Esta tarefa já foi concluída. Somente o administrador pode alterá-la.', 'warning')
        return redirect(url_for('user.task_detail', task_id=task_id))

    description = request.form.get('description', '').strip()
    new_status  = request.form.get('new_status', '').strip()
    files       = request.files.getlist('attachments')

    if not description:
        flash('A descrição da ação é obrigatória.', 'danger')
        return redirect(url_for('user.task_detail', task_id=task_id))

    # Valida novo status
    valid_statuses = ('pending', 'in_progress', 'done')
    if new_status not in valid_statuses:
        new_status = task.status  # mantém atual se inválido

    # Usuário comum não pode voltar de done
    old_status = task.status
    if old_status == 'done' and not current_user.is_admin:
        new_status = 'done'  # força manter

    # Cria a ação
    action = TaskAction(
        task_id=task_id,
        user_id=current_user.id,
        description=description,
        old_status=old_status,
        new_status=new_status,
    )
    db.session.add(action)
    db.session.flush()  # gera action.id antes de salvar anexos

    # Processa anexos
    errors = []
    saved  = 0
    for f in files:
        if not f or not f.filename:
            continue
        if saved >= MAX_ATTACHMENTS_PER_ACTION:
            errors.append(f'Limite de {MAX_ATTACHMENTS_PER_ACTION} anexos por ação atingido.')
            break
        # Verifica tamanho (lê stream)
        f.stream.seek(0, 2)
        size_mb = f.stream.tell() / (1024 * 1024)
        f.stream.seek(0)
        if size_mb > MAX_FILE_MB:
            errors.append(f'{f.filename}: arquivo maior que {MAX_FILE_MB} MB.')
            continue
        if not allowed_attachment(f.filename):
            errors.append(f'{f.filename}: tipo não permitido (use imagem ou PDF).')
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
            saved += 1
        except ValueError as e:
            errors.append(str(e))

    # Atualiza status da tarefa
    task.status     = new_status
    task.updated_at = datetime.utcnow()
    db.session.commit()

    if errors:
        for e in errors:
            flash(e, 'warning')
    flash('Ação registrada com sucesso!', 'success')
    return redirect(url_for('user.task_detail', task_id=task_id))


# ─── Update rápido via JSON (dashboard) ──────────────────────────────────────

@user_bp.route('/tasks/<int:task_id>/update-status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)

    if task.assigned_to != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403

    # Tarefa concluída: bloqueia para usuários comuns
    if task.status == 'done' and not current_user.is_admin:
        return jsonify({
            'error': 'done_locked',
            'message': 'Tarefa concluída. Acesse os detalhes para registrar ações.',
        }), 403

    new_status = request.json.get('status')
    if new_status not in ('pending', 'in_progress', 'done'):
        return jsonify({'error': 'Status inválido'}), 400

    old_status      = task.status
    task.status     = new_status
    task.updated_at = datetime.utcnow()

    # Registra log automático da mudança rápida
    action = TaskAction(
        task_id=task_id,
        user_id=current_user.id,
        description=f'Status alterado para "{task.status_label}" via painel.',
        old_status=old_status,
        new_status=new_status,
    )
    db.session.add(action)
    db.session.commit()

    return jsonify({
        'success':    True,
        'status':     new_status,
        'detail_url': url_for('user.task_detail', task_id=task_id),
    })


# ─── Perfil do usuário ────────────────────────────────────────────────────────

@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if current_user.is_admin:
        return redirect(url_for('admin.profile'))

    user = current_user

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm  = request.form.get('confirm_password', '').strip()

        # Validações básicas
        if not name or not email:
            flash('Nome e e-mail são obrigatórios.', 'danger')
            return render_template('user/profile.html', user=user)

        # E-mail já em uso por outro usuário
        from models import User
        existing = User.query.filter_by(email=email).first()
        if existing and existing.id != user.id:
            flash('Este e-mail já está em uso por outra conta.', 'danger')
            return render_template('user/profile.html', user=user)

        # Validação de senha (só se preenchida)
        if password:
            if len(password) < 6:
                flash('A nova senha deve ter no mínimo 6 caracteres.', 'danger')
                return render_template('user/profile.html', user=user)
            if password != confirm:
                flash('As senhas não coincidem.', 'danger')
                return render_template('user/profile.html', user=user)
            user.set_password(password)

        user.name  = name
        user.email = email
        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('user.profile'))

    return render_template('user/profile.html', user=user)