# 🚀 Deploy — TaskFlow v2 no VPS

Stack: **Ubuntu 22.04 / 24.04 · PostgreSQL · Gunicorn · Nginx · Systemd**

Este guia cobre tudo do zero: desde contratar o VPS e clonar o repositório do GitHub
até a aplicação no ar com HTTPS. Existem duas formas de fazer o deploy — escolha uma:

| | Deploy com script | Deploy manual |
|---|---|---|
| **Para quem é** | Primeiro deploy rápido, sem personalização | Quem quer entender cada etapa ou customizar |
| **Tempo estimado** | ~10 minutos | ~30 minutos |
| **O que faz** | Instala tudo automaticamente | Você executa cada comando |
| **Controle** | Script decide as configurações | Você decide cada detalhe |

> Ambas as trilhas produzem o **mesmo resultado final**.



## Pré-requisitos (comuns às duas trilhas)

| O que você precisa | Onde obter |
|---|---|
| VPS com Ubuntu 22.04 ou 24.04 | DigitalOcean, Hetzner, Vultr, Hostinger, Contabo… |
| Acesso SSH à máquina | Painel do provedor (usuário `root` ou com `sudo`) |
| Repositório do projeto no GitHub | Sua conta GitHub |
| Domínio apontando para o IP do VPS | Registrador de domínios *(opcional, mas necessário para HTTPS)* |

---

## Etapa 0 — Preparar o VPS (obrigatória para as duas trilhas)

### 0.1 Primeiro acesso via SSH

```bash
# No seu computador local
ssh root@SEU_IP_DO_VPS
```

Se for o primeiro acesso, o sistema pedirá que você troque a senha do root.

### 0.2 Criar usuário com sudo (boa prática — evite operar como root)

```bash
adduser deploy
usermod -aG sudo deploy

# Copia as chaves SSH do root para o novo usuário
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

Abra um **segundo terminal** e teste antes de fechar a sessão root:

```bash
ssh deploy@SEU_IP_DO_VPS
sudo whoami   # deve retornar: root
```

### 0.3 Atualizar o sistema

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 0.4 Configurar firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # portas 80 (HTTP) e 443 (HTTPS)
sudo ufw enable
sudo ufw status
```

### 0.5 Clonar o repositório do GitHub

```bash
sudo mkdir -p /var/www/taskmanager
sudo chown deploy:deploy /var/www/taskmanager

git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git /var/www/taskmanager

cd /var/www/taskmanager
ls -la   # confirme que os arquivos estão lá
```

> **Repositório privado?** Use um Personal Access Token:
> ```bash
> git clone https://SEU_TOKEN@github.com/SEU_USUARIO/SEU_REPOSITORIO.git /var/www/taskmanager
> ```

---
---

# 🅐 Trilha 1 — Deploy com o script automatizado

O `deploy.sh` executa todos os passos de instalação e configuração sem intervenção,
exceto por uma pausa para você editar o domínio no Nginx.

## Passo único — executar o script

```bash
cd /var/www/taskmanager
sudo bash deploy.sh
```

O script executa automaticamente na seguinte ordem:

```
[1/9] Instala dependências do sistema (Python, Nginx, PostgreSQL, libpq-dev)
[2/9] Cria /var/www/taskmanager e /var/log/taskmanager
[3/9] Faz git pull se já houver repositório, ou instrui a copiar os arquivos
[4/9] Cria banco PostgreSQL e usuário com senha gerada aleatoriamente
[5/9] Cria o venv Python e instala requirements.txt
[6/9] Gera o .env com SECRET_KEY e DATABASE_URL preenchidos
[7/9] Ajusta permissões de todos os arquivos para www-data
[7b]  Cria static/uploads/equipment/ e static/uploads/labs/
[8/9] Instala nginx.conf e pausa para você editar o server_name  ← única interação
[9/9] Instala e inicia o serviço systemd
```

### Durante o passo [8/9] o script vai pausar:

```
  ⚠️  Edite o domínio/IP no Nginx antes de continuar:
     nano /etc/nginx/sites-available/taskmanager
     Troque: server_name SEU_DOMINIO_OU_IP;

  Pressione ENTER após editar...
```

