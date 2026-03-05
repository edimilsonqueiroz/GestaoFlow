from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response
from flask_login import login_required, current_user
from blueprints.utils import parse_date as _parse_date_util, admin_required_redirect
from models import User, Task, Reservation, LabReservation, Lab

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Frame, PageTemplate, BaseDocTemplate
)
from reportlab.platypus.flowables import Flowable

reports_bp = Blueprint('reports', __name__)

# ── Paleta ────────────────────────────────────────────────────────────────────
C_ACCENT   = colors.HexColor('#6c63ff')
C_ACCENT2  = colors.HexColor('#4f46e5')
C_DARK     = colors.HexColor('#0f172a')
C_GRAY     = colors.HexColor('#64748b')
C_LGRAY    = colors.HexColor('#94a3b8')
C_LIGHT    = colors.HexColor('#f8fafc')
C_LIGHT2   = colors.HexColor('#f1f5f9')
C_BORDER   = colors.HexColor('#e2e8f0')
C_GREEN    = colors.HexColor('#10b981')
C_GREEN_BG = colors.HexColor('#d1fae5')
C_RED      = colors.HexColor('#ef4444')
C_RED_BG   = colors.HexColor('#fee2e2')
C_YELLOW   = colors.HexColor('#f59e0b')
C_YEL_BG   = colors.HexColor('#fef3c7')
C_BLUE     = colors.HexColor('#3b82f6')
C_BLUE_BG  = colors.HexColor('#dbeafe')
C_WHITE    = colors.white

W, H = A4
MG   = 1.8 * cm   # margem


# ── Helpers ───────────────────────────────────────────────────────────────────


def _period_str(date_from, date_to):
    if date_from and date_to:
        return f"{date_from.strftime('%d/%m/%Y')} a {date_to.strftime('%d/%m/%Y')}"
    elif date_from:
        return f"A partir de {date_from.strftime('%d/%m/%Y')}"
    elif date_to:
        return f"Ate {date_to.strftime('%d/%m/%Y')}"
    return "Todos os registros"


# ── Estilos ───────────────────────────────────────────────────────────────────
def _st():
    return {
        'rpt_title':   ParagraphStyle('rpt_title',   fontName='Helvetica-Bold', fontSize=24,
                                      textColor=C_WHITE, leading=28, spaceAfter=0),
        'rpt_sub':     ParagraphStyle('rpt_sub',     fontName='Helvetica',      fontSize=10,
                                      textColor=colors.HexColor('#c4b5fd'), spaceAfter=0),
        'rpt_meta':    ParagraphStyle('rpt_meta',    fontName='Helvetica',      fontSize=8,
                                      textColor=C_GRAY, leading=13),
        'rpt_section': ParagraphStyle('rpt_section', fontName='Helvetica-Bold', fontSize=11,
                                      textColor=C_DARK, spaceBefore=14, spaceAfter=5),
        'rpt_th':      ParagraphStyle('rpt_th',      fontName='Helvetica-Bold', fontSize=8,
                                      textColor=C_WHITE, alignment=TA_LEFT),
        'rpt_td':      ParagraphStyle('rpt_td',      fontName='Helvetica',      fontSize=8,
                                      textColor=C_DARK, leading=11),
        'rpt_tag':     ParagraphStyle('rpt_tag',     fontName='Helvetica-Bold', fontSize=7,
                                      alignment=TA_CENTER, leading=9),
    }


# ── Bloco colorido no cabeçalho ───────────────────────────────────────────────
class HeaderBand(Flowable):
    """Faixa roxa no topo com titulo e subtitulo."""
    def __init__(self, title, subtitle, width):
        super().__init__()
        self.title    = title
        self.subtitle = subtitle
        self._width   = width
        self.height   = 2.4 * cm

    def draw(self):
        c = self.canv
        # Fundo
        c.setFillColor(C_ACCENT)
        c.roundRect(0, 0, self._width, self.height, 6, fill=1, stroke=0)
        # Faixa escura lateral esquerda
        c.setFillColor(C_ACCENT2)
        c.rect(0, 0, 6, self.height, fill=1, stroke=0)
        # Titulo
        c.setFont('Helvetica-Bold', 20)
        c.setFillColor(C_WHITE)
        c.drawString(16, self.height - 0.85*cm, self.title)
        # Subtitulo
        c.setFont('Helvetica', 9)
        c.setFillColor(colors.HexColor('#c4b5fd'))
        c.drawString(16, 0.45*cm, self.subtitle)


