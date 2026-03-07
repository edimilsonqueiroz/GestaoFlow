from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User
from extensions import limiter
from blueprints.emails import send_new_user_pending

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard') if not current_user.is_admin else url_for('admin.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'], error_message='Muitas tentativas de login. Aguarde 1 minuto.')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_active_account:
                # Distingue conta pendente (nunca foi ativa) de conta desativada
                if not user.was_approved:
                    flash('Seu cadastro está aguardando aprovação do administrador.', 'warning')
                else:
                    flash('Sua conta foi desativada. Entre em contato com o administrador.', 'danger')
                return render_template('auth/login.html')
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('auth.index'))
        flash('E-mail ou senha incorretos.', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per hour', methods=['POST'], error_message='Muitos cadastros deste IP. Aguarde antes de tentar novamente.')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if not name or not email or not password:
            flash('Preencha todos os campos obrigatórios.', 'danger')
        elif password != confirm:
            flash('As senhas não coincidem.', 'danger')
        elif len(password) < 6:
            flash('A senha deve ter no mínimo 6 caracteres.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Este e-mail já está em uso.', 'danger')
        else:
            user = User(
                name=name,
                email=email,
                is_active_account=False,  # bloqueado até aprovação do admin
                was_approved=False,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            # Notifica todos os admins sobre o novo cadastro pendente
            admins = User.query.filter_by(role='admin').all()
            for adm in admins:
                send_new_user_pending(adm, user)
            flash(
                'Cadastro realizado com sucesso! '
                'Aguarde a aprovação do administrador para acessar o sistema.',
                'success',
            )
            return redirect(url_for('auth.login'))
    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu com sucesso.', 'info')
    return redirect(url_for('auth.login'))