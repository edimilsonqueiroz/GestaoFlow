from datetime import date, datetime
from io import BytesIO
import math

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
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
    HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable

reports_bp = Blueprint('reports', __name__)

# ── Paleta ────────────────────────────────────────────────────────────────────
C_ACCENT   = colors.HexColor('#6c63ff')
C_ACCENT2  = colors.HexColor('#4f46e5')
C_ACCENT_L = colors.HexColor('#ede9fe')
C_DARK     = colors.HexColor('#0f172a')
C_DARK2    = colors.HexColor('#1e293b')
C_GRAY     = colors.HexColor('#64748b')
C_LGRAY    = colors.HexColor('#94a3b8')
C_LIGHT    = colors.HexColor('#f8fafc')
C_LIGHT2   = colors.HexColor('#f1f5f9')
C_BORDER   = colors.HexColor('#e2e8f0')
C_GREEN    = colors.HexColor('#059669')
C_GREEN_L  = colors.HexColor('#d1fae5')
C_RED      = colors.HexColor('#dc2626')
C_RED_L    = colors.HexColor('#fee2e2')
C_YELLOW   = colors.HexColor('#d97706')
C_YEL_L    = colors.HexColor('#fef3c7')
C_BLUE     = colors.HexColor('#2563eb')
C_BLUE_L   = colors.HexColor('#dbeafe')
C_INDIGO   = colors.HexColor('#6366f1')
C_INDIGO_L = colors.HexColor('#e0e7ff')
C_WHITE    = colors.white
C_ORANGE   = colors.HexColor('#ea580c')
C_ORANGE_L = colors.HexColor('#ffedd5')

W, H  = A4
MG    = 1.6 * cm
CW    = W - 2 * MG   # largura útil


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _period_str(date_from, date_to):
    if date_from and date_to:
        return f"{date_from.strftime('%d/%m/%Y')} a {date_to.strftime('%d/%m/%Y')}"
    elif date_from:
        return f"A partir de {date_from.strftime('%d/%m/%Y')}"
    elif date_to:
        return f"Ate {date_to.strftime('%d/%m/%Y')}"
    return "Todos os registros"


# ─────────────────────────────────────────────────────────────────────────────
# ESTILOS TIPOGRÁFICOS
# ─────────────────────────────────────────────────────────────────────────────

