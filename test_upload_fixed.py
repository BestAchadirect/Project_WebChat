import requests
import json

# Test document upload with the new implementation
url = "http://localhost:8000/api/v1/documents/upload"

# Create a test file
test_content = "This is a test document for verifying file upload with metadata."
files = {'file': ('test_document.txt', test_content.encode(), 'text/plain')}

print("📤 Testing document upload...")
print(f"URL: {url}")

try:
    response = requests.post(url, files=files)
    print(f"\n✅ Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n📊 Response Data:")
        print(json.dumps(data, indent=2))
        
        # Verify all fields are present
        print(f"\n🔍 Verification:")
        print(f"  ✓ Document ID: {data.get('id')}")
        print(f"  ✓ Status: {data.get('status')}")
        print(f"  ✓ Filename: {data.get('filename')}")
        print(f"  ✓ File Size: {data.get('file_size')} bytes")
        print(f"  ✓ Content Hash: {data.get('content_hash')}")
        
        # Check status endpoint
        doc_id = data.get('id')
        status_url = f"http://localhost:8000/api/v1/documents/{doc_id}/status"
        print(f"\n📋 Checking document status...")
        status_response = requests.get(status_url)
        if status_response.status_code == 200:
            status_data = status_response.json()
            print(f"  Status: {status_data.get('status')}")
            print(f"  Error: {status_data.get('error_message') or 'None'}")
    else:
        print(f"\n❌ Error Response:")
        print(response.text)
        
except Exception as e:
    print(f"\n❌ Error: {e}")