# ── Card de metadados ─────────────────────────────────────────────────────────
class MetaCard(Flowable):
    """Card cinza claro com periodo, usuario e emissao."""
    def __init__(self, lines, width):
        super().__init__()
        self._width = width
        self.lines  = lines          # lista de (label, valor)
        self.height = 1.0 * cm

    def draw(self):
        c = self.canv
        c.setFillColor(C_LIGHT2)
        c.roundRect(0, 0, self._width, self.height, 4, fill=1, stroke=0)
        c.setStrokeColor(C_BORDER)
        c.roundRect(0, 0, self._width, self.height, 4, fill=0, stroke=1)

        x = 10
        y = (self.height - 8) / 2
        col_w = (self._width - 20) / len(self.lines)
        for label, value in self.lines:
            c.setFont('Helvetica-Bold', 6.5)
            c.setFillColor(C_LGRAY)
            c.drawString(x, y + 9, label.upper())
            c.setFont('Helvetica', 8)
            c.setFillColor(C_DARK)
            # trunca se muito longo
            txt = value if len(value) <= 22 else value[:20] + '...'
            c.drawString(x, y, txt)
            x += col_w


# ── Rodape com paginacao ──────────────────────────────────────────────────────
def _on_page(canvas, doc):
    canvas.saveState()
    W_pg, _ = A4
    y = MG * 0.5
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MG, y + 10, W_pg - MG, y + 10)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(C_LGRAY)
    canvas.drawString(MG, y, f"TaskFlow v2 — Emitido em {datetime.now().strftime('%d/%m/%Y as %H:%M')} por {current_user.name}")
    canvas.drawRightString(W_pg - MG, y, f"Pagina {doc.page}")
    canvas.restoreState()


# ── Tabela de resumo (cards de totais) ────────────────────────────────────────
def _kpi_table(items, page_w):
    """items = [(label, valor, cor_texto, cor_bg), ...]"""
    n    = len(items)
    colw = (page_w - 2 * MG) / n
    header_row = [[item[0] for item in items]]
    value_row  = [[str(item[1]) for item in items]]
    data = header_row + value_row
    # rowHeights fixos: label=20pt, valor=44pt — evita que fonte 20pt extrapole
    tbl  = Table(data, colWidths=[colw] * n, rowHeights=[20, 44])
    style = [
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  7),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  C_GRAY),
        ('FONTNAME',      (0, 1), (-1, 1),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 1), (-1, 1),  20),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, 0),  4),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  4),
        ('TOPPADDING',    (0, 1), (-1, 1),  10),
        ('BOTTOMPADDING', (0, 1), (-1, 1),  10),
        ('LINEBELOW',     (0, 0), (-1, 0),  0.5, C_BORDER),
        ('BOX',           (0, 0), (-1, -1), 0.5, C_BORDER),
    ]
    for i, item in enumerate(items):
        style += [
            ('BACKGROUND', (i, 0), (i, -1), item[3]),
            ('TEXTCOLOR',  (i, 1), (i,  1), item[2]),
        ]
        if i > 0:
            style.append(('LINEBEFORE', (i, 0), (i, -1), 0.5, C_BORDER))
    tbl.setStyle(TableStyle(style))
    return tbl


# ── Tag colorida (pill) ───────────────────────────────────────────────────────
def _pill(text, bg, fg):
    return Table([[text]], colWidths=[1.6*cm])


def _badge(text, fg, bg):
    """Retorna uma mini-tabela com fundo colorido simulando badge."""
    style = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('TEXTCOLOR',     (0, 0), (-1, -1), fg),
        ('FONTNAME',      (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 7),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('ROUNDEDCORNERS', [3]),
    ])
    t = Table([[text]], colWidths=[1.5*cm])
    t.setStyle(style)
    return t


