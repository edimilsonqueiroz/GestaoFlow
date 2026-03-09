from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from models import Equipment, Reservation, TimeSlot
from blueprints.utils import (
    allowed_file, save_photo, delete_photo,
    week_days, parse_date, parse_time,
    expire_past_reservations, admin_required_redirect,
)

equipment_bp = Blueprint('equipment', __name__)


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN — TimeSlot CRUD
# ════════════════════════════════════════════════════════════════════════════════

@equipment_bp.route('/admin/horarios')
@login_required
def admin_slots_list():
    redir = admin_required_redirect()
    if redir: return redir
    slots = TimeSlot.query.order_by(TimeSlot.start_time).all()
    return render_template('equipment/admin_slots_list.html', slots=slots)


@equipment_bp.route('/admin/horarios/novo', methods=['GET', 'POST'])
@login_required
def admin_slots_create():
    redir = admin_required_redirect()
    if redir: return redir
    if request.method == 'POST':
        desc  = request.form.get('description', '').strip()
        start = parse_time(request.form.get('start_time', ''))
        end   = parse_time(request.form.get('end_time', ''))
        errors = []
        if not desc:  errors.append('A descricao e obrigatoria.')
        if not start: errors.append('Horario de inicio invalido.')
        if not end:   errors.append('Horario de fim invalido.')
        if start and end and end <= start:
            errors.append('O horario de fim deve ser posterior ao de inicio.')
        if errors:
            for e in errors: flash(e, 'danger')
        else:
            exists = TimeSlot.query.filter_by(start_time=start, end_time=end).first()
            if exists:
                flash(f'Ja existe um horario para {start.strftime("%H:%M")}-{end.strftime("%H:%M")}.', 'danger')
            else:
                db.session.add(TimeSlot(description=desc, start_time=start, end_time=end))
                db.session.commit()
                flash(f'Horario "{desc}" cadastrado!', 'success')
                return redirect(url_for('equipment.admin_slots_list'))
    return render_template('equipment/admin_slots_form.html', slot=None)


@equipment_bp.route('/admin/horarios/<int:slot_id>/editar', methods=['GET', 'POST'])
@login_required
def admin_slots_edit(slot_id):
    redir = admin_required_redirect()
    if redir: return redir
    slot = TimeSlot.query.get_or_404(slot_id)
    if request.method == 'POST':
        desc  = request.form.get('description', '').strip()
        start = parse_time(request.form.get('start_time', ''))
        end   = parse_time(request.form.get('end_time', ''))
        errors = []
        if not desc:  errors.append('A descricao e obrigatoria.')
        if not start: errors.append('Horario de inicio invalido.')
        if not end:   errors.append('Horario de fim invalido.')
        if start and end and end <= start:
            errors.append('O horario de fim deve ser posterior ao de inicio.')
        if errors:
            for e in errors: flash(e, 'danger')
        else:
            slot.description = desc
            slot.start_time  = start
            slot.end_time    = end
            slot.is_active   = request.form.get('is_active') == 'on'
            db.session.commit()
            flash(f'Horario "{desc}" atualizado!', 'success')
            return redirect(url_for('equipment.admin_slots_list'))
    return render_template('equipment/admin_slots_form.html', slot=slot)


@equipment_bp.route('/admin/horarios/<int:slot_id>/excluir', methods=['POST'])
@login_required
def admin_slots_delete(slot_id):
    redir = admin_required_redirect()
    if redir: return redir
    slot   = TimeSlot.query.get_or_404(slot_id)
    future = [r for r in slot.reservations if r.date >= date.today() and r.status == 'confirmed']
    if future:
        flash(f'Nao e possivel excluir: "{slot.description}" tem {len(future)} reserva(s) ativa(s).', 'danger')
        return redirect(url_for('equipment.admin_slots_list'))
    desc = slot.description
    db.session.delete(slot)
    db.session.commit()
    flash(f'Horario "{desc}" excluido.', 'success')
    return redirect(url_for('equipment.admin_slots_list'))


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — catálogo
# ════════════════════════════════════════════════════════════════════════════════