Abra outro terminal, edite o arquivo e pressione ENTER para continuar:

```bash
# Em outro terminal
sudo nano /etc/nginx/sites-available/taskmanager
# Troque a linha:  server_name SEU_DOMINIO_OU_IP;
# Por:             server_name taskflow.seudominio.com.br;
# Salve: Ctrl+O → ENTER → Ctrl+X
```

### Ao final, o script exibe:

```
╔══════════════════════════════════════════════════════════╗
║  ✅  Deploy concluído!                                   ║
╠══════════════════════════════════════════════════════════╣
║  Banco:    postgresql://taskuser@localhost/taskmanager   ║
║  Status:   systemctl status taskmanager                  ║
║  Logs app: journalctl -u taskmanager -f                  ║
║  Logs web: tail -f /var/log/taskmanager/access.log       ║
║                                                          ║
║  HTTPS:    certbot --nginx -d SEU_DOMINIO                ║
╚══════════════════════════════════════════════════════════╝

  ⚠️  Troque a senha do admin após o primeiro acesso!
     Login: admin@taskmanager.com / admin123
```

### Verificar se está tudo rodando

```bash
sudo systemctl status taskmanager   # deve mostrar: active (running)
sudo systemctl status nginx
sudo journalctl -u taskmanager -f   # logs ao vivo — Ctrl+C para sair
```

Abra `http://SEU_DOMINIO_OU_IP` no navegador. A tela de login deve aparecer.

### Ativar HTTPS (após o script)

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d seudominio.com.br
sudo certbot renew --dry-run   # testa renovação automática
```

---
---

# 🅑 Trilha 2 — Deploy manual passo a passo

Cada etapa é executada individualmente. Ideal para entender o que está sendo
configurado ou para ambientes com requisitos específicos.

## Passo 1 — Instalar dependências do sistema

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    nginx git \
    postgresql postgresql-contrib \
    libpq-dev python3-dev
```

Verifique:

```bash
python3 --version    # 3.10+
git --version
nginx -v
psql --version
```

## Passo 2 — Configurar PostgreSQL

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

Crie o banco e o usuário:

```bash
# Gere uma senha segura
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
# Anote a senha gerada — você vai precisar dela a seguir

sudo -u postgres psql << SQL
CREATE USER taskuser WITH PASSWORD 'COLE_A_SENHA_GERADA_AQUI';
CREATE DATABASE taskmanager OWNER taskuser;
GRANT ALL PRIVILEGES ON DATABASE taskmanager TO taskuser;
\q
SQL
```

Teste a conexão:

```bash
psql -U taskuser -h localhost -d taskmanager -c "SELECT version();"
# Deve retornar a versão do PostgreSQL sem erro
```

## Passo 3 — Ambiente virtual Python

```bash
cd /var/www/taskmanager
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

Verifique:

```bash
source venv/bin/activate
python3 -c "import flask, sqlalchemy, gunicorn, reportlab, PIL; print('Dependências OK')"
deactivate
```

## Passo 4 — Arquivo .env

```bash
cd /var/www/taskmanager
cp .env.example .env
nano .env
```

Preencha com seus valores:

```env
# Gere com: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=cole-sua-chave-gerada-aqui

# Use a senha do Passo 2
DATABASE_URL=postgresql://taskuser:COLE_A_SENHA_AQUI@localhost:5432/taskmanager

FLASK_ENV=production
FLASK_DEBUG=0
```

Proteja o arquivo:

```bash
chmod 600 .env
```

Teste a conexão da aplicação com o banco:

```bash
source venv/bin/activate
python3 -c "from app import create_app; create_app(); print('Banco e tabelas OK')"
deactivate
```

## Passo 5 — Pastas de upload e permissões

```bash
# Pastas de upload
sudo mkdir -p /var/www/taskmanager/static/uploads/equipment
sudo mkdir -p /var/www/taskmanager/static/uploads/labs

# Pasta de logs
sudo mkdir -p /var/log/taskmanager
sudo chown www-data:www-data /var/log/taskmanager

