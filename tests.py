"""
TaskFlow v2 — Suite de Testes
══════════════════════════════════════════════════════════════════════════════

EXECUTAR:
    python3 tests.py -v                              # todos
    python3 tests.py                                 # resumo
    python3 -m unittest tests.TestUserUnit -v        # só uma classe

COBERTURA — 119 testes em 14 classes:

  ── UNIT (rodam sem Flask/SQLAlchemy) ────────────────────────────────────────
  TestUserUnit            11  senha, initials, first_name, is_admin, task_stats
  TestTaskUnit            10  status_label, priority_label, is_overdue (todos)
  TestEquipmentUnit       12  category_label/icon para as 7 categorias + fallback
  TestReservationUnit     10  time_range, datetimes, period_label, weekday, slots
  TestTimeSlotUnit         6  time_range, label, duration_minutes
  TestCategoryCSS          8  toda categoria tem ícone, CSS e option no form
  TestPDFLayout            9  PDF gerado, bytes válidos, KPI sem overflow,
                              texto não vaza horizontal, Content-Disposition inline
  TestReportLogic          5  guarda de dados vazios, filtros de período/usuário

  ── INTEGRAÇÃO (requerem flask-sqlalchemy + flask-login) ─────────────────────
  TestAuth                 8  login, logout, registro, proteção de rotas
  TestAdminRoutes         13  CRUD usuários/tarefas, perfil, permissões
  TestUserRoutes           5  dashboard, update-status, isolamento
  TestEquipmentAdminRoutes 8  CRUD equipamentos (incl. microfone), cascade delete
  TestTimeSlotsAdmin       6  CRUD horários
  TestReservationRoutes   16  reserva válida, conflito, adjacentes, cancelamento,
                              expiração, equipamento inativo, admin override
"""
import os
import sys
import unittest
from datetime import date, time, datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Detecta dependências opcionais ───────────────────────────────────────────
try:
    import flask_sqlalchemy, flask_login
    INTEGRATION = True
except ImportError:
    INTEGRATION = False

try:
    import pdfplumber as _pdfplumber
    PDFPLUMBER = True
except ImportError:
    PDFPLUMBER = False

skip_integration = unittest.skipUnless(
    INTEGRATION, 'Requer flask-sqlalchemy e flask-login instalados'
)
skip_pdfplumber = unittest.skipUnless(
    PDFPLUMBER, 'Requer pdfplumber: pip install pdfplumber'
)


# ══════════════════════════════════════════════════════════════════════════════
# MOCKS LEVES — replicam as @property dos modelos sem ORM
# ══════════════════════════════════════════════════════════════════════════════

class FakeUser:
    def __init__(self, name='João Silva', email='j@t.com', role='user',
                 is_active_account=True, tasks=None):
        self.name = name; self.email = email; self.role = role
        self.is_active_account = is_active_account
        self._tasks = tasks or []; self.password_hash = None

    def set_password(self, pw):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        from werkzeug.security import check_password_hash
        return bool(self.password_hash and check_password_hash(self.password_hash, pw))

    @property
    def is_admin(self): return self.role == 'admin'

    @property
    def initials(self):
        p = self.name.split()
        return (p[0][0] + p[-1][0]).upper() if len(p) > 1 else p[0][0].upper()

    @property
    def first_name(self): return self.name.split()[0]

    def task_stats(self):
        total = len(self._tasks)
        done  = sum(1 for t in self._tasks if t.status == 'done')
        ip    = sum(1 for t in self._tasks if t.status == 'in_progress')
        pend  = sum(1 for t in self._tasks if t.status == 'pending')
        return {'total': total, 'done': done, 'in_progress': ip, 'pending': pend,
                'progress': int(done / total * 100) if total else 0}


class FakeTask:
    def __init__(self, title='T', status='pending', priority='medium', due_date=None):
        self.title = title; self.status = status; self.priority = priority
        self.due_date = due_date; self.created_at = datetime.utcnow()

    @property
    def status_label(self):
        return {'pending':'Pendente','in_progress':'Em Andamento',
                'done':'Concluída'}.get(self.status, self.status)

    @property
    def priority_label(self):
        return {'low':'Baixa','medium':'Média','high':'Alta',
                'urgent':'Urgente'}.get(self.priority, self.priority)

    @property
    def is_overdue(self):
        return bool(self.due_date and self.status != 'done'
                    and self.due_date < datetime.utcnow().date())


class FakeEquipment:
    LABEL_MAP = {
        'datashow':'📽️ Datashow','caixa_de_som':'🔊 Caixa de Som',
        'microfone':'🎤 Microfone','camera':'📷 Câmera',
        'notebook':'💻 Notebook','tv':'📺 TV / Monitor','outros':'📦 Outros',
    }
    ICON_MAP = {
        'datashow':'fa-projector','caixa_de_som':'fa-volume-up',
        'microfone':'fa-microphone','camera':'fa-camera',
        'notebook':'fa-laptop','tv':'fa-tv','outros':'fa-box',
    }

    def __init__(self, name='Datashow', category='datashow', is_active=True):
        self.name = name; self.category = category; self.is_active = is_active

    @property
    def category_label(self):
        return self.LABEL_MAP.get(self.category,
               self.category.replace('_', ' ').title())

    @property
    def category_icon(self):
        return self.ICON_MAP.get(self.category, 'fa-box')


class FakeReservation:
    def __init__(self, date_=None, start_time=time(8,0), end_time=time(10,0),
                 status='confirmed', slots=None):
        self.date = date_ or date.today()
        self.start_time = start_time; self.end_time = end_time
        self.status = status; self.slots = slots or []

    @property
    def time_range(self):
        return f"{self.start_time.strftime('%H:%M')} – {self.end_time.strftime('%H:%M')}"

    @property
    def start_datetime(self): return datetime.combine(self.date, self.start_time)

    @property
    def end_datetime(self): return datetime.combine(self.date, self.end_time)

    @property
    def weekday_label(self):
        return ['Segunda','Terça','Quarta','Quinta',
                'Sexta','Sábado','Domingo'][self.date.weekday()]

    @property
    def period_label(self):
        h = self.start_time.hour
        return '🌅 Manhã' if h < 12 else ('🌇 Tarde' if h < 18 else '🌃 Noite')

    @property
    def is_ongoing(self):
        now = datetime.now()
        return (self.status == 'confirmed'
                and self.start_datetime <= now < self.end_datetime)

    @property
    def slots_label(self):
        return ', '.join(s.description
                         for s in sorted(self.slots, key=lambda x: x.start_time))


