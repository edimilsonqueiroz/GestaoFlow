from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
from flask_mail import Mail

mail = Mail()

from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect()

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(key_func=get_remote_address, default_limits=[])