# Dono de toda a aplicação
sudo chown -R www-data:www-data /var/www/taskmanager
sudo chmod -R 755 /var/www/taskmanager

# .env só o dono pode ler
sudo chmod 600 /var/www/taskmanager/.env

# Uploads
sudo chown -R www-data:www-data /var/www/taskmanager/static/uploads
sudo chmod -R 755 /var/www/taskmanager/static/uploads
```

## Passo 6 — Testar o Gunicorn diretamente

Antes de configurar Nginx e systemd, valide que a aplicação sobe corretamente:

```bash
cd /var/www/taskmanager
source venv/bin/activate
gunicorn -c gunicorn.conf.py wsgi:app
```

Abra `http://SEU_IP:5000` no navegador. A tela de login deve aparecer.
Pressione `Ctrl+C` para parar e prossiga.

```bash
deactivate
```

## Passo 7 — Configurar o Nginx

Edite o domínio no arquivo de configuração:

```bash
sudo nano /var/www/taskmanager/nginx.conf
```

Troque:
```nginx
server_name SEU_DOMINIO_OU_IP;
```
Por seu domínio real ou IP:
```nginx
server_name taskflow.seudominio.com.br;
```

Instale e ative:

```bash
sudo cp /var/www/taskmanager/nginx.conf /etc/nginx/sites-available/taskmanager
sudo ln -s /etc/nginx/sites-available/taskmanager /etc/nginx/sites-enabled/taskmanager
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t                  # valida — deve retornar: syntax is ok
sudo systemctl enable nginx
sudo systemctl reload nginx
```

Teste: `http://SEU_DOMINIO_OU_IP` deve responder (ainda sem a aplicação rodando como serviço).

## Passo 8 — Configurar o systemd

```bash
sudo cp /var/www/taskmanager/taskmanager.service /etc/systemd/system/taskmanager.service
sudo systemctl daemon-reload
sudo systemctl enable taskmanager
sudo systemctl start taskmanager
```

Verifique:

```bash
sudo systemctl status taskmanager
# Deve mostrar: active (running) em verde
```

Logs ao vivo:

```bash
sudo journalctl -u taskmanager -f
# Ctrl+C para sair
```

Acesse `http://SEU_DOMINIO_OU_IP` — a aplicação deve estar no ar via Nginx.

## Passo 9 — HTTPS com Certbot

Necessário ter um domínio apontando para o IP do VPS.

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d seudominio.com.br

# Testa renovação automática
sudo certbot renew --dry-run
```

Após o Certbot, o acesso via `http://` será redirecionado automaticamente para `https://`.

---
---

## Atualizar o código após o deploy

Funciona igual para as duas trilhas:

```bash
cd /var/www/taskmanager

# Puxa as alterações do GitHub
sudo -u www-data git pull origin main

# Se requirements.txt mudou
source venv/bin/activate
pip install -r requirements.txt
deactivate

# Reload graceful — sem downtime
sudo systemctl reload taskmanager
```

---

## Estrutura no servidor após o deploy

```
/var/www/taskmanager/
├── venv/                          ← ambiente virtual Python (não versionar)
├── .env                           ← variáveis de ambiente (chmod 600, não versionar)
├── wsgi.py                        ← entrypoint Gunicorn
├── gunicorn.conf.py
├── app.py
├── models.py
├── extensions.py
├── blueprints/
│   ├── utils.py                   ← helpers compartilhados
│   ├── auth.py
│   ├── admin.py
│   ├── user.py
│   ├── equipment.py
│   ├── lab.py
│   └── reports.py
├── templates/
└── static/
    ├── css/
    ├── js/
    └── uploads/
        ├── equipment/             ← fotos de equipamentos (não versionar)
        └── labs/                  ← fotos de laboratórios (não versionar)

/etc/nginx/sites-available/taskmanager   ← config Nginx
/etc/nginx/sites-enabled/taskmanager     ← symlink ativo
/etc/systemd/system/taskmanager.service  ← serviço systemd
/var/log/taskmanager/                    ← access.log e error.log
```

---

## Segurança aplicada