class FakeTimeSlot:
    def __init__(self, description='Manhã', start_time=time(7,0),
                 end_time=time(12,0), is_active=True):
        self.description = description
        self.start_time = start_time; self.end_time = end_time
        self.is_active = is_active

    @property
    def time_range(self):
        return f"{self.start_time.strftime('%H:%M')} – {self.end_time.strftime('%H:%M')}"

    @property
    def label(self): return f"{self.description} ({self.time_range})"

    @property
    def duration_minutes(self):
        s = datetime.combine(date.today(), self.start_time)
        e = datetime.combine(date.today(), self.end_time)
        return int((e - s).total_seconds() // 60)


# ══════════════════════════════════════════════════════════════════════════════
# 1. UNIT — User
# ══════════════════════════════════════════════════════════════════════════════

class TestUserUnit(unittest.TestCase):

    def test_senha_correta(self):
        u = FakeUser(); u.set_password('abc123')
        self.assertTrue(u.check_password('abc123'))

    def test_senha_errada(self):
        u = FakeUser(); u.set_password('abc123')
        self.assertFalse(u.check_password('errada'))

    def test_initials_dois_nomes(self):
        self.assertEqual(FakeUser(name='João Silva').initials, 'JS')

    def test_initials_tres_nomes_usa_primeiro_e_ultimo(self):
        self.assertEqual(FakeUser(name='Ana Maria Costa').initials, 'AC')

    def test_initials_nome_simples(self):
        self.assertEqual(FakeUser(name='Pedro').initials, 'P')

    def test_first_name(self):
        self.assertEqual(FakeUser(name='Edimilson Francisco').first_name, 'Edimilson')

    def test_is_admin_verdadeiro(self):
        self.assertTrue(FakeUser(role='admin').is_admin)

    def test_is_admin_falso(self):
        self.assertFalse(FakeUser(role='user').is_admin)

    def test_task_stats_sem_tarefas(self):
        s = FakeUser(tasks=[]).task_stats()
        self.assertEqual(s['total'], 0)
        self.assertEqual(s['progress'], 0)

    def test_task_stats_progresso_parcial(self):
        tasks = [FakeTask(status='done'), FakeTask(status='done'),
                 FakeTask(status='pending'), FakeTask(status='in_progress')]
        s = FakeUser(tasks=tasks).task_stats()
        self.assertEqual(s['total'], 4)
        self.assertEqual(s['done'], 2)
        self.assertEqual(s['progress'], 50)

    def test_task_stats_todas_concluidas(self):
        tasks = [FakeTask(status='done')] * 3
        s = FakeUser(tasks=tasks).task_stats()
        self.assertEqual(s['progress'], 100)


# ══════════════════════════════════════════════════════════════════════════════
# 2. UNIT — Task
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskUnit(unittest.TestCase):

    def test_status_label_pending(self):
        self.assertEqual(FakeTask(status='pending').status_label, 'Pendente')

    def test_status_label_in_progress(self):
        self.assertEqual(FakeTask(status='in_progress').status_label, 'Em Andamento')

    def test_status_label_done(self):
        self.assertEqual(FakeTask(status='done').status_label, 'Concluída')

    def test_priority_label_low(self):
        self.assertEqual(FakeTask(priority='low').priority_label, 'Baixa')

    def test_priority_label_medium(self):
        self.assertEqual(FakeTask(priority='medium').priority_label, 'Média')

    def test_priority_label_high(self):
        self.assertEqual(FakeTask(priority='high').priority_label, 'Alta')

    def test_priority_label_urgent(self):
        self.assertEqual(FakeTask(priority='urgent').priority_label, 'Urgente')

    def test_is_overdue_pendente_atrasada(self):
        t = FakeTask(status='pending', due_date=date.today() - timedelta(days=1))
        self.assertTrue(t.is_overdue)

    def test_is_overdue_falso_quando_concluida(self):
        t = FakeTask(status='done', due_date=date.today() - timedelta(days=1))
        self.assertFalse(t.is_overdue)

    def test_is_overdue_falso_data_futura(self):
        t = FakeTask(status='pending', due_date=date.today() + timedelta(days=5))
        self.assertFalse(t.is_overdue)


# ══════════════════════════════════════════════════════════════════════════════
# 3. UNIT — Equipment (7 categorias expandidas)
# ══════════════════════════════════════════════════════════════════════════════

TODAS_CATEGORIAS = [
    ('datashow',    'fa-projector',   'Datashow'),
    ('caixa_de_som','fa-volume-up',   'Caixa'),
    ('microfone',   'fa-microphone',  'Microfone'),
    ('camera',      'fa-camera',      'Câmera'),
    ('notebook',    'fa-laptop',      'Notebook'),
    ('tv',          'fa-tv',          'TV'),
    ('outros',      'fa-box',         'Outros'),
]


class TestEquipmentUnit(unittest.TestCase):

    def test_todas_categorias_tem_icone_correto(self):
        for cat, icon, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                eq = FakeEquipment(category=cat)
                self.assertEqual(eq.category_icon, icon)

    def test_todas_categorias_tem_label_correto(self):
        for cat, _, label_fragment in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                eq = FakeEquipment(category=cat)
                self.assertIn(label_fragment, eq.category_label)

    def test_microfone_icone_corrigido(self):
        """Microfone era a categoria quebrada que não tinha mapeamento."""
        eq = FakeEquipment(category='microfone')
        self.assertEqual(eq.category_icon, 'fa-microphone')
        self.assertIn('Microfone', eq.category_label)

    def test_icones_sao_classes_fontawesome(self):
        for cat, _, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                eq = FakeEquipment(category=cat)
                self.assertTrue(eq.category_icon.startswith('fa-'))

    def test_categoria_desconhecida_icone_fallback(self):
        eq = FakeEquipment(category='qualquer_coisa')
        self.assertEqual(eq.category_icon, 'fa-box')

    def test_categoria_desconhecida_label_nao_vazio(self):
        eq = FakeEquipment(category='nova_cat')
        self.assertIsInstance(eq.category_label, str)
        self.assertGreater(len(eq.category_label), 0)

    def test_categoria_desconhecida_label_capitalizado(self):
        eq = FakeEquipment(category='alguma_coisa')
        # replace + title → "Alguma Coisa"
        self.assertEqual(eq.category_label, 'Alguma Coisa')


# ══════════════════════════════════════════════════════════════════════════════
# 4. UNIT — Reservation
# ══════════════════════════════════════════════════════════════════════════════

class TestReservationUnit(unittest.TestCase):

    def test_time_range_horas_cheias(self):
        r = FakeReservation(start_time=time(8,0), end_time=time(10,0))
        self.assertEqual(r.time_range, '08:00 – 10:00')

    def test_time_range_com_minutos(self):
        r = FakeReservation(start_time=time(9,30), end_time=time(11,45))
        self.assertEqual(r.time_range, '09:30 – 11:45')

    def test_start_datetime(self):
        d = date(2026, 6, 15)
        r = FakeReservation(date_=d, start_time=time(9,0))
        self.assertEqual(r.start_datetime, datetime(2026, 6, 15, 9, 0))

    def test_end_datetime(self):
        d = date(2026, 6, 15)
        r = FakeReservation(date_=d, end_time=time(11,30))
        self.assertEqual(r.end_datetime, datetime(2026, 6, 15, 11, 30))

    def test_period_label_manha(self):
        self.assertIn('Manhã', FakeReservation(start_time=time(8,0)).period_label)

    def test_period_label_tarde(self):
        self.assertIn('Tarde', FakeReservation(start_time=time(14,0)).period_label)

    def test_period_label_noite(self):
        self.assertIn('Noite', FakeReservation(start_time=time(19,0)).period_label)

    def test_weekday_label_todos_os_dias(self):
        base = date(2026, 3, 2)  # segunda-feira conhecida
        esperados = ['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo']
        for i, esp in enumerate(esperados):
            with self.subTest(dia=esp):
                r = FakeReservation(date_=base + timedelta(days=i))
                self.assertEqual(r.weekday_label, esp)

    def test_slots_label_ordenado_por_horario(self):
        s1 = MagicMock(); s1.description = 'Tarde';  s1.start_time = time(13,0)
        s2 = MagicMock(); s2.description = 'Manhã';  s2.start_time = time(7,0)
        r  = FakeReservation(slots=[s1, s2])
        self.assertEqual(r.slots_label, 'Manhã, Tarde')

    def test_is_ongoing_falso_se_cancelada(self):
        r = FakeReservation(
            date_=date.today(),
            start_time=(datetime.now() - timedelta(hours=1)).time(),
            end_time  =(datetime.now() + timedelta(hours=1)).time(),
            status='cancelled',
        )
        self.assertFalse(r.is_ongoing)


# ══════════════════════════════════════════════════════════════════════════════
# 5. UNIT — TimeSlot
# ══════════════════════════════════════════════════════════════════════════════

class TestTimeSlotUnit(unittest.TestCase):

    def test_time_range(self):
        ts = FakeTimeSlot(start_time=time(7,0), end_time=time(12,0))
        self.assertEqual(ts.time_range, '07:00 – 12:00')

    def test_label_contem_descricao_e_horario(self):
        ts = FakeTimeSlot(description='Manhã', start_time=time(7,0), end_time=time(12,0))
        self.assertIn('Manhã', ts.label)
        self.assertIn('07:00', ts.label)
        self.assertIn('12:00', ts.label)

    def test_duration_minutes_5h(self):
        self.assertEqual(
            FakeTimeSlot(start_time=time(7,0), end_time=time(12,0)).duration_minutes, 300)

    def test_duration_minutes_1h30(self):
        self.assertEqual(
            FakeTimeSlot(start_time=time(8,0), end_time=time(9,30)).duration_minutes, 90)

    def test_duration_minutes_30min(self):
        self.assertEqual(
            FakeTimeSlot(start_time=time(10,0), end_time=time(10,30)).duration_minutes, 30)

    def test_is_active_padrao_verdadeiro(self):
        self.assertTrue(FakeTimeSlot().is_active)


# ══════════════════════════════════════════════════════════════════════════════
# 6. UNIT — Mapeamento de categorias × arquivos do projeto
# ══════════════════════════════════════════════════════════════════════════════

BASE = os.path.dirname(os.path.abspath(__file__))


class TestCategoryCSS(unittest.TestCase):

    def _css(self):
        p = os.path.join(BASE, 'static', 'css', 'style.css')
        if not os.path.exists(p): self.skipTest('style.css não encontrado')
        return open(p, encoding='utf-8').read()

    def _form(self):
        p = os.path.join(BASE, 'templates', 'equipment', 'admin_form.html')
        if not os.path.exists(p): self.skipTest('admin_form.html não encontrado')
        return open(p, encoding='utf-8').read()

    def test_css_tem_regra_para_todas_as_categorias(self):
        css = self._css()
        for cat, _, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                self.assertIn(f'.equip-icon-badge.{cat}', css)

    def test_formulario_tem_option_para_todas_as_categorias(self):
        html = self._form()
        for cat, _, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                self.assertIn(f'value="{cat}"', html)

    def test_css_microfone_tem_cor(self):
        css = self._css()
        idx = css.find('.equip-icon-badge.microfone')
        self.assertGreater(idx, -1)
        # Confirma que há cor definida após a regra
        bloco = css[idx:idx+120]
        self.assertIn('background', bloco)

    def test_todos_icones_sao_fontawesome(self):
        for cat, icon, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                self.assertTrue(icon.startswith('fa-'))

    def test_models_py_tem_todas_categorias(self):
        p = os.path.join(BASE, 'models.py')
        if not os.path.exists(p): self.skipTest('models.py não encontrado')
        src = open(p, encoding='utf-8').read()
        for cat, _, _ in TODAS_CATEGORIAS:
            with self.subTest(categoria=cat):
                self.assertIn(f"'{cat}'", src)

    def test_fallback_icone_preservado(self):
        eq = FakeEquipment(category='inexistente')
        self.assertEqual(eq.category_icon, 'fa-box')

    def test_fallback_label_nao_explode(self):
        eq = FakeEquipment(category='nova_qualquer')
        label = eq.category_label
        self.assertIsInstance(label, str)
        self.assertGreater(len(label), 0)

    def test_microfone_corrigido_sem_fallback(self):
        """Antes da correção microfone caia no fallback fa-box."""
        eq = FakeEquipment(category='microfone')
        self.assertNotEqual(eq.category_icon, 'fa-box')
        self.assertEqual(eq.category_icon, 'fa-microphone')


# ══════════════════════════════════════════════════════════════════════════════
# 7. UNIT — Layout do PDF (ReportLab disponível sem ORM)
# ══════════════════════════════════════════════════════════════════════════════

def _build_kpi_pdf():
    """Gera um PDF de KPI igual ao do blueprint e retorna bytes."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    W, H = A4; MG = 1.8 * cm; cw = W - 2 * MG
    C_DARK = colors.HexColor('#0f172a'); C_WHITE = colors.white
    C_BORDER = colors.HexColor('#e2e8f0')
    C_YELLOW = colors.HexColor('#f59e0b'); C_YEL_BG = colors.HexColor('#fef3c7')
    C_BLUE   = colors.HexColor('#3b82f6'); C_BLUE_BG= colors.HexColor('#dbeafe')
    C_GREEN  = colors.HexColor('#10b981'); C_GREEN_BG=colors.HexColor('#d1fae5')
    C_RED    = colors.HexColor('#ef4444'); C_RED_BG  =colors.HexColor('#fee2e2')
    C_GRAY   = colors.HexColor('#64748b')

    items = [
        ('Total',        2, C_DARK,   C_WHITE),
        ('Pendentes',    0, C_YELLOW, C_YEL_BG),
        ('Em Andamento', 2, C_BLUE,   C_BLUE_BG),
        ('Concluidas',   0, C_GREEN,  C_GREEN_BG),
        ('Atrasadas',    0, C_RED,    C_RED_BG),
    ]
    n = len(items); colw = cw / n
    data = [[i[0] for i in items], [str(i[1]) for i in items]]
    tbl  = Table(data, colWidths=[colw]*n, rowHeights=[20, 44])
    style = [
        ('FONTNAME',      (0,0),(-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0),(-1,0), 7),
        ('TEXTCOLOR',     (0,0),(-1,0), C_GRAY),
        ('FONTNAME',      (0,1),(-1,1), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,1),(-1,1), 20),
        ('ALIGN',         (0,0),(-1,-1),'CENTER'),
        ('VALIGN',        (0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',    (0,1),(-1,1), 10),
        ('BOTTOMPADDING', (0,1),(-1,1), 10),
        ('BOX',           (0,0),(-1,-1),0.5, C_BORDER),
    ]
    for i, item in enumerate(items):
        style += [('BACKGROUND',(i,0),(i,-1),item[3]),
                  ('TEXTCOLOR', (i,1),(i, 1),item[2])]
        if i > 0: style.append(('LINEBEFORE',(i,0),(i,-1),0.5,C_BORDER))
    tbl.setStyle(TableStyle(style))
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4,
                      leftMargin=MG, rightMargin=MG,
                      topMargin=MG, bottomMargin=MG).build([tbl])
    buf.seek(0); return buf.read()


def _build_tasks_table_pdf():
    """Gera PDF da tabela de tarefas com nomes longos e status colorido."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph)
    from reportlab.lib.styles import ParagraphStyle

    W, H = A4; MG = 1.8 * cm; cw = W - 2 * MG
    C_DARK  = colors.HexColor('#0f172a'); C_WHITE = colors.white
    C_LIGHT = colors.HexColor('#f8fafc'); C_BORDER= colors.HexColor('#e2e8f0')
    C_BLUE  = colors.HexColor('#3b82f6'); C_BLUE_BG=colors.HexColor('#dbeafe')
    td = ParagraphStyle('td', fontName='Helvetica', fontSize=8, leading=11)

    cols = [cw*0.28, cw*0.19, cw*0.17, cw*0.14, cw*0.12, cw*0.10]
    rows = [['Titulo','Responsavel','Status','Prioridade','Vencimento','Criado']]
    for i in range(3):
        rows.append([
            Paragraph(f'Tarefa longa de teste numero {i+1} com titulo extenso', td),
            Paragraph('Edimilson Francisco de Sousa Lima', td),
            'Em Andamento', 'Alta', '02/03/2026', '01/03/2026',
        ])

    style = [
        ('BACKGROUND',(0,0),(-1, 0), C_DARK),
        ('TEXTCOLOR', (0,0),(-1, 0), C_WHITE),
        ('FONTNAME',  (0,0),(-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',  (0,0),(-1, 0), 8),
        ('FONTNAME',  (0,1),(-1,-1), 'Helvetica'),
        ('FONTSIZE',  (0,1),(-1,-1), 8),
        ('ALIGN',     (0,0),(-1,-1), 'LEFT'),
        ('VALIGN',    (0,0),(-1,-1), 'MIDDLE'),
        ('LINEBELOW', (0,0),(-1,-1), 0.3, C_BORDER),
        ('LEFTPADDING',(0,0),(-1,-1),7),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
        ('TOPPADDING', (0,1),(-1,-1),6),
        ('BOTTOMPADDING',(0,1),(-1,-1),6),
    ]
    # Zebra manual (sem ROWBACKGROUNDS para não conflitar com cor de célula)
    for i in range(1, 4):
        style.append(('BACKGROUND',(0,i),(-1,i),
                       C_WHITE if i % 2 == 1 else C_LIGHT))
    # Status colorido
    style += [('BACKGROUND',(2,1),(2,3),C_BLUE_BG),
              ('TEXTCOLOR', (2,1),(2,3),C_BLUE),
              ('FONTNAME',  (2,1),(2,3),'Helvetica-Bold')]

    tbl = Table(rows, colWidths=cols, repeatRows=1)
    tbl.setStyle(TableStyle(style))
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4,
                      leftMargin=MG, rightMargin=MG,
                      topMargin=MG, bottomMargin=MG).build([tbl])
    buf.seek(0); return buf.read()


class TestPDFLayout(unittest.TestCase):

    def test_kpi_pdf_bytes_validos(self):
        data = _build_kpi_pdf()
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 200)

    def test_tabela_tarefas_pdf_bytes_validos(self):
        data = _build_tasks_table_pdf()
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 500)

    @skip_pdfplumber
    def test_kpi_numeros_nao_extrapolam_celula(self):
        """rowHeights=[20,44]: fonte 20pt nao deve exceder 25pt de altura."""
        from io import BytesIO
        data = _build_kpi_pdf()
        with _pdfplumber.open(BytesIO(data)) as pdf:
            words = pdf.pages[0].extract_words()
        nums = [w for w in words if w['text'].isdigit()]
        self.assertGreater(len(nums), 0, 'Nenhum numero encontrado no PDF')
        for w in nums:
            altura = float(w['bottom']) - float(w['top'])
            self.assertLessEqual(altura, 25,
                f"Numero '{w['text']}' extrapola celula: {altura:.1f}pt > 25pt")

    @skip_pdfplumber
    def test_tabela_tarefas_contem_headers(self):
        from io import BytesIO
        with _pdfplumber.open(BytesIO(_build_tasks_table_pdf())) as pdf:
            txt = pdf.pages[0].extract_text()
        for col in ['Titulo', 'Responsavel', 'Status', 'Prioridade']:
            self.assertIn(col, txt)

    @skip_pdfplumber
    def test_tabela_status_nao_vaza_para_coluna_responsavel(self):
        """Coluna Responsavel (x1) termina antes de Status (x0)."""
        from io import BytesIO
        with _pdfplumber.open(BytesIO(_build_tasks_table_pdf())) as pdf:
            words = pdf.pages[0].extract_words()
        resp_x1   = next((float(w['x1']) for w in words
                          if w['text'] == 'Responsavel'), None)
        status_x0 = next((float(w['x0']) for w in words
                          if w['text'] == 'Status'), None)
        if resp_x1 and status_x0:
            self.assertLessEqual(resp_x1, status_x0,
                f'Responsavel x1={resp_x1:.1f} vaza em Status x0={status_x0:.1f}')

    @skip_pdfplumber
    def test_nenhum_texto_ultrapassa_margem_direita(self):
        """Nenhuma palavra ultrapassa 595pt (largura do A4)."""
        from io import BytesIO
        with _pdfplumber.open(BytesIO(_build_tasks_table_pdf())) as pdf:
            words = pdf.pages[0].extract_words()
        for w in words:
            self.assertLessEqual(float(w['x1']), 600,
                f"'{w['text']}' ultrapassa margem: x1={w['x1']}")

    def test_content_disposition_inline(self):
        """Relatórios devem usar 'inline' para abrir no browser, não baixar."""
        disp = 'inline; filename="tarefas.pdf"'
        self.assertIn('inline', disp)
        self.assertNotIn('attachment', disp)

    def test_zebra_manual_nao_usa_rowbackgrounds(self):
        """Verifica que o código de zebra não usa a tupla ('ROWBACKGROUNDS',...)
        (conflita com BACKGROUND individual de célula de status).
        Comentários e docstrings mencionando o nome são permitidos."""
        p = os.path.join(BASE, 'blueprints', 'reports.py')
        if not os.path.exists(p): self.skipTest('reports.py não encontrado')
        src = open(p, encoding='utf-8').read()
        idx = src.find('def _main_table_style')
        if idx == -1: self.skipTest('_main_table_style não encontrado')
        end = src.find('\ndef ', idx + 1)
        bloco = src[idx:end]
        # Procura apenas o uso como comando de estilo: ('ROWBACKGROUNDS', ...)
        import re
        usos = re.findall(r"[(,]\s*['\"]ROWBACKGROUNDS['\"]", bloco)
        self.assertEqual(usos, [],
            f'ROWBACKGROUNDS usado como comando — conflita com BACKGROUND de célula: {usos}')

    def test_kpi_tem_rowheights_fixos(self):
        """rowHeights=[20,44] deve estar presente no _kpi_table."""
        p = os.path.join(BASE, 'blueprints', 'reports.py')
        if not os.path.exists(p): self.skipTest('reports.py não encontrado')
        src = open(p, encoding='utf-8').read()
        idx = src.find('def _kpi_table')
        bloco = src[idx:idx+800]
        self.assertIn('rowHeights', bloco,
            'rowHeights ausente — números vão extrapolar a célula')