@equipment_bp.route('/equipamentos')
@login_required
def index():
    expire_past_reservations(Reservation)
    equipments = Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all()
    today = date.today()
    now   = datetime.now()
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
    my_reservations = Reservation.query.filter(
        Reservation.user_id == current_user.id,
        Reservation.status  == 'confirmed',
        Reservation.date    >= today,
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template('equipment/index.html',
        equipments=equipments, my_reservations=my_reservations, today=today)


# ════════════════════════════════════════════════════════════════════════════════
# USUARIO — detalhe + reserva
# ════════════════════════════════════════════════════════════════════════════════

@equipment_bp.route('/equipamentos/<int:eq_id>')
@login_required
def detail(eq_id):
    expire_past_reservations(Reservation)
    eq        = Equipment.query.get_or_404(eq_id)
    ref       = parse_date(request.args.get('week')) or date.today()
    days      = week_days(ref)
    today     = date.today()
    all_slots = TimeSlot.query.filter_by(is_active=True).order_by(TimeSlot.start_time).all()
    now_time  = datetime.now().time()

    day_data = []
    for d in days:
        occupied_ids = eq.occupied_slot_ids_on(d) if d >= today and d.weekday() < 5 else set()
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
                    (r.user for r in eq.active_reservations_on(d) if any(s.id == ts.id for s in r.slots)),
                    None
                )
                state = 'occupied'
            else:
                state = 'free'
                owner = None
            slots_status.append({'slot': ts, 'state': state, 'owner': owner if state == 'occupied' else None})

        my_res_today = Reservation.query.filter(
            Reservation.equipment_id == eq_id,
            Reservation.user_id == current_user.id,
            Reservation.date    == d,
            Reservation.status  == 'confirmed',
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

    my_upcoming = Reservation.query.filter(
        Reservation.equipment_id == eq_id,
        Reservation.user_id == current_user.id,
        Reservation.status  == 'confirmed',
        Reservation.date    >= today,
    ).order_by(Reservation.date, Reservation.start_time).all()

    return render_template('equipment/detail.html',
        eq=eq, day_data=day_data, all_slots=all_slots,
        prev_week=(days[0] - timedelta(days=7)).isoformat(),
        next_week=(days[0] + timedelta(days=7)).isoformat(),
        today=today, my_upcoming=my_upcoming,
        week_ref=days[0].isoformat(),
        no_slots=len(all_slots) == 0,
    )


@equipment_bp.route('/equipamentos/reservar', methods=['POST'])
@login_required
def reserve():
    equipment_id = request.form.get('equipment_id', type=int)
    date_str     = request.form.get('date')
    slot_ids     = request.form.getlist('slot_ids', type=int)
    notes        = request.form.get('notes', '').strip()
    week_ref     = request.form.get('week_ref', '')
    eq           = Equipment.query.get_or_404(equipment_id)
    res_date     = parse_date(date_str)
    back_url     = url_for('equipment.detail', eq_id=equipment_id, week=week_ref)

    if not eq.is_active:
        flash('Este equipamento nao esta disponivel para reservas.', 'danger')
        return redirect(back_url)
    if not res_date:
        flash('Data invalida.', 'danger'); return redirect(back_url)
    if res_date.weekday() >= 5:
        flash('Reservas permitidas apenas de segunda a sexta-feira.', 'danger'); return redirect(back_url)
    if res_date < date.today():
        flash('Nao e possivel reservar uma data passada.', 'danger'); return redirect(back_url)
    if not slot_ids:
        flash('Selecione pelo menos um horario.', 'danger'); return redirect(back_url)

    slots = TimeSlot.query.filter(TimeSlot.id.in_(slot_ids), TimeSlot.is_active == True).all()
    if len(slots) != len(slot_ids):
        flash('Um ou mais horarios selecionados sao invalidos.', 'danger'); return redirect(back_url)

    slots.sort(key=lambda s: s.start_time)
    occupied_ids = eq.occupied_slot_ids_on(res_date)
    conflicting  = [s for s in slots if s.id in occupied_ids]
    if conflicting:
        nomes = ', '.join(f'"{s.description}"' for s in conflicting)
        flash(f'Os seguintes horarios ja estao reservados: {nomes}.', 'danger'); return redirect(back_url)

    start_t = slots[0].start_time
    end_t   = slots[-1].end_time

    if res_date == date.today() and datetime.combine(res_date, start_t) <= datetime.now():
        flash('O horario de inicio ja passou.', 'danger'); return redirect(back_url)

    reservation = Reservation(
        equipment_id=equipment_id, user_id=current_user.id,
        date=res_date, start_time=start_t, end_time=end_t,
        notes=notes, status='confirmed',
    )
    reservation.slots = slots
    db.session.add(reservation)
    db.session.commit()
    slot_names = ', '.join(s.description for s in slots)
    flash(f'"{eq.name}" reservado para {res_date.strftime("%d/%m/%Y")} - {slot_names}!', 'success')
    return redirect(back_url)


@equipment_bp.route('/equipamentos/reservas/<int:res_id>/cancelar', methods=['POST'])
@login_required
def cancel_reservation(res_id):
    res = Reservation.query.get_or_404(res_id)
    if res.user_id != current_user.id and not current_user.is_admin:
        flash('Sem permissao para cancelar esta reserva.', 'danger')
        return redirect(url_for('equipment.index'))
    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('Informe o motivo do cancelamento.', 'danger')
        return redirect(request.form.get('next') or url_for('equipment.index'))
    res.status = 'cancelled'
    res.notes  = (res.notes + ' ' if res.notes else '') + f'[Cancelado: {motivo}]'
    db.session.commit()
    flash('Reserva cancelada com sucesso.', 'success')
    return redirect(request.form.get('next') or url_for('equipment.index'))


@equipment_bp.route('/equipamentos/reservas/<int:res_id>/iniciar', methods=['POST'])
@login_required
def start_reservation(res_id):
    redir = admin_required_redirect()
    if redir: return redir
    res = Reservation.query.get_or_404(res_id)
    if res.status != 'confirmed':
        flash('Só é possível iniciar reservas confirmadas.', 'danger')
        return redirect(request.form.get('next') or url_for('equipment.admin_reservations'))
    res.status     = 'in_use'
    res.started_at = datetime.utcnow()
    db.session.commit()
    flash(f'Retirada registrada para {res.user.first_name} — {res.equipment.name}.', 'success')
    return redirect(request.form.get('next') or url_for('equipment.admin_reservations'))


@equipment_bp.route('/equipamentos/reservas/<int:res_id>/devolver', methods=['POST'])
@login_required
def return_reservation(res_id):
    redir = admin_required_redirect()
    if redir: return redir
    res = Reservation.query.get_or_404(res_id)
    if res.status != 'in_use':
        flash('Só é possível registrar devolução de reservas em uso.', 'danger')
        return redirect(request.form.get('next') or url_for('equipment.admin_reservations'))
    res.status      = 'returned'
    res.returned_at = datetime.utcnow()
    db.session.commit()
    flash(f'Devolução registrada — {res.equipment.name}.', 'success')
    return redirect(request.form.get('next') or url_for('equipment.admin_reservations'))


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN — Equipamentos CRUD
# ════════════════════════════════════════════════════════════════════════════════

@equipment_bp.route('/admin/equipamentos')
@login_required
def admin_list():
    redir = admin_required_redirect()
    if redir: return redir
    expire_past_reservations(Reservation)
    equipments = Equipment.query.order_by(Equipment.name).all()
    today = date.today()
    for eq in equipments:
        eq._upcoming = Reservation.query.filter(
            Reservation.equipment_id == eq.id,
            Reservation.date >= today,
            Reservation.status == 'confirmed'
        ).count()
    return render_template('equipment/admin_list.html', equipments=equipments)


@equipment_bp.route('/admin/equipamentos/novo', methods=['GET', 'POST'])
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
            photo = save_photo(file, 'equipment') if file and file.filename else None
            db.session.add(Equipment(
                name=name,
                category=request.form.get('category', 'outros'),
                description=request.form.get('description', '').strip(),
                photo=photo,
            ))
            db.session.commit()
            flash(f'Equipamento "{name}" cadastrado!', 'success')
            return redirect(url_for('equipment.admin_list'))
    return render_template('equipment/admin_form.html', equipment=None)


@equipment_bp.route('/admin/equipamentos/<int:eq_id>/editar', methods=['GET', 'POST'])
@login_required
def admin_edit(eq_id):
    redir = admin_required_redirect()
    if redir: return redir
    eq = Equipment.query.get_or_404(eq_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        file = request.files.get('photo')
        if not name:
            flash('O nome e obrigatorio.', 'danger')
            return render_template('equipment/admin_form.html', equipment=eq)
        if file and file.filename and not allowed_file(file.filename):
            flash('Formato invalido. Use JPG, PNG, WEBP ou GIF.', 'danger')
            return render_template('equipment/admin_form.html', equipment=eq)
        eq.name        = name
        eq.category    = request.form.get('category', 'outros')
        eq.description = request.form.get('description', '').strip()
        eq.is_active   = request.form.get('is_active') == 'on'
        if file and file.filename:
            delete_photo(eq.photo)
            eq.photo = save_photo(file, 'equipment')
        elif request.form.get('remove_photo') == '1':
            delete_photo(eq.photo)
            eq.photo = None
        db.session.commit()
        flash(f'"{eq.name}" atualizado!', 'success')
        return redirect(url_for('equipment.admin_list'))
    return render_template('equipment/admin_form.html', equipment=eq)


@equipment_bp.route('/admin/equipamentos/<int:eq_id>/excluir', methods=['POST'])
@login_required
def admin_delete(eq_id):
    redir = admin_required_redirect()
    if redir: return redir
    eq   = Equipment.query.get_or_404(eq_id)
    name = eq.name
    delete_photo(eq.photo)
    db.session.delete(eq)
    db.session.commit()
    flash(f'"{name}" excluido.', 'success')
    return redirect(url_for('equipment.admin_list'))


@equipment_bp.route('/admin/equipamentos/reservas')
@login_required
def admin_reservations():
    redir = admin_required_redirect()
    if redir: return redir
    expire_past_reservations(Reservation)
    ref  = parse_date(request.args.get('week')) or date.today()
    days = week_days(ref)
    reservations = Reservation.query.filter(
        Reservation.date >= days[0],
        Reservation.date <= days[4],
        Reservation.status.in_(['confirmed', 'in_use', 'returned']),
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template('equipment/admin_reservations.html',
        reservations=reservations, days=days,
        prev_week=(days[0] - timedelta(days=7)).isoformat(),
        next_week=(days[0] + timedelta(days=7)).isoformat(),
        today=date.today(),
    )