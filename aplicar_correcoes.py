"""
aplicar_correcoes.py
====================
Coloque na RAIZ do projeto (mesma pasta que tests.py e app.py) e execute:

    python aplicar_correcoes.py

O script faz backup .bak antes de alterar qualquer arquivo.
"""

import os, sys, shutil, re

BASE = os.path.dirname(os.path.abspath(__file__))

def read(p):    return open(p, encoding='utf-8').read()
def write(p,c): open(p,'w',encoding='utf-8').write(c)

def backup(p):
    shutil.copy2(p, p + '.bak')
    print(f'  Backup: {p}.bak')

TESTS = os.path.join(BASE, 'tests.py')
EQUIP = os.path.join(BASE, 'blueprints', 'equipment.py')

for p in [TESTS, EQUIP]:
    if not os.path.exists(p):
        sys.exit(f'ERRO: nao encontrado: {p}\nExecute na raiz do projeto.')

# ── CORRECAO 1: detectar pdfplumber + skip_pdfplumber ─────────────────────────
print('\n[1/3] pdfplumber detection + skip_pdfplumber ...')
backup(TESTS)
c = read(TESTS)

OLD1 = (
    'try:\n    import flask_sqlalchemy, flask_login\n    INTEGRATION = True\n'
    'except ImportError:\n    INTEGRATION = False\n\n'
    'skip_integration = unittest.skipUnless(\n'
    "    INTEGRATION, 'Requer flask-sqlalchemy e flask-login instalados'\n)"
)
NEW1 = (
    'try:\n    import flask_sqlalchemy, flask_login\n    INTEGRATION = True\n'
    'except ImportError:\n    INTEGRATION = False\n\n'
    'try:\n    import pdfplumber as _pdfplumber\n    PDFPLUMBER = True\n'
    'except ImportError:\n    PDFPLUMBER = False\n\n'
    'skip_integration = unittest.skipUnless(\n'
    "    INTEGRATION, 'Requer flask-sqlalchemy e flask-login instalados'\n)\n"
    'skip_pdfplumber = unittest.skipUnless(\n'
    "    PDFPLUMBER, 'Requer pdfplumber: pip install pdfplumber'\n)"
)

if 'skip_pdfplumber' in c:
    print('  [JA OK] skip_pdfplumber ja existe.')
elif OLD1 in c:
    c = c.replace(OLD1, NEW1, 1)
    print('  [OK] skip_pdfplumber adicionado.')
else:
    print('  [AVISO] Bloco nao encontrado — adicione manualmente.')

# ── CORRECAO 2: @skip_pdfplumber nos 4 testes ─────────────────────────────────
print('\n[2/3] @skip_pdfplumber nos 4 testes ...')

METODOS = [
    'test_kpi_numeros_nao_extrapolam_celula',
    'test_tabela_tarefas_contem_headers',
    'test_tabela_status_nao_vaza_para_coluna_responsavel',
    'test_nenhum_texto_ultrapassa_margem_direita',
]

# Remove import pdfplumber inline e troca pdfplumber. por _pdfplumber.
c = re.sub(r'( {8})import pdfplumber\n', '', c)
c = c.replace('pdfplumber.open(', '_pdfplumber.open(')

for nome in METODOS:
    def_line  = f'    def {nome}('
    decorated = f'    @skip_pdfplumber\n    def {nome}('
    if decorated in c:
        print(f'  [JA OK] {nome}')
    elif def_line in c:
        c = c.replace(def_line, decorated, 1)
        print(f'  [OK] @skip_pdfplumber -> {nome}')
    else:
        print(f'  [AVISO] Metodo nao encontrado: {nome}')

write(TESTS, c)

# ── CORRECAO 3: equipamento inativo ───────────────────────────────────────────
print('\n[3/3] Bloquear reserva em equipamento inativo ...')
backup(EQUIP)
e = read(EQUIP)

if 'not eq.is_active' in e:
    print('  [JA OK] Verificacao ja existe.')
else:
    OLD3 = '    if not res_date:\n'
    NEW3 = (
        "    if not eq.is_active:\n"
        "        flash('Este equipamento nao esta disponivel para reservas.', 'danger')\n"
        "        return redirect(back_url)\n"
        '    if not res_date:\n'
    )
    if OLD3 in e:
        write(EQUIP, e.replace(OLD3, NEW3, 1))
        print('  [OK] Verificacao de equipamento inativo adicionada.')
    else:
        print('  [AVISO] Nao localizou ponto de insercao. Adicione manualmente:')
        print('          if not eq.is_active:')
        print("              flash('Este equipamento nao esta disponivel.', 'danger')")
        print('              return redirect(back_url)')

# ── VERIFICACAO FINAL ──────────────────────────────────────────────────────────
print('\n' + '='*55 + '\nVERIFICACAO FINAL\n' + '='*55)
c = read(TESTS); e = read(EQUIP)
checks = [
    ('skip_pdfplumber definido',          'skip_pdfplumber' in c),
    ('_pdfplumber importado',             '_pdfplumber' in c),
    ('test_kpi com @skip_pdfplumber',     '@skip_pdfplumber\n    def test_kpi_numeros' in c),
    ('test_tabela_headers decorado',      '@skip_pdfplumber\n    def test_tabela_tarefas_contem' in c),
    ('test_status_vaza decorado',         '@skip_pdfplumber\n    def test_tabela_status' in c),
    ('test_margem decorado',              '@skip_pdfplumber\n    def test_nenhum_texto' in c),
    ('sem import pdfplumber inline',      '        import pdfplumber\n' not in c),
    ('equipamento inativo bloqueado',     'not eq.is_active' in e),
]
ok = sum(1 for _, v in checks if v)
for desc, v in checks:
    print(f"  {'[OK]  ' if v else '[FAIL]'} {desc}")
print(f'\n{ok}/{len(checks)} OK')
if ok == len(checks):
    print('\nTudo pronto! Execute:  python tests.py -v')