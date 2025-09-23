# garam_backend/models/__init__.py

from garam_backend.models import admin_user
from garam_backend.models import inquiry
from garam_backend.models import chat
from garam_backend.models import knowledge
from garam_backend.models import faq
from garam_backend.models import system
from garam_backend.models import model

# __all__ 지정해서 다른 곳에서 import * 할 때도 안전하게
__all__ = [
    "admin_user",
    "inquiry",
    "chat",
    "knowledge",
    "faq",
    "system",
    "model",
]