def _st():
    return {
        'title':    ParagraphStyle('title',    fontName='Helvetica-Bold', fontSize=22,
                                   textColor=C_WHITE,  leading=26),
        'subtitle': ParagraphStyle('subtitle', fontName='Helvetica',      fontSize=9,
                                   textColor=colors.HexColor('#c4b5fd')),
        'section':  ParagraphStyle('section',  fontName='Helvetica-Bold', fontSize=10,
                                   textColor=C_DARK2, spaceBefore=16, spaceAfter=6,
                                   leading=14),
        'th':       ParagraphStyle('th',       fontName='Helvetica-Bold', fontSize=7.5,
                                   textColor=C_WHITE, leading=10),
        'td':       ParagraphStyle('td',       fontName='Helvetica',      fontSize=8,
                                   textColor=C_DARK,  leading=11),
        'td_muted': ParagraphStyle('td_muted', fontName='Helvetica',      fontSize=8,
                                   textColor=C_LGRAY, leading=11),
        'badge':    ParagraphStyle('badge',    fontName='Helvetica-Bold', fontSize=7,
                                   alignment=TA_CENTER, leading=9),
        'meta_lbl': ParagraphStyle('meta_lbl', fontName='Helvetica-Bold', fontSize=6,
                                   textColor=C_LGRAY),
        'meta_val': ParagraphStyle('meta_val', fontName='Helvetica',      fontSize=8,
                                   textColor=C_DARK2),
        'footer':   ParagraphStyle('footer',   fontName='Helvetica',      fontSize=7,
                                   textColor=C_LGRAY),
        'kpi_lbl':  ParagraphStyle('kpi_lbl',  fontName='Helvetica-Bold', fontSize=6.5,
                                   textColor=C_GRAY, alignment=TA_CENTER),
        'kpi_val':  ParagraphStyle('kpi_val',  fontName='Helvetica-Bold', fontSize=22,
                                   alignment=TA_CENTER, leading=26),
        'empty':    ParagraphStyle('empty',    fontName='Helvetica',      fontSize=10,
                                   textColor=C_LGRAY, alignment=TA_CENTER, spaceBefore=20),
    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOWABLES CUSTOMIZADOS
# ─────────────────────────────────────────────────────────────────────────────

class HeaderBand(Flowable):
    """Cabeçalho com gradiente, logo-like e informações do relatório."""
    H = 2.6 * cm

    def __init__(self, title, subtitle, accent=None):
        super().__init__()
        self.title    = title
        self.subtitle = subtitle
        self.accent   = accent or C_ACCENT
        self.height   = self.H
        self._width   = CW

    def draw(self):
        c = self.canv
        w, h = self._width, self.height

        # Fundo principal
        c.setFillColor(self.accent)
        c.roundRect(0, 0, w, h, 5, fill=1, stroke=0)

        # Faixa escura no topo (decoração)
        c.setFillColor(colors.HexColor('#00000030'))
        c.rect(0, h - 6, w, 6, fill=1, stroke=0)

        # Decoração: linhas diagonais sutis no canto direito
        c.setStrokeColor(colors.HexColor('#ffffff20'))
        c.setLineWidth(1.2)
        for i in range(7):
            ox = w - 2.8*cm + i * 0.38*cm
            c.line(ox, 0, min(ox + h, w), min(h, h))
            c.line(ox, 0, min(ox + h, w), h)

        # Acento lateral esquerdo
        c.setFillColor(colors.HexColor('#00000025'))
        c.rect(0, 0, 5, h, fill=1, stroke=0)

        # Ícone/quadrado decorativo
        c.setFillColor(colors.HexColor('#ffffff20'))
        c.roundRect(14, h/2 - 14, 28, 28, 4, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 14)
        c.setFillColor(C_WHITE)
        c.drawCentredString(28, h/2 - 5, 'TF')

        # Título
        c.setFont('Helvetica-Bold', 19)
        c.setFillColor(C_WHITE)
        c.drawString(52, h - 0.9*cm, self.title)

        # Subtítulo
        c.setFont('Helvetica', 8.5)
        c.setFillColor(colors.HexColor('#ddd6fe'))
        c.drawString(53, 0.52*cm, self.subtitle)

        # Data/hora no canto direito
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.HexColor('#ffffffaa'))
        c.drawRightString(w - 12, h - 0.72*cm,
                          f"Emitido em {datetime.now().strftime('%d/%m/%Y  %H:%M')}")
        c.drawRightString(w - 12, 0.52*cm, f"por {current_user.name}")


class MetaStrip(Flowable):
    """Faixa horizontal de metadados (período, usuário, status...)."""
    H = 1.05 * cm

    def __init__(self, items):
        super().__init__()
        self.items  = items   # [(label, valor), ...]
        self.height = self.H
        self._width = CW

    def draw(self):
        c   = self.canv
        w   = self._width
        n   = len(self.items)

        # Fundo
        c.setFillColor(C_LIGHT2)
        c.roundRect(0, 0, w, self.height, 4, fill=1, stroke=0)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, w, self.height, 4, fill=0, stroke=1)

        col_w = (w - 24) / n
        x = 12
        for label, value in self.items:
            # Linha divisória (exceto no primeiro)
            if x > 12:
                c.setStrokeColor(C_BORDER)
                c.setLineWidth(0.5)
                c.line(x - 6, 4, x - 6, self.height - 4)

            c.setFont('Helvetica-Bold', 6)
            c.setFillColor(C_LGRAY)
            c.drawString(x, self.height - 9, label.upper())

            c.setFont('Helvetica', 7.5)
            c.setFillColor(C_DARK2)
            txt = value[:24] if len(value) > 24 else value
            c.drawString(x, 5, txt)
            x += col_w


class SectionHeader(Flowable):
    """Cabeçalho de seção com linha colorida."""
    def __init__(self, text, count=None, accent=None):
        super().__init__()
        self.text   = text
        self.count  = count
        self.accent = accent or C_ACCENT
        self.height = 22
        self._width = CW

    def draw(self):
        c = self.canv
        # Linha accent
        c.setStrokeColor(self.accent)
        c.setLineWidth(2.5)
        c.line(0, 2, self._width, 2)

        # Texto
        c.setFont('Helvetica-Bold', 10)
        c.setFillColor(C_DARK)
        c.drawString(0, 8, self.text)

        # Contagem
        if self.count is not None:
            txt = f"  {self.count} registro{'s' if self.count != 1 else ''}"
            c.setFont('Helvetica', 8)
            c.setFillColor(C_LGRAY)
            # Posiciona após o texto principal (aprox.)
            tw = len(self.text) * 5.8
            c.drawString(tw, 8, txt)


