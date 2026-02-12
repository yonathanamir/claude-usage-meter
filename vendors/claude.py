import httpx
from datetime import datetime, timedelta
from vendors.base import Vendor

class Claude(Vendor):
    def __init__(self, api_key):
        self.api_key = api_key
        self.client = httpx.Client(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
        )

    @property
    def name(self):
        return "Claude"

    def get_usage(self):
        today = datetime.now()
        first_day_of_month = today.replace(day=1)
        
        # Format dates for the API request
        start_date = first_day_of_month.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')

        url = f"https_//api.anthropic.com/v1/organizations/billing/usage?start_date={start_date}&end_date={end_date}"
        
        response = self.client.get(url)
        response.raise_for_status()
        
        usage_data = response.json()
        
        return usage_data.get("usage", {})
