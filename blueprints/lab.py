from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from models import Lab, LabReservation, TimeSlot
from blueprints.utils import (
    allowed_file, save_photo, delete_photo,
    week_days, parse_date,
    expire_past_reservations, admin_required_redirect,
)

lab_bp = Blueprint('lab', __name__)


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — catálogo de laboratórios
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/laboratorios')
@login_required
def index():
    expire_past_reservations(LabReservation)
    labs  = Lab.query.filter_by(is_active=True).order_by(Lab.name).all()
    today = date.today()
    now   = datetime.now()
    for lab in labs:
        if today.weekday() >= 5:
            lab._status_now  = 'weekend'
            lab._ongoing_res = None
        else:
            ongoing = next(
                (r for r in lab.active_reservations_on(today)
                 if datetime.combine(r.date, r.start_time) <= now < datetime.combine(r.date, r.end_time)),
                None
            )
            lab._status_now  = 'busy' if ongoing else 'free'
            lab._ongoing_res = ongoing
    my_reservations = LabReservation.query.filter(
        LabReservation.user_id == current_user.id,
        LabReservation.status  == 'confirmed',
        LabReservation.date    >= today,
    ).order_by(LabReservation.date, LabReservation.start_time).all()
    return render_template('lab/index.html',
        labs=labs, my_reservations=my_reservations, today=today)


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — detalhe + grade de reservas
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/laboratorios/<int:lab_id>')
@login_required
def detail(lab_id):
    expire_past_reservations(LabReservation)
    lab       = Lab.query.get_or_404(lab_id)
    ref       = parse_date(request.args.get('week')) or date.today()
    days      = week_days(ref)
    today     = date.today()
    all_slots = TimeSlot.query.filter_by(is_active=True).order_by(TimeSlot.start_time).all()
    now_time  = datetime.now().time()

    day_data = []
    for d in days:
        occupied_ids = lab.occupied_slot_ids_on(d) if d >= today and d.weekday() < 5 else set()
        slots_status = []
        for ts in all_slots:
            if d < today or d.weekday() >= 5:
                state = 'past'
                owner = None
            elif d == today and ts.end_time <= now_time:
                state = 'past_today'
                owner = None
            elif ts.id in occupied_ids:
                owner = next(
                    (r.user for r in lab.active_reservations_on(d)
                     if any(s.id == ts.id for s in r.slots)),
                    None
                )
                state = 'occupied'
            else:
                state = 'free'
                owner = None
            slots_status.append({'slot': ts, 'state': state,
                                  'owner': owner if state == 'occupied' else None})

        my_res_today = LabReservation.query.filter(
            LabReservation.lab_id  == lab_id,
            LabReservation.user_id == current_user.id,
            LabReservation.date    == d,
            LabReservation.status  == 'confirmed',
        ).all()

        day_data.append({
            'date':            d,
            'is_today':        d == today,
            'is_past':         d < today,
            'is_weekend':      d.weekday() >= 5,
            'slots_status':    slots_status,
            'free_count':      sum(1 for s in slots_status if s['state'] == 'free'),
            'my_reservations': my_res_today,
        })

    my_upcoming = LabReservation.query.filter(
        LabReservation.lab_id  == lab_id,
        LabReservation.user_id == current_user.id,
        LabReservation.status  == 'confirmed',
        LabReservation.date    >= today,
    ).order_by(LabReservation.date, LabReservation.start_time).all()

    return render_template('lab/detail.html',
        lab=lab, day_data=day_data, all_slots=all_slots,
        prev_week=(days[0] - timedelta(days=7)).isoformat(),
        next_week=(days[0] + timedelta(days=7)).isoformat(),
        today=today, my_upcoming=my_upcoming,
        week_ref=days[0].isoformat(),
        no_slots=len(all_slots) == 0,
    )


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — efetuar reserva
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/laboratorios/reservar', methods=['POST'])
@login_required
def reserve():
    lab_id   = request.form.get('lab_id', type=int)
    date_str = request.form.get('date')
    slot_ids = request.form.getlist('slot_ids', type=int)
    notes    = request.form.get('notes', '').strip()
    week_ref = request.form.get('week_ref', '')
    lab      = Lab.query.get_or_404(lab_id)
    res_date = parse_date(date_str)
    back_url = url_for('lab.detail', lab_id=lab_id, week=week_ref)

    if not lab.is_active:
        flash('Este laboratorio nao esta disponivel para reservas.', 'danger')
        return redirect(back_url)
    if not res_date:
        flash('Data invalida.', 'danger'); return redirect(back_url)
    if res_date.weekday() >= 5:
        flash('Reservas permitidas apenas de segunda a sexta-feira.', 'danger'); return redirect(back_url)
    if res_date < date.today():
        flash('Nao e possivel reservar uma data passada.', 'danger'); return redirect(back_url)
    if not slot_ids:
        flash('Selecione pelo menos um horario.', 'danger'); return redirect(back_url)

    slots = TimeSlot.query.filter(
        TimeSlot.id.in_(slot_ids), TimeSlot.is_active == True
    ).all()
    if len(slots) != len(slot_ids):
        flash('Um ou mais horarios selecionados sao invalidos.', 'danger'); return redirect(back_url)

    slots.sort(key=lambda s: s.start_time)
    occupied_ids = lab.occupied_slot_ids_on(res_date)
    conflicting  = [s for s in slots if s.id in occupied_ids]
    if conflicting:
        nomes = ', '.join(f'"{s.description}"' for s in conflicting)
        flash(f'Os seguintes horarios ja estao reservados: {nomes}.', 'danger'); return redirect(back_url)

    start_t = slots[0].start_time
    end_t   = slots[-1].end_time

    if res_date == date.today() and datetime.combine(res_date, start_t) <= datetime.now():
        flash('O horario de inicio ja passou.', 'danger'); return redirect(back_url)

    reservation = LabReservation(
        lab_id=lab_id, user_id=current_user.id,
        date=res_date, start_time=start_t, end_time=end_t,
        notes=notes, status='confirmed',
    )
    reservation.slots = slots
    db.session.add(reservation)
    db.session.commit()
    slot_names = ', '.join(s.description for s in slots)
    flash(f'"{lab.name}" reservado para {res_date.strftime("%d/%m/%Y")} - {slot_names}!', 'success')
    return redirect(back_url)


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — cancelar reserva
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/laboratorios/reservas/<int:res_id>/cancelar', methods=['POST'])
@login_required
def cancel_reservation(res_id):
    res = LabReservation.query.get_or_404(res_id)
    if res.user_id != current_user.id and not current_user.is_admin:
        flash('Sem permissao para cancelar esta reserva.', 'danger')
        return redirect(url_for('lab.index'))
    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('Informe o motivo do cancelamento.', 'danger')
        return redirect(request.form.get('next') or url_for('lab.index'))
    res.status = 'cancelled'
    res.notes  = (res.notes + ' ' if res.notes else '') + f'[Cancelado: {motivo}]'
    db.session.commit()
    flash('Reserva cancelada com sucesso.', 'success')
    return redirect(request.form.get('next') or url_for('lab.index'))