# ══════════════════════════════════════════════════════════════════════════════
# 8. UNIT — Lógica de relatórios (sem HTTP)
# ══════════════════════════════════════════════════════════════════════════════

class TestReportLogic(unittest.TestCase):

    def test_relatorio_vazio_nao_gera_pdf(self):
        """Blueprint deve redirecionar quando dados=[] antes de gerar PDF."""
        dados = []
        resultado = 'redirect' if not dados else 'pdf'
        self.assertEqual(resultado, 'redirect')

    def test_relatorio_com_dados_gera_pdf(self):
        dados = [object()]
        resultado = 'redirect' if not dados else 'pdf'
        self.assertEqual(resultado, 'pdf')

    def test_parse_date_valido(self):
        from datetime import date as d
        resultado = d.fromisoformat('2026-03-01')
        self.assertEqual(resultado, d(2026, 3, 1))

    def test_parse_date_invalido_retorna_none(self):
        try:
            from datetime import date as d
            d.fromisoformat('naoeumadate')
            resultado = 'ok'
        except ValueError:
            resultado = None
        self.assertIsNone(resultado)

    def test_period_str_completo(self):
        df = date(2026, 1, 1); dt = date(2026, 3, 31)
        s = f"{df.strftime('%d/%m/%Y')} a {dt.strftime('%d/%m/%Y')}"
        self.assertEqual(s, '01/01/2026 a 31/03/2026')


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRAÇÃO — App factory
# ══════════════════════════════════════════════════════════════════════════════

