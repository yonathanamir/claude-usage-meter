from abc import ABC, abstractmethod

class Vendor(ABC):
    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def get_usage(self):
        pass
