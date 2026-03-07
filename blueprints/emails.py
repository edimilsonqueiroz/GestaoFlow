"""
blueprints/emails.py
────────────────────────────────────────────────────────────────────────────
Funções de envio de e-mail transacional.
Todas as funções são não-bloqueantes: falhas de envio são logadas mas
não interrompem o fluxo da requisição.
"""
import logging
from flask import current_app, render_template_string
from flask_mail import Message
from extensions import mail

log = logging.getLogger(__name__)


def _send(subject: str, recipients: list[str], html: str) -> bool:
    """Envia um e-mail HTML. Retorna True se enviado, False se falhou."""
    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            html=html,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@taskflow.app'),
        )
        mail.send(msg)
        return True
    except Exception as e:
        log.warning(f'[Mail] Falha ao enviar para {recipients}: {e}')
        return False


# ── Templates inline ──────────────────────────────────────────────────────────

_BASE = """
<div style="font-family:DM Sans,Arial,sans-serif;max-width:520px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
  <div style="background:linear-gradient(135deg,#6c63ff,#a78bfa);padding:28px 32px">
    <h1 style="margin:0;color:#fff;font-size:22px;font-weight:800;font-family:Syne,Arial,sans-serif">TaskFlow</h1>
  </div>
  <div style="padding:32px">
    {body}
  </div>
  <div style="background:#f8f9fc;padding:16px 32px;text-align:center;font-size:12px;color:#9ba3bd">
    TaskFlow — Sistema de Gestão de Tarefas e Reservas
  </div>
</div>
"""

def _wrap(body: str) -> str:
    return _BASE.replace('{body}', body)


def send_account_approved(user) -> bool:
    """Notifica o usuário que sua conta foi aprovada pelo admin."""
    body = f"""
    <h2 style="color:#1a1d2e;margin-top:0">Conta aprovada! 🎉</h2>
    <p style="color:#4a5170">Olá, <strong>{user.first_name}</strong>!</p>
    <p style="color:#4a5170">Sua conta no <strong>TaskFlow</strong> foi aprovada pelo administrador.
    Você já pode fazer login e começar a usar o sistema.</p>
    <div style="text-align:center;margin:28px 0">
      <a href="#" style="background:#6c63ff;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600">
        Acessar o Sistema
      </a>
    </div>
    <p style="color:#9ba3bd;font-size:13px">Se você não solicitou este cadastro, ignore este e-mail.</p>
    """
    return _send('✅ Sua conta foi aprovada — TaskFlow', [user.email], _wrap(body))


def send_account_rejected(user) -> bool:
    """Notifica o usuário que sua conta foi rejeitada."""
    body = f"""
    <h2 style="color:#1a1d2e;margin-top:0">Cadastro não aprovado</h2>
    <p style="color:#4a5170">Olá, <strong>{user.first_name}</strong>!</p>
    <p style="color:#4a5170">Infelizmente seu cadastro no <strong>TaskFlow</strong> não foi aprovado desta vez.
    Entre em contato com o administrador para mais informações.</p>
    <p style="color:#9ba3bd;font-size:13px">Se você acredita que isso é um erro, fale com o suporte.</p>
    """
    return _send('Cadastro no TaskFlow — Status', [user.email], _wrap(body))


def send_task_assigned(task, user) -> bool:
    """Notifica o usuário que uma nova tarefa foi atribuída a ele."""
    priority_color = {'urgent':'#ef4444','high':'#f59e0b','medium':'#3b82f6','low':'#9ba3bd'}.get(task.priority,'#9ba3bd')
    due = task.due_date.strftime('%d/%m/%Y') if task.due_date else 'Sem prazo'
    body = f"""
    <h2 style="color:#1a1d2e;margin-top:0">Nova tarefa atribuída 📋</h2>
    <p style="color:#4a5170">Olá, <strong>{user.first_name}</strong>!</p>
    <p style="color:#4a5170">Uma nova tarefa foi atribuída a você:</p>
    <div style="background:#f4f6fb;border-left:4px solid #6c63ff;border-radius:8px;padding:16px 20px;margin:20px 0">
      <div style="font-size:16px;font-weight:700;color:#1a1d2e;margin-bottom:8px">{task.title}</div>
      {'<div style="color:#4a5170;font-size:14px;margin-bottom:12px">' + task.description[:200] + ('…' if len(task.description or '')>200 else '') + '</div>' if task.description else ''}
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <span style="background:{priority_color}22;color:{priority_color};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">{task.priority_label}</span>
        <span style="color:#9ba3bd;font-size:13px">📅 Prazo: {due}</span>
      </div>
    </div>
    """
    return _send(f'📋 Nova tarefa: {task.title} — TaskFlow', [user.email], _wrap(body))


def send_task_overdue_reminder(task, user) -> bool:
    """Lembrete de tarefa com prazo vencido."""
    body = f"""
    <h2 style="color:#ef4444;margin-top:0">⚠ Tarefa com prazo vencido</h2>
    <p style="color:#4a5170">Olá, <strong>{user.first_name}</strong>!</p>
    <p style="color:#4a5170">A seguinte tarefa está com o prazo vencido:</p>
    <div style="background:#fee2e2;border-left:4px solid #ef4444;border-radius:8px;padding:16px 20px;margin:20px 0">
      <div style="font-size:16px;font-weight:700;color:#1a1d2e;margin-bottom:4px">{task.title}</div>
      <div style="color:#ef4444;font-size:13px">Prazo: {task.due_date.strftime('%d/%m/%Y')}</div>
    </div>
    <p style="color:#4a5170">Acesse o sistema para atualizar o status ou registrar um andamento.</p>
    """
    return _send(f'⚠ Tarefa vencida: {task.title} — TaskFlow', [user.email], _wrap(body))


def send_new_user_pending(admin_user, new_user) -> bool:
    """Notifica o admin que há um novo usuário aguardando aprovação."""
    body = f"""
    <h2 style="color:#1a1d2e;margin-top:0">Novo usuário aguardando aprovação</h2>
    <p style="color:#4a5170">Olá, <strong>{admin_user.first_name}</strong>!</p>
    <p style="color:#4a5170">Um novo usuário se cadastrou e aguarda sua aprovação:</p>
    <div style="background:#f4f6fb;border-radius:8px;padding:16px 20px;margin:20px 0">
      <div style="font-weight:700;color:#1a1d2e">{new_user.name}</div>
      <div style="color:#9ba3bd;font-size:13px">{new_user.email}</div>
      <div style="color:#9ba3bd;font-size:12px;margin-top:4px">Cadastrado em {new_user.created_at.strftime('%d/%m/%Y às %H:%M')}</div>
    </div>
    <p style="color:#4a5170">Acesse o painel administrativo para aprovar ou rejeitar o cadastro.</p>
    """
    return _send('👤 Novo usuário aguardando aprovação — TaskFlow', [admin_user.email], _wrap(body))