@lab_bp.route('/laboratorios/reservas/<int:res_id>/iniciar', methods=['POST'])
@login_required
def start_reservation(res_id):
    redir = admin_required_redirect()
    if redir: return redir
    res = LabReservation.query.get_or_404(res_id)
    if res.status != 'confirmed':
        flash('Só é possível iniciar reservas confirmadas.', 'danger')
        return redirect(request.form.get('next') or url_for('lab.admin_reservations'))
    res.status     = 'in_use'
    res.started_at = datetime.utcnow()
    db.session.commit()
    flash(f'Retirada registrada para {res.user.first_name} — {res.lab.name}.', 'success')
    return redirect(request.form.get('next') or url_for('lab.admin_reservations'))


@lab_bp.route('/laboratorios/reservas/<int:res_id>/devolver', methods=['POST'])
@login_required
def return_reservation(res_id):
    redir = admin_required_redirect()
    if redir: return redir
    res = LabReservation.query.get_or_404(res_id)
    if res.status != 'in_use':
        flash('Só é possível registrar devolução de reservas em uso.', 'danger')
        return redirect(request.form.get('next') or url_for('lab.admin_reservations'))
    res.status      = 'returned'
    res.returned_at = datetime.utcnow()
    db.session.commit()
    flash(f'Devolução registrada — {res.lab.name}.', 'success')
    return redirect(request.form.get('next') or url_for('lab.admin_reservations'))


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN — laboratórios CRUD
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/admin/laboratorios')
@login_required
def admin_list():
    redir = admin_required_redirect()
    if redir: return redir
    expire_past_reservations(LabReservation)
    labs  = Lab.query.order_by(Lab.name).all()
    today = date.today()
    for lab in labs:
        lab._upcoming = LabReservation.query.filter(
            LabReservation.lab_id == lab.id,
            LabReservation.date   >= today,
            LabReservation.status == 'confirmed'
        ).count()
    return render_template('lab/admin_list.html', labs=labs)