class KpiRow(Flowable):
    """Linha de KPI cards modernos."""
    H = 1.8 * cm

    def __init__(self, items):
        super().__init__()
        self.items  = items   # [(label, valor, cor_texto, cor_fundo), ...]
        self.height = self.H
        self._width = CW

    def draw(self):
        c   = self.canv
        w   = self._width
        n   = len(self.items)
        gap = 6
        cw  = (w - gap * (n - 1)) / n

        for i, (label, value, fg, bg) in enumerate(self.items):
            x = i * (cw + gap)

            # Card fundo
            c.setFillColor(bg)
            c.roundRect(x, 0, cw, self.height, 4, fill=1, stroke=0)
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.5)
            c.roundRect(x, 0, cw, self.height, 4, fill=0, stroke=1)

            # Barra colorida no topo do card
            c.setFillColor(fg)
            c.roundRect(x, self.height - 3.5, cw, 3.5, 2, fill=1, stroke=0)

            # Valor grande
            c.setFont('Helvetica-Bold', 20)
            c.setFillColor(fg)
            c.drawCentredString(x + cw / 2, self.height / 2 - 6, str(value))

            # Label embaixo
            c.setFont('Helvetica-Bold', 6)
            c.setFillColor(C_GRAY)
            c.drawCentredString(x + cw / 2, 5, label.upper())


# ─────────────────────────────────────────────────────────────────────────────
# RODAPÉ DE PÁGINA
# ─────────────────────────────────────────────────────────────────────────────

def _on_page(canvas, doc):
    canvas.saveState()
    y = MG * 0.45

    # Linha
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MG, y + 11, W - MG, y + 11)

    # Texto esquerdo
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(C_LGRAY)
    canvas.drawString(MG, y + 1,
        f"TaskFlow v2  •  {datetime.now().strftime('%d/%m/%Y')}  •  {current_user.name}")

    # Página direita
    canvas.drawRightString(W - MG, y + 1, f"Página {doc.page}")
    canvas.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
# TABELA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def _table_style(n_rows):
    style = [
        # Cabeçalho
        ('BACKGROUND',    (0, 0), (-1,  0), C_DARK2),
        ('TEXTCOLOR',     (0, 0), (-1,  0), C_WHITE),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1,  0), 7.5),
        ('TOPPADDING',    (0, 0), (-1,  0), 7),
        ('BOTTOMPADDING', (0, 0), (-1,  0), 7),
        ('LEFTPADDING',   (0, 0), (-1,  0), 8),
        # Dados
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 8),
        ('TOPPADDING',    (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        # Linha divisória leve
        ('LINEBELOW',     (0, 0), (-1, -1), 0.3, C_BORDER),
        # Borda externa
        ('BOX',           (0, 0), (-1, -1), 0.5, C_BORDER),
    ]
    # Zebra
    for i in range(1, n_rows + 1):
        bg = C_WHITE if i % 2 == 1 else C_LIGHT
        style.append(('BACKGROUND', (0, i), (-1, i), bg))
    return style


def _badge_cell(text, fg, bg):
    """Célula com fundo colorido simulando badge."""
    tbl = Table([[text]], colWidths=[1.7*cm])
    tbl.setStyle(TableStyle([
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
    ]))
    return tbl


# ─────────────────────────────────────────────────────────────────────────────
# BUILD PDF GENÉRICO
# ─────────────────────────────────────────────────────────────────────────────

def _build_pdf(title, subtitle, meta_items, story_fn, accent=None):
    buf = BytesIO()
    st  = _st()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MG, rightMargin=MG,
        topMargin=MG, bottomMargin=MG * 1.5,
    )
    story = []
    story.append(HeaderBand(title, subtitle, accent))
    story.append(Spacer(1, 7))
    story.append(MetaStrip(meta_items))
    story.append(Spacer(1, 14))
    story_fn(story, st)
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# TELA — formulário
# ─────────────────────────────────────────────────────────────────────────────

