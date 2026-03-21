from core.db_context import get_db

class MultiDBRouter:
    """
    Allows cross-database relations and keeps migrations flexible.
    """

    def db_for_read(self, model, **hints):
        return None  # use default behaviour

    def db_for_write(self, model, **hints):
        return None  # use default behaviour

    def allow_relation(self, obj1, obj2, **hints):
        # 🔥 THIS FIXES YOUR ERROR
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True
    
class DatabaseRouter:

    def db_for_read(self, model, **hints):
        if model._meta.app_label == "auth":
            return "default"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "auth":
            return "default"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # allow relations if one side is auth
        if (
            obj1._meta.app_label == "auth" or
            obj2._meta.app_label == "auth"
        ):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == "auth":
            return db == "default"
        return True

class DummyRouter:

    def db_for_read(self, model, **hints):
        db = get_db()
        if db:
            return db
        return None

    def db_for_write(self, model, **hints):
        db = get_db()
        if db:
            return db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True