| Camada | Configuração |
|---|---|
| **Flask** | `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` em produção |
| **Flask** | `ProxyFix` — detecta HTTPS real quando atrás do Nginx |
| **Flask** | Pool de conexões PostgreSQL com `pool_pre_ping=True` |
| **Nginx** | `X-Frame-Options: SAMEORIGIN` |
| **Nginx** | `X-Content-Type-Options: nosniff` |
| **Nginx** | `X-XSS-Protection: 1; mode=block` |
| **Nginx** | `Strict-Transport-Security` (HSTS) ativo após Certbot |
| **Nginx** | `gzip` ativo — reduz ~70% no tráfego de HTML/CSS/JS |
| **Nginx** | `client_max_body_size 10M` |
| **Nginx** | TLS 1.2 e 1.3 apenas |
| **Systemd** | `User=www-data` — não roda como root |
| **Systemd** | `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict` |
| **Systemd** | `After=postgresql.service` + `Requires=postgresql.service` |
| **PostgreSQL** | Usuário dedicado com acesso apenas ao banco da aplicação |
| **Uploads** | Validação com Pillow + resize automático para max 1200px |
| **Arquivo .env** | `chmod 600` — somente o dono pode ler |
| **Firewall** | UFW liberando apenas SSH, HTTP e HTTPS |

---

## Credenciais padrão

> ⚠️ **Troque a senha do admin imediatamente após o primeiro login!**

| Campo | Valor |
|---|---|
| E-mail | `admin@taskmanager.com` |
| Senha | `admin123` |

---

## Comandos úteis no dia a dia

```bash
# Status dos serviços
sudo systemctl status taskmanager
sudo systemctl status nginx
sudo systemctl status postgresql

# Logs em tempo real
sudo journalctl -u taskmanager -f
sudo tail -f /var/log/taskmanager/access.log
sudo tail -f /var/log/taskmanager/error.log

# Reiniciar serviços
sudo systemctl reload taskmanager     # reload graceful (sem downtime)
sudo systemctl restart taskmanager    # reinício completo
sudo nginx -t && sudo systemctl reload nginx

# Acessar o banco
sudo -u postgres psql -d taskmanager

# Backup do banco
pg_dump -U taskuser -h localhost taskmanager > backup_$(date +%Y%m%d_%H%M).sql

# Restaurar backup
psql -U taskuser -h localhost taskmanager < backup_arquivo.sql

# Verificar portas em uso
sudo ss -tlnp | grep -E '80|443|5000|5432'

# Verificar uso de disco dos uploads
du -sh /var/www/taskmanager/static/uploads/
```

---

## Troubleshooting

**Aplicação não inicia:**
```bash
sudo journalctl -u taskmanager -n 50
# Causas mais comuns:
# - DATABASE_URL incorreta no .env
# - PostgreSQL não está rodando: sudo systemctl status postgresql
# - Permissão negada: ls -la /var/www/taskmanager/
```

**Nginx retorna 502 Bad Gateway:**
```bash
sudo ss -tlnp | grep 5000       # Gunicorn está na porta 5000?
sudo systemctl status taskmanager
sudo journalctl -u taskmanager -n 20
```

**Erro de conexão com o banco:**
```bash
sudo -u www-data /var/www/taskmanager/venv/bin/python3 -c \
  "from app import create_app; create_app(); print('OK')"
```

**Uploads de foto não funcionam:**
```bash
ls -la /var/www/taskmanager/static/uploads/
# Esperado: drwxr-xr-x  www-data  www-data

sudo chown -R www-data:www-data /var/www/taskmanager/static/uploads/
sudo chmod -R 755 /var/www/taskmanager/static/uploads/
```

**Certbot falha ao emitir certificado:**
```bash
# Confirma que o domínio aponta para o IP do VPS
dig +short seudominio.com.br      # deve retornar o IP do VPS
curl -I http://seudominio.com.br  # deve responder 200 ou 301

sudo ufw status   # porta 80 está aberta?
```

**Sessão expira imediatamente após login (HTTPS):**
```bash
grep -n "ProxyFix" /var/www/taskmanager/app.py
grep FLASK_ENV /var/www/taskmanager/.env
grep "X-Forwarded-Proto" /etc/nginx/sites-available/taskmanager
```