@reports_bp.route('/admin/relatorios')
@login_required
def index():
    redir = admin_required_redirect()
    if redir: return redir
    users = User.query.filter_by(is_active_account=True).order_by(User.name).all()
    return render_template('reports/index.html', users=users)


# ─────────────────────────────────────────────────────────────────────────────
# PDF — RESERVAS DE EQUIPAMENTOS
# ─────────────────────────────────────────────────────────────────────────────

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

    if not data:
        flash('Nenhuma reserva encontrada para os filtros selecionados.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total     = len(data)
    confirmed = sum(1 for r in data if r.status == 'confirmed')
    in_use    = sum(1 for r in data if r.status == 'in_use')
    returned  = sum(1 for r in data if r.status == 'returned')
    cancelled = sum(1 for r in data if r.status == 'cancelled')
    expired   = sum(1 for r in data if r.status == 'expired')

    STATUS_LBL = {
        'confirmed': 'Confirmada', 'in_use': 'Em Uso',
        'returned':  'Devolvida',  'cancelled': 'Cancelada', 'expired': 'Expirada',
    }
    STATUS_FG = {
        'confirmed': C_BLUE,   'in_use': C_YELLOW,
        'returned':  C_GREEN,  'cancelled': C_RED,  'expired': C_LGRAY,
    }
    STATUS_BG = {
        'confirmed': C_BLUE_L,  'in_use': C_YEL_L,
        'returned':  C_GREEN_L, 'cancelled': C_RED_L, 'expired': C_LIGHT2,
    }

    meta = [
        ('Período',    _period_str(date_from, date_to)),
        ('Usuário',    user_name or 'Todos'),
        ('Status',     STATUS_LBL.get(status, 'Todos')),
        ('Total',      str(total)),
        ('Emitido em', datetime.now().strftime('%d/%m/%Y %H:%M')),
    ]

    def build_story(story, st):
        # KPIs
        story.append(KpiRow([
            ('Total',       total,     C_ACCENT, C_ACCENT_L),
            ('Confirmadas', confirmed, C_BLUE,   C_BLUE_L),
            ('Em Uso',      in_use,    C_YELLOW, C_YEL_L),
            ('Devolvidas',  returned,  C_GREEN,  C_GREEN_L),
            ('Canceladas',  cancelled, C_RED,    C_RED_L),
        ]))
        story.append(Spacer(1, 16))
        story.append(SectionHeader('Listagem de Reservas', total))
        story.append(Spacer(1, 8))

        cols = [CW*0.10, CW*0.22, CW*0.19, CW*0.13, CW*0.20, CW*0.16]
        rows = [[
            Paragraph('Data',        st['th']),
            Paragraph('Equipamento', st['th']),
            Paragraph('Usuário',     st['th']),
            Paragraph('Horário',     st['th']),
            Paragraph('Slots',       st['th']),
            Paragraph('Status',      st['th']),
        ]]
        for r in data:
            slots  = r.slots_label if r.slots else f"{r.start_time.strftime('%H:%M')}–{r.end_time.strftime('%H:%M')}"
            is_dim = r.status in ('cancelled', 'expired')
            td     = st['td_muted'] if is_dim else st['td']
            rows.append([
                Paragraph(r.date.strftime('%d/%m/%Y'), td),
                Paragraph((r.equipment.name if r.equipment else '—')[:32], td),
                Paragraph((r.user.name      if r.user      else '—')[:26], td),
                Paragraph(f"{r.start_time.strftime('%H:%M')}–{r.end_time.strftime('%H:%M')}", td),
                Paragraph(slots[:38], td),
                _badge_cell(STATUS_LBL.get(r.status, r.status),
                            STATUS_FG.get(r.status, C_LGRAY),
                            STATUS_BG.get(r.status, C_LIGHT2)),
            ])

        tbl   = Table(rows, colWidths=cols, repeatRows=1)
        style = _table_style(len(data))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

        # Notas de rodapé da seção
        if returned > 0 or in_use > 0:
            story.append(Spacer(1, 8))
            nota = Paragraph(
                f'<font color="#94a3b8">* Em Uso: {in_use}  |  Devolvidas: {returned}  |  '
                f'Expiradas: {expired}</font>', st['footer'])
            story.append(nota)

    buf  = _build_pdf('Relatório de Reservas', 'TaskFlow v2  —  Gestão de Equipamentos', meta, build_story)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="reservas.pdf"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# PDF — RESERVAS DE LABORATÓRIOS
# ─────────────────────────────────────────────────────────────────────────────

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
        flash('Nenhuma reserva de laboratório encontrada.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total     = len(data)
    confirmed = sum(1 for r in data if r.status == 'confirmed')
    in_use    = sum(1 for r in data if r.status == 'in_use')
    returned  = sum(1 for r in data if r.status == 'returned')
    cancelled = sum(1 for r in data if r.status == 'cancelled')
    expired   = sum(1 for r in data if r.status == 'expired')

    STATUS_LBL = {
        'confirmed': 'Confirmada', 'in_use': 'Em Uso',
        'returned':  'Devolvida',  'cancelled': 'Cancelada', 'expired': 'Expirada',
    }
    STATUS_FG = {
        'confirmed': C_BLUE,   'in_use': C_YELLOW,
        'returned':  C_GREEN,  'cancelled': C_RED,  'expired': C_LGRAY,
    }
    STATUS_BG = {
        'confirmed': C_BLUE_L,  'in_use': C_YEL_L,
        'returned':  C_GREEN_L, 'cancelled': C_RED_L, 'expired': C_LIGHT2,
    }

    meta = [
        ('Período',    _period_str(date_from, date_to)),
        ('Usuário',    user_name or 'Todos'),
        ('Status',     STATUS_LBL.get(status, 'Todos')),
        ('Total',      str(total)),
        ('Emitido em', datetime.now().strftime('%d/%m/%Y %H:%M')),
    ]

    def build_story(story, st):
        story.append(KpiRow([
            ('Total',       total,     C_INDIGO, C_INDIGO_L),
            ('Confirmadas', confirmed, C_BLUE,   C_BLUE_L),
            ('Em Uso',      in_use,    C_YELLOW, C_YEL_L),
            ('Devolvidas',  returned,  C_GREEN,  C_GREEN_L),
            ('Canceladas',  cancelled, C_RED,    C_RED_L),
        ]))
        story.append(Spacer(1, 16))
        story.append(SectionHeader('Listagem de Reservas de Laboratórios', total, C_INDIGO))
        story.append(Spacer(1, 8))

        cols = [CW*0.10, CW*0.20, CW*0.18, CW*0.12, CW*0.11, CW*0.13, CW*0.16]
        rows = [[
            Paragraph('Data',         st['th']),
            Paragraph('Laboratório',  st['th']),
            Paragraph('Usuário',      st['th']),
            Paragraph('Horário',      st['th']),
            Paragraph('Slots',        st['th']),
            Paragraph('Local',        st['th']),
            Paragraph('Status',       st['th']),
        ]]
        for r in data:
            slots  = r.slots_label if r.slots else f"{r.start_time.strftime('%H:%M')}–{r.end_time.strftime('%H:%M')}"
            loc    = (r.lab.location or '—') if r.lab else '—'
            is_dim = r.status in ('cancelled', 'expired')
            td     = st['td_muted'] if is_dim else st['td']
            rows.append([
                Paragraph(r.date.strftime('%d/%m/%Y'), td),
                Paragraph((r.lab.name  if r.lab  else '—')[:28], td),
                Paragraph((r.user.name if r.user else '—')[:26], td),
                Paragraph(f"{r.start_time.strftime('%H:%M')}–{r.end_time.strftime('%H:%M')}", td),
                Paragraph(slots[:22], td),
                Paragraph(loc[:18], td),
                _badge_cell(STATUS_LBL.get(r.status, r.status),
                            STATUS_FG.get(r.status, C_LGRAY),
                            STATUS_BG.get(r.status, C_LIGHT2)),
            ])

        tbl = Table(rows, colWidths=cols, repeatRows=1)
        tbl.setStyle(TableStyle(_table_style(len(data))))
        story.append(tbl)

    buf  = _build_pdf('Relatório de Laboratórios', 'TaskFlow v2  —  Gestão de Laboratórios',
                      meta, build_story, accent=C_INDIGO)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="reservas-labs.pdf"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# PDF — TAREFAS
# ─────────────────────────────────────────────────────────────────────────────

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

    if not data:
        flash('Nenhuma tarefa encontrada para os filtros selecionados.', 'warning')
        return redirect(url_for('reports.index'))

    user_name = User.query.get(user_id).name if user_id else None
    total   = len(data)
    pending = sum(1 for t in data if t.status == 'pending')
    in_prog = sum(1 for t in data if t.status == 'in_progress')
    done    = sum(1 for t in data if t.status == 'done')
    overdue = sum(1 for t in data if t.is_overdue)

    STATUS_LBL = {'pending': 'Pendente', 'in_progress': 'Em Andamento', 'done': 'Concluída'}
    STATUS_FG  = {'pending': C_YELLOW,  'in_progress': C_BLUE,  'done': C_GREEN}
    STATUS_BG  = {'pending': C_YEL_L,   'in_progress': C_BLUE_L, 'done': C_GREEN_L}
    PRIO_LBL   = {'low': 'Baixa', 'medium': 'Média', 'high': 'Alta', 'urgent': 'Urgente'}
    PRIO_FG    = {'low': C_LGRAY, 'medium': C_GRAY, 'high': C_ORANGE, 'urgent': C_RED}
    PRIO_BG    = {'low': C_LIGHT2, 'medium': C_LIGHT2, 'high': C_ORANGE_L, 'urgent': C_RED_L}

    meta = [
        ('Período',     _period_str(date_from, date_to)),
        ('Responsável', user_name or 'Todos'),
        ('Status',      STATUS_LBL.get(status, 'Todos')),
        ('Prioridade',  PRIO_LBL.get(priority, 'Todas')),
        ('Total',       str(total)),
    ]

    def build_story(story, st):
        story.append(KpiRow([
            ('Total',        total,   C_GREEN,  C_GREEN_L),
            ('Pendentes',    pending, C_YELLOW, C_YEL_L),
            ('Em Andamento', in_prog, C_BLUE,   C_BLUE_L),
            ('Concluídas',   done,    C_GREEN,  C_GREEN_L),
            ('Atrasadas',    overdue, C_RED,    C_RED_L),
        ]))
        story.append(Spacer(1, 16))
        story.append(SectionHeader('Listagem de Tarefas', total, C_GREEN))
        story.append(Spacer(1, 8))

        cols = [CW*0.30, CW*0.18, CW*0.16, CW*0.13, CW*0.12, CW*0.11]
        rows = [[
            Paragraph('Título',       st['th']),
            Paragraph('Responsável',  st['th']),
            Paragraph('Status',       st['th']),
            Paragraph('Prioridade',   st['th']),
            Paragraph('Vencimento',   st['th']),
            Paragraph('Criado em',    st['th']),
        ]]
        for t in data:
            is_done = t.status == 'done'
            td = st['td_muted'] if is_done else st['td']
            due = '—'
            if t.due_date:
                due = t.due_date.strftime('%d/%m/%Y')
            rows.append([
                Paragraph((t.title[:55] + '…' if len(t.title) > 55 else t.title), td),
                Paragraph((t.assignee.name if t.assignee else 'Sem responsável')[:24], td),
                _badge_cell(STATUS_LBL.get(t.status, t.status),
                            STATUS_FG.get(t.status, C_GRAY),
                            STATUS_BG.get(t.status, C_LIGHT2)),
                _badge_cell(PRIO_LBL.get(t.priority, t.priority),
                            PRIO_FG.get(t.priority, C_GRAY),
                            PRIO_BG.get(t.priority, C_LIGHT2)),
                Paragraph(f'<font color="#dc2626"><b>{due} (!)</b></font>'
                          if t.is_overdue else due, st['td']),
                Paragraph(t.created_at.strftime('%d/%m/%Y') if t.created_at else '—', td),
            ])

        tbl   = Table(rows, colWidths=cols, repeatRows=1)
        style = _table_style(len(data))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

        if overdue:
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                f'<font color="#dc2626">⚠ {overdue} tarefa{"s" if overdue > 1 else ""} '
                f'com vencimento ultrapassado</font>', st['footer']))

    buf  = _build_pdf('Relatório de Tarefas', 'TaskFlow v2  —  Gestão de Tarefas',
                      meta, build_story, accent=C_GREEN)
    resp = Response(buf, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = 'inline; filename="tarefas.pdf"'
    return resp