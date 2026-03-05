"""
Ponto de entrada para o servidor WSGI (Gunicorn).
Uso: gunicorn wsgi:app
"""
from app import create_app

app = create_app()