# ── Tabela de dados principal ─────────────────────────────────────────────────
def _main_table_style(n_rows=0):
    """n_rows = número de linhas de dados (sem header). Aplica zebra sem ROWBACKGROUNDS."""
    style = [
        ('BACKGROUND',    (0, 0), (-1,  0), C_DARK),
        ('TEXTCOLOR',     (0, 0), (-1,  0), C_WHITE),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1,  0), 8),
        ('TOPPADDING',    (0, 0), (-1,  0), 8),
        ('BOTTOMPADDING', (0, 0), (-1,  0), 8),
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 8),
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW',     (0, 0), (-1, -1), 0.3, C_BORDER),
        ('LEFTPADDING',   (0, 0), (-1, -1), 7),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('TOPPADDING',    (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]
    # Zebra manual por linha (não conflita com BACKGROUND de célula individual)
    for i in range(1, n_rows + 1):
        bg = C_WHITE if i % 2 == 1 else C_LIGHT
        style.append(('BACKGROUND', (0, i), (-1, i), bg))
    return style


def _build_pdf(title, subtitle, meta_lines, story_fn):
    """Monta e retorna um BytesIO com o PDF completo."""
    buf = BytesIO()
    cw  = W - 2 * MG
    st  = _st()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MG, rightMargin=MG,
        topMargin=MG, bottomMargin=MG * 1.4,
        onPage=_on_page,
    )

    story = []

    # 1. Faixa de cabecalho
    story.append(HeaderBand(title, subtitle, cw))
    story.append(Spacer(1, 6))

    # 2. Card de metadados
    story.append(MetaCard(meta_lines, cw))
    story.append(Spacer(1, 14))

    # 3. Conteudo especifico do relatorio
    story_fn(story, st, cw)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════════
# TELA — formulario
# ════════════════════════════════════════════════════════════════════════════════

@reports_bp.route('/admin/relatorios')
@login_required
def index():
    redir = admin_required_redirect()
    if redir: return redir
    users = User.query.filter_by(is_active_account=True).order_by(User.name).all()
    return render_template('reports/index.html', users=users)


# ════════════════════════════════════════════════════════════════════════════════
# PDF — RESERVAS
# ════════════════════════════════════════════════════════════════════════════════

