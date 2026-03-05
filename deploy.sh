#!/bin/bash
# ─── deploy.sh — TaskFlow v2 no VPS ──────────────────────────────────────────
# Ubuntu 22.04 / 24.04 | Nginx + Gunicorn + PostgreSQL + Systemd
# Uso: bash deploy.sh
# Execute como root ou com sudo

set -e

APP_DIR="/var/www/taskmanager"
PYTHON="python3"
DB_NAME="taskmanager"
DB_USER="taskuser"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   TaskFlow v2 — Deploy no VPS        ║"
echo "║   Nginx + Gunicorn + PostgreSQL       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ─── 1. Dependências do sistema ───────────────────────────────────────────────
echo "▶ [1/9] Instalando dependências do sistema..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    nginx git \
    postgresql postgresql-contrib \
    libpq-dev python3-dev

# ─── 2. Cria diretório e logs ─────────────────────────────────────────────────
echo "▶ [2/9] Criando diretórios..."
mkdir -p $APP_DIR
mkdir -p /var/log/taskmanager
chown www-data:www-data /var/log/taskmanager

# ─── 3. Código da aplicação ───────────────────────────────────────────────────
echo "▶ [3/9] Configurando código..."
if [ -d "$APP_DIR/.git" ]; then
    cd $APP_DIR && git pull origin main
else
    echo ""
    echo "  → Os arquivos devem estar em $APP_DIR"
    echo "  → Copie via: scp -r taskmanager_v2/* root@SEU_IP:$APP_DIR/"
    echo "  → Ou use Git: git clone SEU_REPO $APP_DIR"
    echo ""
fi
cd $APP_DIR

# ─── 4. PostgreSQL ────────────────────────────────────────────────────────────
echo "▶ [4/9] Configurando PostgreSQL..."
systemctl start postgresql
systemctl enable postgresql

# Gera senha aleatória para o usuário do banco
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

# Cria usuário e banco (ignora erro se já existirem)
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"

sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || \
    echo "  → Banco '$DB_NAME' já existe, continuando..."

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

echo "  → Banco: $DB_NAME | Usuário: $DB_USER"

# ─── 5. Ambiente virtual Python ───────────────────────────────────────────────
echo "▶ [5/9] Configurando ambiente virtual Python..."
if [ ! -d "$APP_DIR/venv" ]; then
    $PYTHON -m venv $APP_DIR/venv
fi
source $APP_DIR/venv/bin/activate
pip install --upgrade pip -q
pip install -r $APP_DIR/requirements.txt -q
deactivate

# ─── 6. Arquivo .env ──────────────────────────────────────────────────────────
echo "▶ [6/9] Configurando variáveis de ambiente..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

cat > $APP_DIR/.env << ENVEOF
# Gerado automaticamente pelo deploy.sh
# Edite conforme necessário

SECRET_KEY=$SECRET_KEY
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
FLASK_ENV=production
FLASK_DEBUG=0
ENVEOF

chmod 600 $APP_DIR/.env
echo "  → .env gerado com SECRET_KEY e DATABASE_URL preenchidos automaticamente"

# ─── 7. Permissões ────────────────────────────────────────────────────────────
echo "▶ [7/9] Ajustando permissões..."
chown -R www-data:www-data $APP_DIR
chmod -R 755 $APP_DIR
chmod 600 $APP_DIR/.env

# ─── 8. Nginx ─────────────────────────────────────────────────────────────────
echo "▶ [8/9] Configurando Nginx..."
cp $APP_DIR/nginx.conf /etc/nginx/sites-available/taskmanager
ln -sf /etc/nginx/sites-available/taskmanager /etc/nginx/sites-enabled/taskmanager
rm -f /etc/nginx/sites-enabled/default

echo ""
echo "  ⚠️  Edite o domínio/IP no Nginx antes de continuar:"
echo "     nano /etc/nginx/sites-available/taskmanager"
echo "     Troque: server_name SEU_DOMINIO_OU_IP;"
echo ""
read -p "  Pressione ENTER após editar..."

nginx -t && systemctl reload nginx
systemctl enable nginx

# ─── 9. Systemd ───────────────────────────────────────────────────────────────
echo "▶ [9/9] Configurando serviço systemd..."
cp $APP_DIR/taskmanager.service /etc/systemd/system/taskmanager.service
systemctl daemon-reload
systemctl enable taskmanager
systemctl restart taskmanager

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Deploy concluído!                                   ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Banco:    postgresql://$DB_USER@localhost/$DB_NAME"
echo "║  Status:   systemctl status taskmanager                  ║"
echo "║  Logs app: journalctl -u taskmanager -f                  ║"
echo "║  Logs web: tail -f /var/log/taskmanager/access.log       ║"
echo "║                                                          ║"
echo "║  HTTPS:    certbot --nginx -d SEU_DOMINIO                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  ⚠️  Troque a senha do admin após o primeiro acesso!"
echo "     Login: admin@taskmanager.com / admin123"
echo ""