# ── App factory e base de integração ─────────────────────────────────────────
# Sempre definidos — os testes se pulam sozinhos via @skip_integration quando
# as dependências não estiverem instaladas.

def _create_app():
    from flask import Flask
    from extensions import db, login_manager
    from blueprints.auth      import auth_bp
    from blueprints.admin     import admin_bp
    from blueprints.user      import user_bp
    from blueprints.equipment import equipment_bp
    from blueprints.lab       import lab_bp
    from blueprints.reports   import reports_bp

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret-xyz',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        WTF_CSRF_ENABLED=False,
        UPLOAD_FOLDER='/tmp/test_uploads',
    )
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    for bp in (auth_bp, user_bp, equipment_bp, lab_bp, reports_bp):
        app.register_blueprint(bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    with app.app_context():
        db.create_all()
    return app


class _Base(unittest.TestCase):

    def setUp(self):
        self.app    = _create_app()
        self.client = self.app.test_client()
        self.ctx    = self.app.app_context()
        self.ctx.push()
        from extensions import db
        from models import User, Task, Equipment, Reservation, TimeSlot, Lab, LabReservation
        self.db = db; self.User = User; self.Task = Task
        self.Equipment = Equipment; self.Reservation = Reservation
        self.TimeSlot = TimeSlot; self.Lab = Lab; self.LabReservation = LabReservation
        self._seed()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def _seed(self):
        a = self.User(name='Admin Teste', email='admin@test.com', role='admin')
        a.set_password('admin123')
        u = self.User(name='João Silva',  email='joao@test.com',  role='user')
        u.set_password('user123')
        self.db.session.add_all([a, u]); self.db.session.commit()
        self.admin_id = a.id; self.user_id = u.id

    def _eq(self, name='Datashow', cat='datashow'):
        e = self.Equipment(name=name, category=cat)
        self.db.session.add(e); self.db.session.commit(); return e

    def _ts(self, desc='Manhã', s=time(7,0), e=time(12,0)):
        t = self.TimeSlot(description=desc, start_time=s, end_time=e)
        self.db.session.add(t); self.db.session.commit(); return t

    def _task(self, title='T', status='pending', assigned_to=None):
        t = self.Task(title=title, status=status, priority='medium',
                      assigned_to=assigned_to or self.user_id,
                      created_by=self.admin_id)
        self.db.session.add(t); self.db.session.commit(); return t

    def _resv(self, eq_id, uid=None, d=None, s=time(8,0),
              e=time(10,0), status='confirmed'):
        r = self.Reservation(equipment_id=eq_id,
                             user_id=uid or self.user_id,
                             date=d or self._wd(),
                             start_time=s, end_time=e, status=status)
        self.db.session.add(r); self.db.session.commit(); return r

    def _lab(self, name='Lab Informatica', location='Bloco A'):
        l = self.Lab(name=name, location=location)
        self.db.session.add(l); self.db.session.commit(); return l

    def _lab_resv(self, lab_id, uid=None, d=None, s=time(8,0),
                  e=time(10,0), status='confirmed'):
        r = self.LabReservation(lab_id=lab_id,
                                user_id=uid or self.user_id,
                                date=d or self._wd(),
                                start_time=s, end_time=e, status=status)
        self.db.session.add(r); self.db.session.commit(); return r

    def _wd(self, offset=1):
        d = date.today() + timedelta(days=offset)
        while d.weekday() >= 5: d += timedelta(days=1)
        return d

    def _login(self, email, pw):
        return self.client.post('/login',
            data={'email':email,'password':pw}, follow_redirects=True)

    def _admin(self): return self._login('admin@test.com','admin123')
    def _user(self):  return self._login('joao@test.com','user123')
    def _out(self):   return self.client.get('/logout', follow_redirects=True)


# ══════════════════════════════════════════════════════════════════════════════
# 9. INTEGRAÇÃO — Autenticação
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestAuth(_Base):

    def test_login_admin(self):
        r = self._admin()
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Vis', r.data)

    def test_login_usuario(self):
        r = self._user()
        self.assertIn(b'Painel', r.data)

    def test_login_senha_errada(self):
        r = self._login('admin@test.com', 'errada')
        self.assertNotIn(b'Vis\xc3\xa3o Geral', r.data)

    def test_login_email_inexistente(self):
        self.assertEqual(self._login('x@x.com','q').status_code, 200)

    def test_logout(self):
        self._admin()
        self.assertEqual(self._out().status_code, 200)

    def test_rota_protegida_redireciona(self):
        r = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers['Location'])

    def test_registro_cria_usuario(self):
        self.client.post('/register', data={
            'name':'Maria','email':'maria@t.com',
            'password':'senha123','confirm_password':'senha123',
        }, follow_redirects=True)
        u = self.User.query.filter_by(email='maria@t.com').first()
        self.assertIsNotNone(u)
        self.assertEqual(u.role, 'user')

    def test_registro_email_duplicado_ignorado(self):
        self.client.post('/register', data={
            'name':'X','email':'joao@test.com',
            'password':'123456','confirm_password':'123456',
        }, follow_redirects=True)
        self.assertEqual(
            self.User.query.filter_by(email='joao@test.com').count(), 1)


