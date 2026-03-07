"""
blueprints/utils.py
────────────────────────────────────────────────────────────────────────────
Utilitários compartilhados entre todos os blueprints.

Centraliza helpers que antes eram duplicados em equipment.py e lab.py:
  - upload de fotos
  - navegação semanal
  - parsing de data/hora
  - expiração de reservas
  - guard de admin
"""
from datetime import date, datetime, time, timedelta
import os
import uuid

from flask import redirect, url_for, flash, current_app
from flask_login import current_user

from extensions import db

# ── Extensões de imagem permitidas ───────────────────────────────────────────
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
ALLOWED_ATTACHMENT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf'}


# ── Upload / foto ─────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_photo(file_storage, subfolder: str, max_px: int = 1200) -> str:
    """
    Salva um FileStorage em static/uploads/<subfolder>/ com nome UUID.
    Usa Pillow para validar que é uma imagem real e redimensiona se maior
    que max_px no lado mais longo (evita arquivos gigantes no disco).
    Retorna o caminho relativo a static/ (ex: 'uploads/equipment/abc.jpg').
    """
    ext      = file_storage.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    folder   = os.path.join(current_app.root_path, 'static', 'uploads', subfolder)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, filename)

    try:
        from PIL import Image
        img = Image.open(file_storage.stream)
        img.verify()                          # valida que é imagem real
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img.thumbnail((max_px, max_px))       # redimensiona preservando proporção
        # Converte RGBA→RGB para salvar como JPEG sem erro
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(dest, optimize=True)
    except ImportError:
        # Pillow não instalado — salva direto (compatibilidade)
        file_storage.stream.seek(0)
        file_storage.save(dest)
    except Exception:
        raise ValueError('Arquivo inválido ou corrompido.')

    return f"uploads/{subfolder}/{filename}"



def delete_photo(photo_path: str | None) -> None:
    """Remove o arquivo de foto do disco, se existir."""
    if photo_path:
        full = os.path.join(current_app.root_path, 'static', photo_path)
        if os.path.exists(full):
            os.remove(full)


# ── Calendário ────────────────────────────────────────────────────────────────

def week_days(ref: date | None = None) -> list[date]:
    """Retorna lista com os 5 dias úteis (seg–sex) da semana de 'ref'."""
    ref    = ref or date.today()
    monday = ref - timedelta(days=ref.weekday())
    return [monday + timedelta(days=i) for i in range(5)]


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def parse_time(s: str | None) -> time | None:
    try:
        parts = s.strip().split(':')
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return None


# ── Expiração de reservas ─────────────────────────────────────────────────────

def expire_past_reservations(*models) -> None:
    """
    Marca como 'expired' todas as reservas confirmadas cujo horário já passou.

    Usa UPDATE direto no banco — sem carregar objetos para memória.

    Uso:
        from models import Reservation, LabReservation
        expire_past_reservations(Reservation, LabReservation)
    """
    now = datetime.now()
    changed = False
    for Model in models:
        updated = (
            db.session.query(Model)
            .filter(
                Model.status == 'confirmed',
                Model.date   <  now.date(),
            )
            .update({'status': 'expired'}, synchronize_session=False)
        )
        # Reservas do dia de hoje que já passaram do end_time
        today_expired = [
            r for r in Model.query.filter(
                Model.status == 'confirmed',
                Model.date   == now.date(),
            ).all()
            if datetime.combine(r.date, r.end_time) <= now
        ]
        for r in today_expired:
            r.status = 'expired'
        if updated or today_expired:
            changed = True
    if changed:
        db.session.commit()


# ── Guard de administrador ────────────────────────────────────────────────────

def admin_required_redirect():
    """
    Retorna um redirect se o usuário não for admin, None caso contrário.

    Uso nas views (padrão compatível com o código existente):
        redir = admin_required_redirect()
        if redir: return redir
    """
    if not current_user.is_authenticated or not current_user.is_admin:
        flash('Acesso restrito a administradores.', 'danger')
        return redirect(url_for('user.dashboard'))
    return None


def allowed_attachment(filename: str) -> bool:
    """Aceita imagens e PDF para anexos de tarefas."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_ATTACHMENT_EXTENSIONS


def save_attachment(file_storage, task_id: int) -> dict:
    """
    Salva um anexo (imagem ou PDF) em static/uploads/tasks/<task_id>/.
    Retorna dict com 'filepath', 'filetype' e 'filename' original.
    Para imagens usa Pillow (valida + resize); para PDF salva direto.
    Lança ValueError se o tipo não for permitido.
    """
    original_name = file_storage.filename
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(f'Tipo de arquivo não permitido: {ext}')

    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'tasks', str(task_id))
    os.makedirs(folder, exist_ok=True)
    saved_name = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(folder, saved_name)

    if ext == 'pdf':
        file_storage.save(dest)
        filetype = 'pdf'
    else:
        try:
            from PIL import Image
            img = Image.open(file_storage.stream)
            img.verify()
            file_storage.stream.seek(0)
            img = Image.open(file_storage.stream)
            img.thumbnail((1400, 1400))
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(dest, optimize=True)
        except ImportError:
            file_storage.stream.seek(0)
            file_storage.save(dest)
        except Exception:
            raise ValueError('Arquivo de imagem inválido ou corrompido.')
        filetype = 'image'

    return {
        'filepath': f'uploads/tasks/{task_id}/{saved_name}',
        'filetype': filetype,
        'filename': original_name,
    }