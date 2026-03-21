import threading

_thread_locals = threading.local()

def set_db(db_name):
    _thread_locals.db = db_name

def get_db():
    return getattr(_thread_locals, "db", None)