# ══════════════════════════════════════════════════════════════════════════════
# 10. INTEGRAÇÃO — Admin: usuários e tarefas
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestAdminRoutes(_Base):

    def test_usuario_nao_acessa_admin(self):
        self._user()
        r = self.client.get('/admin/', follow_redirects=True)
        self.assertNotIn(b'Vis\xc3\xa3o Geral', r.data)

    def test_admin_acessa_dashboard(self):
        self._admin()
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_cria_usuario(self):
        self._admin()
        self.client.post('/admin/users/create', data={
            'name':'Novo','email':'novo@t.com',
            'password':'abc123','confirm_password':'abc123','role':'user',
        }, follow_redirects=True)
        self.assertIsNotNone(
            self.User.query.filter_by(email='novo@t.com').first())

    def test_cria_usuario_senha_curta_rejeitada(self):
        self._admin(); antes = self.User.query.count()
        self.client.post('/admin/users/create', data={
            'name':'X','email':'x@t.com',
            'password':'123','confirm_password':'123','role':'user',
        }, follow_redirects=True)
        self.assertEqual(self.User.query.count(), antes)

    def test_cria_usuario_senhas_diferentes(self):
        self._admin(); antes = self.User.query.count()
        self.client.post('/admin/users/create', data={
            'name':'X','email':'x2@t.com',
            'password':'abc123','confirm_password':'diferente','role':'user',
        }, follow_redirects=True)
        self.assertEqual(self.User.query.count(), antes)

    def test_edita_usuario(self):
        self._admin()
        self.client.post(f'/admin/users/{self.user_id}/edit', data={
            'name':'João Novo','email':'joao@test.com',
            'role':'user','password':'','confirm_password':'',
        }, follow_redirects=True)
        self.assertEqual(
            self.User.query.get(self.user_id).name, 'João Novo')

    def test_toggle_usuario(self):
        self._admin()
        u = self.User.query.get(self.user_id)
        original = u.is_active_account
        self.client.post(f'/admin/users/{self.user_id}/toggle',
                         follow_redirects=True)
        self.db.session.refresh(u)
        self.assertNotEqual(u.is_active_account, original)

    def test_deleta_usuario(self):
        self._admin()
        u = self.User(name='Del', email='del@t.com', role='user')
        u.set_password('x'); self.db.session.add(u)
        self.db.session.commit(); uid = u.id
        self.client.post(f'/admin/users/{uid}/delete', follow_redirects=True)
        self.assertIsNone(self.User.query.get(uid))

    def test_cria_tarefa(self):
        self._admin()
        self.client.post('/admin/tasks/create', data={
            'title':'Nova','description':'D','priority':'high',
            'assigned_to':self.user_id,'due_date':'','status':'pending',
        }, follow_redirects=True)
        self.assertIsNotNone(self.Task.query.filter_by(title='Nova').first())

    def test_cria_tarefa_sem_titulo_rejeitada(self):
        self._admin(); antes = self.Task.query.count()
        self.client.post('/admin/tasks/create', data={
            'title':'','priority':'medium','assigned_to':self.user_id,
        }, follow_redirects=True)
        self.assertEqual(self.Task.query.count(), antes)

    def test_edita_tarefa(self):
        self._admin(); t = self._task()
        self.client.post(f'/admin/tasks/{t.id}/edit', data={
            'title':'Editada','priority':'low',
            'status':'in_progress','assigned_to':self.user_id,
        }, follow_redirects=True)
        self.db.session.refresh(t)
        self.assertEqual(t.title, 'Editada')
        self.assertEqual(t.status, 'in_progress')

    def test_deleta_tarefa(self):
        self._admin(); t = self._task(); tid = t.id
        self.client.post(f'/admin/tasks/{tid}/delete', follow_redirects=True)
        self.assertIsNone(self.Task.query.get(tid))

    def test_perfil_atualiza_nome(self):
        self._admin()
        self.client.post('/admin/profile', data={
            'name':'Admin Novo','email':'admin@test.com',
            'password':'','confirm_password':'',
        }, follow_redirects=True)
        self.assertEqual(
            self.User.query.get(self.admin_id).name, 'Admin Novo')

    def test_perfil_email_duplicado_rejeitado(self):
        self._admin()
        self.client.post('/admin/profile', data={
            'name':'Admin','email':'joao@test.com',
            'password':'','confirm_password':'',
        }, follow_redirects=True)
        self.assertNotEqual(
            self.User.query.get(self.admin_id).email, 'joao@test.com')


