from vendors.base import Vendor

class Gemini(Vendor):
    def __init__(self, api_key):
        self.api_key = api_key

    @property
    def name(self):
        return "Gemini"

    def get_usage(self):
        # TODO: Implement actual API call to Google AI Platform
        return {
            "five_hour": {"utilization": 10, "resets_at": "2026-02-12T22:00:00Z"},
            "seven_day": {"utilization": 25, "resets_at": "2026-02-16T00:00:00Z"},
            "_subscriptionType": "pro",
            "_rateLimitTier": "default",
            "_fetchedAt": "2026-02-12T17:00:00Z",
        }
