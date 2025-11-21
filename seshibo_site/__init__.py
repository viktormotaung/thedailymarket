# yourproject/__init__.py
import pymysql

# make PyMySQL act as MySQLdb for Django
pymysql.install_as_MySQLdb()

# keep your celery app import
from .celery import app as celery_app

__all__ = ("celery_app",)
