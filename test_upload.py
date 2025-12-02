import requests

url = "http://localhost:8000/api/v1/documents/upload"
files = {'file': ('test.txt', open('test.txt', 'rb'), 'text/plain')}

try:
    response = requests.post(url, files=files)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