@reports_bp.route('/admin/relatorios/reservas.pdf')
@login_required
def reservations_pdf():
    redir = admin_required_redirect()
    if redir: return redir

    date_from = _parse_date_util(request.args.get('date_from'))
    date_to   = _parse_date_util(request.args.get('date_to'))
    user_id   = request.args.get('user_id', type=int)
    status    = request.args.get('status', 'all')

    q = Reservation.query
    if date_from: q = q.filter(Reservation.date >= date_from)
    if date_to:   q = q.filter(Reservation.date <= date_to)
    if user_id:   q = q.filter(Reservation.user_id == user_id)
    if status != 'all': q = q.filter(Reservation.status == status)
    data = q.order_by(Reservation.date, Reservation.start_time).all()

    # Bloqueia se vazio
    if not data:
        flash('Nenhuma reserva encontrada para os filtros selecionados. Ajuste o periodo ou os filtros.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total     = len(data)
    confirmed = sum(1 for r in data if r.status == 'confirmed')
    cancelled = sum(1 for r in data if r.status == 'cancelled')
    expired   = sum(1 for r in data if r.status == 'expired')

    meta = [
        ('Periodo',   _period_str(date_from, date_to)),
        ('Usuario',   user_name or 'Todos'),
        ('Status',    {'all':'Todos','confirmed':'Confirmadas','cancelled':'Canceladas','expired':'Expiradas'}.get(status, status)),
        ('Emitido em', datetime.now().strftime('%d/%m/%Y %H:%M')),
        ('Emitido por', current_user.name),
    ]

    STATUS_LBL   = {'confirmed': 'Confirmada', 'cancelled': 'Cancelada', 'expired': 'Expirada'}
    STATUS_BADGE = {
        'confirmed': (C_GREEN,  C_GREEN_BG),
        'cancelled': (C_RED,    C_RED_BG),
        'expired':   (C_LGRAY,  C_LIGHT2),
    }

    def build_story(story, st, cw):
        # KPIs
        story.append(_kpi_table([
            ('Total',       total,     C_DARK,   C_WHITE),
            ('Confirmadas', confirmed, C_GREEN,  C_GREEN_BG),
            ('Canceladas',  cancelled, C_RED,    C_RED_BG),
            ('Expiradas',   expired,   C_LGRAY,  C_LIGHT2),
        ], W))
        story.append(Spacer(1, 14))

        # Cabecalho secao
        story.append(KeepTogether([
            Paragraph(f'Listagem de Reservas <font color="#94a3b8" size="9">({total} registros)</font>', st['rpt_section']),
        ]))

        cols = [cw*0.11, cw*0.23, cw*0.20, cw*0.12, cw*0.22, cw*0.12]
        rows = [['Data', 'Equipamento', 'Usuario', 'Horario', 'Slots', 'Status']]
        for r in data:
            slots = r.slots_label if r.slots else f"{r.start_time.strftime('%H:%M')}-{r.end_time.strftime('%H:%M')}"
            rows.append([
                r.date.strftime('%d/%m/%Y'),
                Paragraph((r.equipment.name if r.equipment else '-')[:34], st['rpt_td']),
                Paragraph((r.user.name      if r.user      else '-')[:28], st['rpt_td']),
                f"{r.start_time.strftime('%H:%M')}-{r.end_time.strftime('%H:%M')}",
                Paragraph(slots[:40], st['rpt_td']),
                STATUS_LBL.get(r.status, r.status),
            ])

        tbl   = Table(rows, colWidths=cols, repeatRows=1)
        style = _main_table_style(len(data))
        STATUS_FG = {'confirmed': C_GREEN, 'cancelled': C_RED,    'expired': C_LGRAY}
        STATUS_BG = {'confirmed': C_GREEN_BG, 'cancelled': C_RED_BG, 'expired': C_LIGHT2}
        for i, r in enumerate(data, start=1):
            fg = STATUS_FG.get(r.status, C_LGRAY)
            bg = STATUS_BG.get(r.status, C_LIGHT2)
            style += [
                ('BACKGROUND', (5, i), (5, i), bg),
                ('TEXTCOLOR',  (5, i), (5, i), fg),
                ('FONTNAME',   (5, i), (5, i), 'Helvetica-Bold'),
            ]
            if r.status in ('cancelled', 'expired'):
                style.append(('TEXTCOLOR', (0, i), (4, i), C_LGRAY))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

    buf  = _build_pdf('Relatorio de Reservas', 'TaskFlow v2 — Gestao de Equipamentos', meta, build_story)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="reservas.pdf"'
    return resp



# ════════════════════════════════════════════════════════════════════════════════
# PDF — RESERVAS DE LABORATORIOS
# ════════════════════════════════════════════════════════════════════════════════

@reports_bp.route('/admin/relatorios/reservas-labs.pdf')
@login_required
def lab_reservations_pdf():
    redir = admin_required_redirect()
    if redir: return redir

    date_from = _parse_date_util(request.args.get('date_from'))
    date_to   = _parse_date_util(request.args.get('date_to'))
    user_id   = request.args.get('user_id', type=int)
    status    = request.args.get('status', 'all')

    q = LabReservation.query
    if date_from: q = q.filter(LabReservation.date >= date_from)
    if date_to:   q = q.filter(LabReservation.date <= date_to)
    if user_id:   q = q.filter(LabReservation.user_id == user_id)
    if status != 'all': q = q.filter(LabReservation.status == status)
    data = q.order_by(LabReservation.date, LabReservation.start_time).all()

    if not data:
        flash('Nenhuma reserva de laboratorio encontrada para os filtros selecionados.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total     = len(data)
    confirmed = sum(1 for r in data if r.status == 'confirmed')
    cancelled = sum(1 for r in data if r.status == 'cancelled')
    expired   = sum(1 for r in data if r.status == 'expired')

    meta = [
        ('Periodo',    _period_str(date_from, date_to)),
        ('Usuario',    user_name or 'Todos'),
        ('Status',     {'all':'Todos','confirmed':'Confirmadas','cancelled':'Canceladas','expired':'Expiradas'}.get(status, status)),
        ('Emitido em', datetime.now().strftime('%d/%m/%Y %H:%M')),
        ('Emitido por', current_user.name),
    ]

    STATUS_LBL = {'confirmed': 'Confirmada', 'cancelled': 'Cancelada', 'expired': 'Expirada'}
    STATUS_FG  = {'confirmed': C_GREEN,  'cancelled': C_RED,    'expired': C_LGRAY}
    STATUS_BG  = {'confirmed': C_GREEN_BG, 'cancelled': C_RED_BG, 'expired': C_LIGHT2}

    C_LAB = colors.HexColor('#6366f1')   # roxo/indigo dos labs

    def build_story(story, st, cw):
        story.append(_kpi_table([
            ('Total',       total,     C_DARK,  C_WHITE),
            ('Confirmadas', confirmed, C_GREEN, C_GREEN_BG),
            ('Canceladas',  cancelled, C_RED,   C_RED_BG),
            ('Expiradas',   expired,   C_LGRAY, C_LIGHT2),
        ], W))
        story.append(Spacer(1, 14))

        story.append(KeepTogether([
            Paragraph(f'Listagem de Reservas de Laboratorios <font color="#94a3b8" size="9">({total} registros)</font>', st['rpt_section']),
        ]))

        cols = [cw*0.11, cw*0.22, cw*0.20, cw*0.12, cw*0.12, cw*0.11, cw*0.12]
        rows = [['Data', 'Laboratorio', 'Usuario', 'Horario', 'Slots', 'Localizacao', 'Status']]
        for r in data:
            slots = r.slots_label if r.slots else f"{r.start_time.strftime('%H:%M')}-{r.end_time.strftime('%H:%M')}"
            loc   = (r.lab.location or '-') if r.lab else '-'
            rows.append([
                r.date.strftime('%d/%m/%Y'),
                Paragraph((r.lab.name  if r.lab  else '-')[:32], st['rpt_td']),
                Paragraph((r.user.name if r.user else '-')[:28], st['rpt_td']),
                f"{r.start_time.strftime('%H:%M')}-{r.end_time.strftime('%H:%M')}",
                Paragraph(slots[:30], st['rpt_td']),
                Paragraph(loc[:20],   st['rpt_td']),
                STATUS_LBL.get(r.status, r.status),
            ])

        tbl   = Table(rows, colWidths=cols, repeatRows=1)
        style = _main_table_style(len(data))
        for i, r in enumerate(data, start=1):
            fg = STATUS_FG.get(r.status, C_LGRAY)
            bg = STATUS_BG.get(r.status, C_LIGHT2)
            style += [
                ('BACKGROUND', (6, i), (6, i), bg),
                ('TEXTCOLOR',  (6, i), (6, i), fg),
                ('FONTNAME',   (6, i), (6, i), 'Helvetica-Bold'),
            ]
            if r.status in ('cancelled', 'expired'):
                style.append(('TEXTCOLOR', (0, i), (5, i), C_LGRAY))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

    buf  = _build_pdf('Relatorio de Reservas de Laboratorios', 'TaskFlow v2 — Gestao de Laboratorios', meta, build_story)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="reservas-labs.pdf"'
    return resp

# ════════════════════════════════════════════════════════════════════════════════
# PDF — TAREFAS
# ════════════════════════════════════════════════════════════════════════════════

@reports_bp.route('/admin/relatorios/tarefas.pdf')
@login_required
def tasks_pdf():
    redir = admin_required_redirect()
    if redir: return redir

    date_from = _parse_date_util(request.args.get('date_from'))
    date_to   = _parse_date_util(request.args.get('date_to'))
    user_id   = request.args.get('user_id', type=int)
    status    = request.args.get('status', 'all')
    priority  = request.args.get('priority', 'all')

    q = Task.query
    if date_from: q = q.filter(Task.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:   q = q.filter(Task.created_at <= datetime.combine(date_to,   datetime.max.time()))
    if user_id:   q = q.filter(Task.assigned_to == user_id)
    if status   != 'all': q = q.filter(Task.status   == status)
    if priority != 'all': q = q.filter(Task.priority == priority)
    data = q.order_by(Task.created_at.desc()).all()

    # Bloqueia se vazio
    if not data:
        flash('Nenhuma tarefa encontrada para os filtros selecionados. Ajuste o periodo ou os filtros.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total   = len(data)
    pending = sum(1 for t in data if t.status == 'pending')
    in_prog = sum(1 for t in data if t.status == 'in_progress')
    done    = sum(1 for t in data if t.status == 'done')
    overdue = sum(1 for t in data if t.is_overdue)

    meta = [
        ('Periodo',     _period_str(date_from, date_to)),
        ('Responsavel', user_name or 'Todos'),
        ('Status',      {'all':'Todos','pending':'Pendentes','in_progress':'Em Andamento','done':'Concluidas'}.get(status, status)),
        ('Prioridade',  {'all':'Todas','low':'Baixa','medium':'Media','high':'Alta','urgent':'Urgente'}.get(priority, priority)),
        ('Emitido em',  datetime.now().strftime('%d/%m/%Y %H:%M')),
    ]

    STATUS_LBL   = {'pending': 'Pendente', 'in_progress': 'Em Andamento', 'done': 'Concluida'}
    STATUS_BADGE = {'pending': (C_YELLOW, C_YEL_BG), 'in_progress': (C_BLUE, C_BLUE_BG), 'done': (C_GREEN, C_GREEN_BG)}
    PRIO_LBL     = {'low': 'Baixa', 'medium': 'Media', 'high': 'Alta', 'urgent': 'Urgente'}
    PRIO_BADGE   = {'low': (C_LGRAY, C_LIGHT2), 'medium': (C_DARK, C_LIGHT2), 'high': (C_YELLOW, C_YEL_BG), 'urgent': (C_RED, C_RED_BG)}

    def build_story(story, st, cw):
        # KPIs
        story.append(_kpi_table([
            ('Total',        total,   C_DARK,   C_WHITE),
            ('Pendentes',    pending, C_YELLOW, C_YEL_BG),
            ('Em Andamento', in_prog, C_BLUE,   C_BLUE_BG),
            ('Concluidas',   done,    C_GREEN,  C_GREEN_BG),
            ('Atrasadas',    overdue, C_RED,    C_RED_BG),
        ], W))
        story.append(Spacer(1, 14))

        story.append(KeepTogether([
            Paragraph(f'Listagem de Tarefas <font color="#94a3b8" size="9">({total} registros)</font>', st['rpt_section']),
        ]))

        # Status "Em Andamento" = ~10 chars, precisa de ~2.8cm com padding
        cols = [cw*0.28, cw*0.19, cw*0.17, cw*0.14, cw*0.12, cw*0.10]
        rows = [['Titulo', 'Responsavel', 'Status', 'Prioridade', 'Vencimento', 'Criado']]
        for t in data:
            due = t.due_date.strftime('%d/%m/%Y') if t.due_date else '-'
            if t.is_overdue: due = due + '(!)'
            rows.append([
                Paragraph(t.title[:60] + ('...' if len(t.title) > 60 else ''), st['rpt_td']),
                Paragraph((t.assignee.name if t.assignee else 'Sem responsavel')[:28], st['rpt_td']),
                STATUS_LBL.get(t.status, t.status),
                PRIO_LBL.get(t.priority, t.priority),
                due,
                t.created_at.strftime('%d/%m/%Y') if t.created_at else '-',
            ])

        tbl   = Table(rows, colWidths=cols, repeatRows=1)
        style = _main_table_style(len(data))
        for i, t in enumerate(data, start=1):
            s_fg, s_bg = STATUS_BADGE.get(t.status, (C_GRAY, C_LIGHT2))
            p_fg, p_bg = PRIO_BADGE.get(t.priority, (C_DARK, C_LIGHT2))
            style += [
                # Status — fundo colorido aplicado DEPOIS da zebra (sobrescreve corretamente)
                ('BACKGROUND', (2, i), (2, i), s_bg),
                ('TEXTCOLOR',  (2, i), (2, i), s_fg),
                ('FONTNAME',   (2, i), (2, i), 'Helvetica-Bold'),
                # Prioridade
                ('BACKGROUND', (3, i), (3, i), p_bg),
                ('TEXTCOLOR',  (3, i), (3, i), p_fg),
                ('FONTNAME',   (3, i), (3, i), 'Helvetica-Bold'),
            ]
            if t.is_overdue:
                style += [
                    ('TEXTCOLOR', (4, i), (4, i), C_RED),
                    ('FONTNAME',  (4, i), (4, i), 'Helvetica-Bold'),
                ]
            if t.status == 'done':
                style.append(('TEXTCOLOR', (0, i), (1, i), C_LGRAY))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

    buf  = _build_pdf('Relatorio de Tarefas', 'TaskFlow v2 — Gestao de Tarefas', meta, build_story)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="tarefas.pdf"'
    return resp