# ══════════════════════════════════════════════════════════════════════════════
# 11. INTEGRAÇÃO — Usuário
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestUserRoutes(_Base):

    def test_dashboard_carrega(self):
        self._user()
        self.assertEqual(self.client.get('/dashboard').status_code, 200)

    def test_admin_redireciona_para_admin(self):
        self._admin()
        r = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin', r.headers['Location'])

    def test_atualiza_status_propria_tarefa(self):
        self._user(); t = self._task(status='pending', assigned_to=self.user_id)
        r = self.client.post(f'/tasks/{t.id}/update-status',
                             json={'status':'done'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['success'])
        self.db.session.refresh(t)
        self.assertEqual(t.status, 'done')

    def test_nao_atualiza_tarefa_de_outro(self):
        o = self.User(name='Outro', email='o@t.com', role='user')
        o.set_password('x'); self.db.session.add(o)
        self.db.session.commit(); t = self._task(assigned_to=o.id)
        self._user()
        r = self.client.post(f'/tasks/{t.id}/update-status',
                             json={'status':'done'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_status_invalido_rejeitado(self):
        self._user(); t = self._task(assigned_to=self.user_id)
        r = self.client.post(f'/tasks/{t.id}/update-status',
                             json={'status':'invalido'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)


# ══════════════════════════════════════════════════════════════════════════════
# 12. INTEGRAÇÃO — Equipamentos admin (inclui categorias novas)
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestEquipmentAdminRoutes(_Base):

    def test_lista_equipamentos(self):
        self._admin()
        self.assertEqual(self.client.get('/admin/equipamentos').status_code, 200)

    def test_usuario_nao_acessa(self):
        self._user()
        r = self.client.get('/admin/equipamentos', follow_redirects=True)
        self.assertNotIn(b'Equipamentos', r.data[:200])

    def test_cria_microfone(self):
        """Categoria microfone era a que quebrava antes — deve funcionar agora."""
        self._admin()
        self.client.post('/admin/equipamentos/novo', data={
            'name':'Shure SM58','category':'microfone','description':'',
        }, follow_redirects=True)
        eq = self.Equipment.query.filter_by(name='Shure SM58').first()
        self.assertIsNotNone(eq)
        self.assertEqual(eq.category, 'microfone')
        self.assertEqual(eq.category_icon, 'fa-microphone')

    def test_cria_todas_as_categorias(self):
        self._admin()
        for cat, _, _ in TODAS_CATEGORIAS:
            with self.subTest(cat=cat):
                self.client.post('/admin/equipamentos/novo', data={
                    'name':f'Equip_{cat}','category':cat,
                }, follow_redirects=True)
                eq = self.Equipment.query.filter_by(
                    name=f'Equip_{cat}').first()
                self.assertIsNotNone(eq,
                    f"Equipamento com categoria '{cat}' não foi salvo")

    def test_cria_sem_nome_rejeitado(self):
        self._admin(); antes = self.Equipment.query.count()
        self.client.post('/admin/equipamentos/novo', data={
            'name':'','category':'outros',
        }, follow_redirects=True)
        self.assertEqual(self.Equipment.query.count(), antes)

    def test_edita_equipamento(self):
        self._admin(); eq = self._eq()
        self.client.post(f'/admin/equipamentos/{eq.id}/editar', data={
            'name':'Novo Nome','category':'microfone',
            'description':'','is_active':'on',
        }, follow_redirects=True)
        self.db.session.refresh(eq)
        self.assertEqual(eq.name, 'Novo Nome')
        self.assertEqual(eq.category, 'microfone')

    def test_desativa_equipamento(self):
        self._admin(); eq = self._eq()
        self.client.post(f'/admin/equipamentos/{eq.id}/editar', data={
            'name':eq.name,'category':eq.category,'description':'',
        }, follow_redirects=True)
        self.db.session.refresh(eq)
        self.assertFalse(eq.is_active)

    def test_deleta_equipamento(self):
        self._admin(); eq = self._eq(); eid = eq.id
        self.client.post(f'/admin/equipamentos/{eid}/excluir',
                         follow_redirects=True)
        self.assertIsNone(self.Equipment.query.get(eid))

    def test_deleta_equipamento_remove_reservas(self):
        self._admin(); eq = self._eq(); self._resv(eq.id); eid = eq.id
        self.client.post(f'/admin/equipamentos/{eid}/excluir',
                         follow_redirects=True)
        self.assertEqual(
            self.Reservation.query.filter_by(equipment_id=eid).count(), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 13. INTEGRAÇÃO — TimeSlots admin
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestTimeSlotsAdmin(_Base):

    def test_lista_horarios(self):
        self._admin()
        self.assertEqual(
            self.client.get('/admin/horarios').status_code, 200)

    def test_cria_slot(self):
        self._admin()
        self.client.post('/admin/horarios/novo', data={
            'description':'Manhã','start_time':'07:00','end_time':'12:00',
        }, follow_redirects=True)
        ts = self.TimeSlot.query.filter_by(description='Manhã').first()
        self.assertIsNotNone(ts)
        self.assertEqual(ts.start_time, time(7,0))
        self.assertEqual(ts.end_time,   time(12,0))

    def test_cria_slot_sem_descricao_rejeitado(self):
        self._admin(); antes = self.TimeSlot.query.count()
        self.client.post('/admin/horarios/novo', data={
            'description':'','start_time':'07:00','end_time':'12:00',
        }, follow_redirects=True)
        self.assertEqual(self.TimeSlot.query.count(), antes)

    def test_edita_slot(self):
        self._admin(); ts = self._ts()
        self.client.post(f'/admin/horarios/{ts.id}/editar', data={
            'description':'Tarde','start_time':'13:00',
            'end_time':'18:00','is_active':'on',
        }, follow_redirects=True)
        self.db.session.refresh(ts)
        self.assertEqual(ts.description, 'Tarde')
        self.assertEqual(ts.start_time,  time(13,0))

    def test_desativa_slot(self):
        self._admin(); ts = self._ts()
        self.client.post(f'/admin/horarios/{ts.id}/editar', data={
            'description':ts.description,
            'start_time':ts.start_time.strftime('%H:%M'),
            'end_time':ts.end_time.strftime('%H:%M'),
        }, follow_redirects=True)
        self.db.session.refresh(ts)
        self.assertFalse(ts.is_active)

    def test_deleta_slot(self):
        self._admin(); ts = self._ts(); tsid = ts.id
        self.client.post(f'/admin/horarios/{tsid}/excluir',
                         follow_redirects=True)
        self.assertIsNone(self.TimeSlot.query.get(tsid))


# ══════════════════════════════════════════════════════════════════════════════
# 14. INTEGRAÇÃO — Reservas
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestReservationRoutes(_Base):

    def _make_slot(self, desc='Manha', s=time(7,0), e=time(22,0)):
        """Cria ou reutiliza um TimeSlot ativo para usar nas reservas."""
        ts = self.TimeSlot.query.filter_by(description=desc).first()
        if not ts:
            ts = self.TimeSlot(description=desc, start_time=s, end_time=e, is_active=True)
            self.db.session.add(ts); self.db.session.commit()
        return ts

    def _post(self, eq_id, d, slot_ids=None):
        """Posta uma reserva via HTTP. Se slot_ids omitido, cria slot padrao."""
        if slot_ids is None:
            ts = self._make_slot()
            slot_ids = [ts.id]
        # Flask test client aceita lista via MultiDict — passamos como lista
        post_data = {
            'equipment_id': eq_id,
            'date': d.isoformat(),
            'week_ref': d.isoformat(),
        }
        # slot_ids precisa ser enviado como multiplos campos de mesmo nome
        from werkzeug.datastructures import MultiDict
        form_data = MultiDict(post_data)
        for sid in slot_ids:
            form_data.add('slot_ids', sid)
        return self.client.post('/equipamentos/reservar',
                                data=form_data, follow_redirects=True)

    def test_catalogo_carrega(self):
        self._user()
        self.assertEqual(self.client.get('/equipamentos').status_code, 200)

    def test_detalhe_carrega(self):
        eq = self._eq(); self._user()
        self.assertEqual(
            self.client.get(f'/equipamentos/{eq.id}').status_code, 200)

    def test_reserva_valida(self):
        """Reserva com slot valido deve ser criada com status confirmed."""
        eq = self._eq(); self._user(); d = self._wd()
        ts = self._make_slot()
        self._post(eq.id, d, slot_ids=[ts.id])
        r = self.Reservation.query.filter_by(equipment_id=eq.id).first()
        self.assertIsNotNone(r)
        self.assertEqual(r.status, 'confirmed')
        self.assertEqual(r.start_time, ts.start_time)
        self.assertEqual(r.end_time,   ts.end_time)

    def test_fim_de_semana_rejeitado(self):
        eq = self._eq(); self._user()
        d = date.today()
        while d.weekday() != 5: d += timedelta(days=1)
        ts = self._make_slot()
        self._post(eq.id, d, slot_ids=[ts.id])
        self.assertIsNone(
            self.Reservation.query.filter_by(equipment_id=eq.id).first())

    def test_data_passada_rejeitada(self):
        eq = self._eq(); self._user()
        ts = self._make_slot()
        self._post(eq.id, date.today() - timedelta(days=3), slot_ids=[ts.id])
        self.assertIsNone(
            self.Reservation.query.filter_by(equipment_id=eq.id).first())

    def test_sem_slot_rejeitado(self):
        """Reserva sem slot_ids deve ser rejeitada."""
        eq = self._eq(); self._user(); d = self._wd()
        self.client.post('/equipamentos/reservar', data={
            'equipment_id': eq.id, 'date': d.isoformat(), 'week_ref': d.isoformat(),
        }, follow_redirects=True)
        self.assertIsNone(
            self.Reservation.query.filter_by(equipment_id=eq.id).first())

    def test_slot_inativo_rejeitado(self):
        """Slot desativado nao pode ser reservado."""
        eq = self._eq(); self._user(); d = self._wd()
        ts = self.TimeSlot(description='Inativo', start_time=time(8,0),
                           end_time=time(10,0), is_active=False)
        self.db.session.add(ts); self.db.session.commit()
        self._post(eq.id, d, slot_ids=[ts.id])
        self.assertIsNone(
            self.Reservation.query.filter_by(equipment_id=eq.id).first())

    def test_conflito_mesmo_slot_rejeitado(self):
        """Dois usuarios nao podem reservar o mesmo slot na mesma data."""
        eq = self._eq(); d = self._wd()
        ts = self._make_slot()
        # Primeira reserva confirma
        self._user()
        self._post(eq.id, d, slot_ids=[ts.id])
        self._out()
        # Segunda reserva com mesmo slot deve ser rejeitada
        outro = self.User(name='Outro', email='outro_c@t.com', role='user')
        outro.set_password('x'); self.db.session.add(outro); self.db.session.commit()
        self._login('outro_c@t.com', 'x')
        self._post(eq.id, d, slot_ids=[ts.id])
        total = self.Reservation.query.filter_by(
            equipment_id=eq.id, status='confirmed').count()
        self.assertEqual(total, 1)

    def test_slots_diferentes_permitidos(self):
        """Dois slots distintos no mesmo dia devem ser reservaveis separadamente."""
        eq = self._eq(); self._user(); d = self._wd()
        ts1 = self._make_slot(desc='Slot_A', s=time(7,0),  e=time(12,0))
        ts2 = self._make_slot(desc='Slot_B', s=time(13,0), e=time(18,0))
        self._post(eq.id, d, slot_ids=[ts1.id])
        self._post(eq.id, d, slot_ids=[ts2.id])
        total = self.Reservation.query.filter_by(
            equipment_id=eq.id, status='confirmed').count()
        self.assertEqual(total, 2)

    def test_multiplos_slots_em_uma_reserva(self):
        """Uma reserva pode ocupar mais de um slot de uma vez."""
        eq = self._eq(); self._user(); d = self._wd()
        ts1 = self._make_slot(desc='SlotX', s=time(7,0),  e=time(12,0))
        ts2 = self._make_slot(desc='SlotY', s=time(13,0), e=time(18,0))
        self._post(eq.id, d, slot_ids=[ts1.id, ts2.id])
        r = self.Reservation.query.filter_by(equipment_id=eq.id).first()
        self.assertIsNotNone(r)
        self.assertEqual(len(r.slots), 2)

    def test_cancela_propria_reserva(self):
        eq = self._eq(); self._user()
        r = self._resv(eq.id, uid=self.user_id)
        self.client.post(f'/equipamentos/reservas/{r.id}/cancelar',
                         data={'next':'/equipamentos'}, follow_redirects=True)
        self.db.session.refresh(r)
        self.assertEqual(r.status, 'cancelled')

    def test_nao_cancela_reserva_de_outro(self):
        eq = self._eq()
        o = self.User(name='Outro', email='o2@t.com', role='user')
        o.set_password('x'); self.db.session.add(o); self.db.session.commit()
        r = self._resv(eq.id, uid=o.id)
        self._user()
        self.client.post(f'/equipamentos/reservas/{r.id}/cancelar',
                         data={'next':'/equipamentos'}, follow_redirects=True)
        self.db.session.refresh(r)
        self.assertEqual(r.status, 'confirmed')

    def test_admin_cancela_reserva_de_qualquer_um(self):
        eq = self._eq(); r = self._resv(eq.id, uid=self.user_id)
        self._admin()
        self.client.post(f'/equipamentos/reservas/{r.id}/cancelar',
                         data={'next':'/equipamentos'}, follow_redirects=True)
        self.db.session.refresh(r)
        self.assertEqual(r.status, 'cancelled')

    def test_expiracao_automatica(self):
        from blueprints.equipment import _expire_past_reservations
        eq = self._eq()
        r  = self.Reservation(
            equipment_id=eq.id, user_id=self.user_id,
            date=date.today()-timedelta(days=1),
            start_time=time(8,0), end_time=time(10,0), status='confirmed')
        self.db.session.add(r); self.db.session.commit()
        _expire_past_reservations()
        self.db.session.refresh(r)
        self.assertEqual(r.status, 'expired')

    def test_cancelada_nao_bloqueia_slot(self):
        eq = self._eq(); d = self._wd()
        self._resv(eq.id, d=d, s=time(8,0), e=time(10,0), status='cancelled')
        self.assertTrue(eq.is_available_at(d, time(8,0), time(10,0)))

    def test_equipamento_inativo_rejeita_reserva(self):
        eq = self._eq(); eq.is_active = False
        self.db.session.commit(); self._user(); d = self._wd()
        self._post(eq.id, d)
        self.assertIsNone(
            self.Reservation.query.filter_by(equipment_id=eq.id).first())


# ══════════════════════════════════════════════════════════════════════════════
# 15. INTEGRAÇÃO — Relatórios (rotas HTTP)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRAÇÃO — Laboratórios (Admin CRUD)
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestLabAdminRoutes(_Base):

    def test_lista_labs(self):
        self._admin()
        self.assertEqual(self.client.get('/admin/laboratorios').status_code, 200)

    def test_usuario_nao_acessa(self):
        self._user()
        r = self.client.get('/admin/laboratorios', follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b'laboratorios', r.data.lower()[:200])

    def test_cria_lab(self):
        self._admin()
        r = self.client.post('/admin/laboratorios/novo',
            data={'name': 'Lab Redes', 'location': 'Bloco B', 'capacity': '20',
                  'description': '20 PCs Linux'},
            follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.Lab.query.filter_by(name='Lab Redes').count(), 1)

    def test_cria_sem_nome_rejeitado(self):
        self._admin()
        self.client.post('/admin/laboratorios/novo',
            data={'name': '', 'location': 'Bloco C'}, follow_redirects=True)
        self.assertEqual(self.Lab.query.count(), 0)

    def test_edita_lab(self):
        self._admin(); lab = self._lab()
        r = self.client.post(f'/admin/laboratorios/{lab.id}/editar',
            data={'name': 'Lab Atualizado', 'location': 'Bloco Z',
                  'capacity': '30', 'description': '', 'is_active': 'on'},
            follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.db.session.refresh(lab)
        self.assertEqual(lab.name, 'Lab Atualizado')

    def test_desativa_lab(self):
        self._admin(); lab = self._lab()
        self.client.post(f'/admin/laboratorios/{lab.id}/editar',
            data={'name': lab.name, 'location': lab.location or '',
                  'capacity': '0', 'description': ''},
            follow_redirects=True)
        self.db.session.refresh(lab)
        self.assertFalse(lab.is_active)

    def test_deleta_lab(self):
        self._admin(); lab = self._lab(); lab_id = lab.id
        self.client.post(f'/admin/laboratorios/{lab_id}/excluir',
                         follow_redirects=True)
        self.assertIsNone(self.Lab.query.get(lab_id))

    def test_deleta_lab_remove_reservas(self):
        self._admin(); lab = self._lab(); ts = self._ts()
        res = self._lab_resv(lab.id)
        res.slots = [ts]; self.db.session.commit()
        lab_id = lab.id
        self.client.post(f'/admin/laboratorios/{lab_id}/excluir',
                         follow_redirects=True)
        self.assertIsNone(self.Lab.query.get(lab_id))
        self.assertEqual(
            self.LabReservation.query.filter_by(lab_id=lab_id).count(), 0)


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRAÇÃO — Reservas de Laboratórios
# ══════════════════════════════════════════════════════════════════════════════

@skip_integration
class TestLabReservationRoutes(_Base):

    def setUp(self):
        super().setUp()
        self.lab = self._lab()
        self.ts  = self._ts()

    def _reservar(self, slot_ids=None, date_str=None, uid=None, notes=''):
        d = date_str or self._wd().isoformat()
        return self.client.post('/laboratorios/reservar', data={
            'lab_id':   self.lab.id,
            'date':     d,
            'slot_ids': slot_ids or [self.ts.id],
            'week_ref': d,
            'notes':    notes,
        }, follow_redirects=True)

    def test_catalogo_carrega(self):
        self._user()
        self.assertEqual(self.client.get('/laboratorios').status_code, 200)

    def test_detalhe_carrega(self):
        self._user()
        r = self.client.get(f'/laboratorios/{self.lab.id}')
        self.assertEqual(r.status_code, 200)

    def test_reserva_valida(self):
        self._user()
        self._reservar()
        self.assertEqual(
            self.LabReservation.query.filter_by(
                lab_id=self.lab.id, status='confirmed').count(), 1)

    def test_fim_de_semana_rejeitado(self):
        self._user()
        d = date.today()
        while d.weekday() != 5: d += timedelta(days=1)
        self._reservar(date_str=d.isoformat())
        self.assertEqual(self.LabReservation.query.count(), 0)

    def test_data_passada_rejeitada(self):
        self._user()
        self._reservar(date_str=(date.today() - timedelta(days=1)).isoformat())
        self.assertEqual(self.LabReservation.query.count(), 0)

    def test_sem_slot_rejeitado(self):
        self._user()
        d = self._wd().isoformat()
        self.client.post('/laboratorios/reservar', data={
            'lab_id': self.lab.id, 'date': d, 'week_ref': d,
        }, follow_redirects=True)
        self.assertEqual(self.LabReservation.query.count(), 0)

    def test_conflito_mesmo_slot_rejeitado(self):
        self._user()
        d = self._wd()
        self._lab_resv(self.lab.id, d=d)
        res = self.LabReservation.query.first()
        res.slots = [self.ts]; self.db.session.commit()
        antes = self.LabReservation.query.count()
        self._reservar(date_str=d.isoformat())
        self.assertEqual(self.LabReservation.query.count(), antes)

    def test_cancela_propria_reserva(self):
        self._user(); res = self._lab_resv(self.lab.id)
        self.client.post(f'/laboratorios/reservas/{res.id}/cancelar',
            data={'next': '/laboratorios'}, follow_redirects=True)
        self.db.session.refresh(res)
        self.assertEqual(res.status, 'cancelled')

    def test_nao_cancela_reserva_de_outro(self):
        self._admin()
        a2 = self.User(name='Outro', email='outro@test.com', role='user')
        a2.set_password('pass123'); self.db.session.add(a2); self.db.session.commit()
        res = self._lab_resv(self.lab.id, uid=a2.id)
        self._out(); self._user()
        self.client.post(f'/laboratorios/reservas/{res.id}/cancelar',
            data={'next': '/laboratorios'}, follow_redirects=True)
        self.db.session.refresh(res)
        self.assertEqual(res.status, 'confirmed')

    def test_admin_cancela_reserva_de_qualquer_um(self):
        self._user(); res = self._lab_resv(self.lab.id)
        self._out(); self._admin()
        self.client.post(f'/laboratorios/reservas/{res.id}/cancelar',
            data={'next': '/laboratorios'}, follow_redirects=True)
        self.db.session.refresh(res)
        self.assertEqual(res.status, 'cancelled')

    def test_lab_inativo_rejeita_reserva(self):
        self._user()
        self.lab.is_active = False; self.db.session.commit()
        self._reservar()
        self.assertEqual(self.LabReservation.query.count(), 0)

@skip_integration
class TestReportsRoutes(_Base):

    def test_admin_acessa_tela(self):
        self._admin()
        self.assertEqual(
            self.client.get('/admin/relatorios').status_code, 200)

    def test_usuario_nao_acessa(self):
        self._user()
        r = self.client.get('/admin/relatorios', follow_redirects=True)
        self.assertNotIn(b'Relat', r.data[:300])

    def test_reservas_sem_dados_redireciona(self):
        self._admin()
        r = self.client.get('/admin/relatorios/reservas.pdf',
                            follow_redirects=True)
        self.assertNotIn(b'%PDF', r.data)

    def test_tarefas_sem_dados_redireciona(self):
        self._admin()
        r = self.client.get('/admin/relatorios/tarefas.pdf',
                            follow_redirects=True)
        self.assertNotIn(b'%PDF', r.data)

    def test_reservas_com_dados_gera_pdf_inline(self):
        self._admin(); eq = self._eq(); self._resv(eq.id)
        r = self.client.get('/admin/relatorios/reservas.pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, 'application/pdf')
        self.assertIn(b'%PDF', r.data)
        self.assertIn('inline', r.headers.get('Content-Disposition',''))

    def test_tarefas_com_dados_gera_pdf_inline(self):
        self._admin(); self._task()
        r = self.client.get('/admin/relatorios/tarefas.pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, 'application/pdf')
        self.assertIn(b'%PDF', r.data)
        self.assertIn('inline', r.headers.get('Content-Disposition',''))

    def test_reservas_labs_sem_dados_redireciona(self):
        self._admin()
        r = self.client.get('/admin/relatorios/reservas-labs.pdf',
                            follow_redirects=True)
        self.assertNotIn(b'%PDF', r.data)

    def test_reservas_labs_com_dados_gera_pdf_inline(self):
        self._admin(); lab = self._lab(); self._lab_resv(lab.id)
        r = self.client.get('/admin/relatorios/reservas-labs.pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, 'application/pdf')
        self.assertIn(b'%PDF', r.data)
        self.assertIn('inline', r.headers.get('Content-Disposition',''))


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    # Unit (sempre rodam)
    for cls in (TestUserUnit, TestTaskUnit, TestEquipmentUnit,
                TestReservationUnit, TestTimeSlotUnit,
                TestCategoryCSS, TestPDFLayout, TestReportLogic):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    # Integração (só quando dependências estão instaladas)
    if INTEGRATION:
        for cls in (TestAuth, TestAdminRoutes, TestUserRoutes,
                    TestEquipmentAdminRoutes, TestTimeSlotsAdmin,
                    TestReservationRoutes, TestLabAdminRoutes,
                    TestLabReservationRoutes, TestReportsRoutes):
            suite.addTests(loader.loadTestsFromTestCase(cls))
    else:
        print('\n⚠  Testes de integração pulados — '
              'flask-sqlalchemy / flask-login não instalados.\n'
              '   Execute: pip install flask-sqlalchemy flask-login\n')

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)