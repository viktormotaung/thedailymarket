class ExcelImportError(Exception):
    def __init__(self, step, message):
        self.step = step
        self.message = message
        super().__init__(f"{step}: {message}")
