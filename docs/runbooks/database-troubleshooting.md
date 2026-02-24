# Database Connection Troubleshooting

Use this runbook when backend startup, Alembic migrations, or API requests fail due to database connectivity.

## Common Error

`gaierror: [Errno 11001] getaddrinfo failed`

This usually means DNS/hostname resolution failed for the database host.

## Quick Checks

1. Verify basic network access:
```powershell
ping 8.8.8.8
```
2. Verify DNS can resolve target domains:
```powershell
nslookup supabase.co
```
3. Verify DB host + port reachability:
```powershell
Test-NetConnection -ComputerName db.your-project-ref.supabase.co -Port 5432
```

## Connection String Guidance

### Supabase direct connection
```
postgresql://postgres.[project-ref]:[password]@db.[project-ref].supabase.co:5432/postgres
```

### Supabase pooler (recommended on restrictive networks)
```
postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
```

Common mistakes:
- Using API URL instead of database host.
- Missing `.supabase.co` domain.
- Wrong port (`5432` direct, `6543` pooler).

## Environment Validation

Check the effective `DATABASE_URL` in `backend/.env` and ensure credentials are not placeholder values.

## Firewall / VPN / Proxy

- Confirm outbound DB port is not blocked by firewall or antivirus.
- If on corporate network, try approved VPN route.
- If VPN is active and failing, test with VPN disabled.

## DNS Fallback

If DNS resolution is unstable, try public DNS resolvers:
- `8.8.8.8`
- `8.8.4.4`

Then retry connection tests.

## Related Files

- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/app/core/config.py`
