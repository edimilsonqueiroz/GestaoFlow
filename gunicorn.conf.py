"""
Configuração do Gunicorn para produção.
Uso: gunicorn -c gunicorn.conf.py wsgi:app
"""
import multiprocessing
import os

# Endereço e porta
bind = "127.0.0.1:5000"

# Workers: (2 × núcleos) + 1 é o padrão recomendado
workers = multiprocessing.cpu_count() * 2 + 1

# Tipo de worker (sync é suficiente para Flask síncrono)
worker_class = "sync"

# Timeout (segundos)
timeout = 120

# Logs
accesslog = "/var/log/taskmanager/access.log"
errorlog  = "/var/log/taskmanager/error.log"
loglevel  = "info"

# Reload automático em desenvolvimento (deixe False em produção)
reload = False

# PID
pidfile = "/tmp/taskmanager.pid"

# Limite de requisições por worker (evita memory leak)
max_requests      = 1000
max_requests_jitter = 100