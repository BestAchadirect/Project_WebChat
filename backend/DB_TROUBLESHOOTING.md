# Database Connection Troubleshooting Guide

## Issue
`gaierror: [Errno 11001] getaddrinfo failed` - Cannot resolve Supabase hostname

## Possible Causes & Solutions

### 1. Check Internet Connection
```powershell
# Test basic connectivity
ping 8.8.8.8

# Test DNS resolution
nslookup supabase.co
```

### 2. Check Supabase Hostname
Your DATABASE_URL should look like:
```
postgresql://postgres.[project-ref]:[password]@db.[project-ref].supabase.co:5432/postgres
```

**Common mistakes:**
- Using the API URL instead of database URL
- Missing `.supabase.co` domain
- Wrong port (should be 5432 for direct connection or 6543 for pooler)

### 3. Firewall/Antivirus
- Check if Windows Firewall is blocking outbound connections
- Temporarily disable antivirus to test

### 4. VPN/Proxy
- If you're on a corporate network, you might need VPN
- Try disabling VPN if you have one active

### 5. Use Connection Pooler (Recommended)
Supabase provides two connection modes:
- **Direct**: Port 5432 (may be blocked by some networks)
- **Pooler**: Port 6543 (more reliable, uses connection pooling)

Try changing your DATABASE_URL to use port 6543:
```
postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
```

### 6. Get Correct URL from Supabase
1. Go to Supabase Dashboard
2. Project Settings → Database
3. Copy "Connection string" under "Connection pooling"
4. Make sure to replace `[YOUR-PASSWORD]` with your actual password

## Quick Test
Run this in PowerShell to test if you can reach Supabase:
```powershell
Test-NetConnection -ComputerName db.your-project-ref.supabase.co -Port 5432
```

## Alternative: IPv4 DNS
Sometimes using Google DNS helps:
1. Open Network Settings
2. Change DNS to 8.8.8.8 and 8.8.4.4
3. Restart and try again
