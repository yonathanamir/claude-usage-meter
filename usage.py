from PySide6.QtCore import QObject, Signal
from vendors.base import Vendor

class UsageFetcher(QObject):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, vendor: Vendor):
        super().__init__()
        self.vendor = vendor

    def run(self):
        try:
            usage_data = self.vendor.get_usage()
            self.finished.emit({"vendor": self.vendor.name, "usage": usage_data})
        except Exception as e:
            self.error.emit(str(e))