@lab_bp.route('/admin/laboratorios/novo', methods=['GET', 'POST'])
@login_required
def admin_create():
    redir = admin_required_redirect()
    if redir: return redir
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        file = request.files.get('photo')
        if not name:
            flash('O nome e obrigatorio.', 'danger')
        elif file and file.filename and not allowed_file(file.filename):
            flash('Formato invalido. Use JPG, PNG, WEBP ou GIF.', 'danger')
        else:
            photo = save_photo(file, 'labs') if file and file.filename else None
            cap   = request.form.get('capacity', '0').strip()
            db.session.add(Lab(
                name=name,
                location=request.form.get('location', '').strip(),
                capacity=int(cap) if cap.isdigit() else 0,
                description=request.form.get('description', '').strip(),
                photo=photo,
            ))
            db.session.commit()
            flash(f'Laboratorio "{name}" cadastrado!', 'success')
            return redirect(url_for('lab.admin_list'))
    return render_template('lab/admin_form.html', lab=None)


@lab_bp.route('/admin/laboratorios/<int:lab_id>/editar', methods=['GET', 'POST'])
@login_required
def admin_edit(lab_id):
    redir = admin_required_redirect()
    if redir: return redir
    lab = Lab.query.get_or_404(lab_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        file = request.files.get('photo')
        if not name:
            flash('O nome e obrigatorio.', 'danger')
            return render_template('lab/admin_form.html', lab=lab)
        if file and file.filename and not allowed_file(file.filename):
            flash('Formato invalido. Use JPG, PNG, WEBP ou GIF.', 'danger')
            return render_template('lab/admin_form.html', lab=lab)
        cap = request.form.get('capacity', '0').strip()
        lab.name        = name
        lab.location    = request.form.get('location', '').strip()
        lab.capacity    = int(cap) if cap.isdigit() else 0
        lab.description = request.form.get('description', '').strip()
        lab.is_active   = request.form.get('is_active') == 'on'
        if file and file.filename:
            delete_photo(lab.photo)
            lab.photo = save_photo(file, 'labs')
        elif request.form.get('remove_photo') == '1':
            delete_photo(lab.photo)
            lab.photo = None
        db.session.commit()
        flash(f'"{lab.name}" atualizado!', 'success')
        return redirect(url_for('lab.admin_list'))
    return render_template('lab/admin_form.html', lab=lab)


@lab_bp.route('/admin/laboratorios/<int:lab_id>/excluir', methods=['POST'])
@login_required
def admin_delete(lab_id):
    redir = admin_required_redirect()
    if redir: return redir
    lab  = Lab.query.get_or_404(lab_id)
    name = lab.name
    delete_photo(lab.photo)
    db.session.delete(lab)
    db.session.commit()
    flash(f'"{name}" excluido.', 'success')
    return redirect(url_for('lab.admin_list'))


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN — reservas (visão semanal)
# ════════════════════════════════════════════════════════════════════════════════

@lab_bp.route('/admin/laboratorios/reservas')
@login_required
def admin_reservations():
    redir = admin_required_redirect()
    if redir: return redir
    expire_past_reservations(LabReservation)
    ref  = parse_date(request.args.get('week')) or date.today()
    days = week_days(ref)
    reservations = LabReservation.query.filter(
        LabReservation.date   >= days[0],
        LabReservation.date   <= days[4],
        LabReservation.status.in_(['confirmed', 'in_use', 'returned']),
    ).order_by(LabReservation.date, LabReservation.start_time).all()
    return render_template('lab/admin_reservations.html',
        reservations=reservations, days=days,
        prev_week=(days[0] - timedelta(days=7)).isoformat(),
        next_week=(days[0] + timedelta(days=7)).isoformat(),
        today=date.today(),
    )