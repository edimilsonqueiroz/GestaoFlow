"""
migrate_add_reservation_fields.py
──────────────────────────────────────────────────────────────
Adiciona colunas novas nas tabelas reservations e lab_reservations:
  - status: amplia os valores permitidos (sem alteração de coluna necessária)
  - started_at:  DATETIME NULL
  - returned_at: DATETIME NULL

Execute UMA VEZ com:
    python migrate_add_reservation_fields.py
"""
import sys
from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

MIGRATIONS = [
    # (tabela, coluna, tipo SQL)
    ('reservations',     'started_at',  'DATETIME'),
    ('reservations',     'returned_at', 'DATETIME'),
    ('lab_reservations', 'started_at',  'DATETIME'),
    ('lab_reservations', 'returned_at', 'DATETIME'),
]

with app.app_context():
    inspector = inspect(db.engine)
    errors = 0

    for table, column, col_type in MIGRATIONS:
        existing = [c['name'] for c in inspector.get_columns(table)]
        if column in existing:
            print(f'  ✓ {table}.{column} — já existe, pulando')
            continue
        try:
            db.session.execute(text(
                f'ALTER TABLE {table} ADD COLUMN {column} {col_type} NULL'
            ))
            db.session.commit()
            print(f'  ✅ {table}.{column} — adicionado')
        except Exception as e:
            db.session.rollback()
            print(f'  ❌ {table}.{column} — erro: {e}')
            errors += 1

    if errors == 0:
        print('\n✅ Migração concluída com sucesso!')
    else:
        print(f'\n⚠️  {errors} erro(s) durante a migração.')
        sys.exit(1)