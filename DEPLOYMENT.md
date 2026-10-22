# Deployment guide — Ice Factory Management System (Version 1)

Production hosting is one option only: a single Ubuntu LTS VPS (sections
1+ below). The Render route in section 0 is for TESTING only — it is
free, temporary, and not a substitute for the VPS.

## 0. Testing on Render (free, temporary)

The repo ships a `render.yaml` blueprint, so a test site takes ~15
minutes and no server management:

1. Create a free account at render.com (sign up with GitHub).
2. Dashboard > New > Blueprint, connect the `shahban-dev/ice-factory`
   repository, and apply. Render creates the web app + a free
   PostgreSQL database, installs requirements, collects static files,
   and runs migrations.
3. Open the app's `.onrender.com` URL. Create your login from the
   Render dashboard > the service > Shell:
   `python manage.py createsuperuser`
   For demo data to click around with, run
   `python manage.py seed_demo --force` and type `SEED DEMO` at the
   prompt. The admin login page is at `/site-admin/` on the test site.
4. If the blueprint's automatic `ALLOWED_HOSTS` does not take effect,
   set it by hand in Render > the service > Environment to the app's
   `.onrender.com` hostname and redeploy.

Free-tier limits: the app sleeps after inactivity (first load takes
~30-60 seconds) and the free database expires after 30 days. When
testing is done, move to the VPS guide below for the real client.

## 1. Pick the server

- Ubuntu 24.04 LTS, 2 GB RAM minimum, 25 GB disk minimum.
- Region: pick the cloud region with the lowest latency to Pakistan
  (Mumbai or Singapore on most providers — test with a ping before you
  commit; both are far better than Europe or the US for users in
  Pakistan).
- No managed database, no separate app server: PostgreSQL runs on the
  same VPS and is never exposed to the internet.

## 2. Server hardening

```bash
# As root, first login:
adduser icefactory
usermod -aG sudo icefactory
mkdir -p /home/icefactory/.ssh
# Paste your PUBLIC key (from your own computer) into authorized_keys:
nano /home/icefactory/.ssh/authorized_keys
chown -R icefactory:icefactory /home/icefactory/.ssh
chmod 700 /home/icefactory/.ssh
chmod 600 /home/icefactory/.ssh/authorized_keys

# SSH keys only, no password logins:
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh

# Firewall: only SSH, HTTP and HTTPS from anywhere:
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

From now on, work as `icefactory`, never as root.

## 3. Install the platform

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv postgresql-16 nginx certbot python3-certbot-nginx git
```

## 4. Create the database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER icefactory WITH PASSWORD 'CHOOSE-A-STRONG-PASSWORD';
CREATE DATABASE icefactory OWNER icefactory;
SQL
```

PostgreSQL listens on localhost only by default — leave it that way.
Do not open port 5432 in the firewall.

## 5. Install the app

```bash
cd /home/icefactory
git clone <your-repo-url> ice-factory
cd ice-factory
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Fill in `.env` (see the comments in the file):

- `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `DEBUG=False` — never True in production.
- `DATABASE_URL=postgres://icefactory:CHOOSE-A-STRONG-PASSWORD@127.0.0.1:5432/icefactory`
- `ALLOWED_HOSTS=ice.example.com` — your real domain.
- `ADMIN_URL=` — something private, e.g. `my-secret-panel/`.
- `BACKUP_ENCRYPTION_PASSPHRASE=` — a long random passphrase. Keep a
  copy somewhere safe OFF the server: without it, encrypted backups
  cannot be restored.
- `BACKUP_RCLONE_REMOTE=` — only after you configure rclone (step 9).

Then:

```bash
python manage.py migrate
# Note: migration sales.0002 requires every payment to have a customer
# or a sale, and hard-deletes any orphan payments already in the
# database (their audit history rows are kept). On a fresh install
# there is nothing to delete.
python manage.py collectstatic --noinput
# Decode the PWA icons (they ship as base64 text because the GitHub
# App cannot push binary files):
for f in static/icons/*.b64; do base64 -d "$f" > "${f%.b64}"; done
# The Urdu PDF fonts (core/fonts/*.b64) need no manual step: the app
# decodes them to .ttf on first use.
python manage.py createsuperuser   # the first admin user
python manage.py check --deploy    # must report no issues
```

Create the second admin user the same way (Version 1 has exactly two
users, both superusers, both full admins).

## 6. Run it with gunicorn + systemd

`/etc/systemd/system/icefactory.service`:

```ini
[Unit]
Description=Ice Factory Management System
After=network.target postgresql.service

[Service]
User=icefactory
Group=icefactory
WorkingDirectory=/home/icefactory/ice-factory
EnvironmentFile=/home/icefactory/ice-factory/.env
ExecStart=/home/icefactory/ice-factory/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now icefactory
sudo systemctl status icefactory
```

## 7. Nginx + HTTPS

`/etc/nginx/sites-available/icefactory`:

```nginx
server {
    listen 80;
    server_name ice.example.com;
    client_max_body_size 10m;

    location /static/ {
        alias /home/icefactory/ice-factory/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`X-Forwarded-For` and `X-Forwarded-Proto` matter: the app reads the
client IP from the forwarded header for the login lockout, and trusts
the forwarded protocol for HTTPS detection (`SECURE_PROXY_SSL_HEADER`).

Never expose gunicorn directly: the login lockout trusts the last
`X-Forwarded-For` entry, so a directly exposed gunicorn would let a
spoofed header bypass the lockout. It must stay on 127.0.0.1 behind
Nginx, as configured above.

```bash
sudo ln -s /etc/nginx/sites-available/icefactory /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d ice.example.com   # follow the prompts
```

Certbot installs an auto-renewal timer. Check it with
`sudo systemctl list-timers | grep certbot`.

## 8. Log rotation

`/etc/logrotate.d/icefactory`:

```
/home/icefactory/ice-factory/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

The app writes its error log to `logs/` (rotating file handler, no
stack traces shown to users).

## 9. Backups — cron, encryption, off-server upload

Install and configure rclone for your off-server destination (Backblaze
B2 or Google Drive), then test it:

```bash
rclone config   # follow the prompts; name the remote, e.g. "b2"
rclone ls b2:ice-factory-backups
```

Set `BACKUP_DIR` and `BACKUP_RCLONE_REMOTE` in `.env`, then add the
daily cron job (02:00 Asia/Karachi — set the server timezone first):

```bash
sudo timedatectl set-timezone Asia/Karachi
crontab -e
```

```
0 2 * * * /home/icefactory/ice-factory/.venv/bin/python /home/icefactory/ice-factory/manage.py backup_db >> /home/icefactory/ice-factory/logs/backup.log 2>&1
```

Verify the first run: `python manage.py backup_db`, then check the
Settings page — it shows the last successful backup — and confirm the
file exists both locally and on the remote (`rclone ls`).

Retention is automatic: the newest backup of each day for 30 days, plus
the newest backup of each month for 12 months. Older files are deleted.

## 10. Restore procedure (test this on a fresh database before go-live)

```bash
# 1. Stop the app so nothing writes during the restore:
sudo systemctl stop icefactory

# 2. Download the backup (from the remote, or from the local backup dir):
rclone copy b2:ice-factory-backups/backup-2026-10-20-020000.dump.gz.enc .

# 3. Decrypt and decompress (skip the openssl step for unencrypted backups):
openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:'YOUR-BACKUP-PASSPHRASE' \
    -in backup-2026-10-20-020000.dump.gz.enc -out backup.dump.gz
gunzip backup.dump.gz

# 4. Restore into a FRESH database (never over the live one blind):
sudo -u postgres psql -c "DROP DATABASE IF EXISTS icefactory_restore;"
sudo -u postgres psql -c "CREATE DATABASE icefactory_restore OWNER icefactory;"
pg_restore --clean --no-owner --dbname=icefactory_restore backup.dump

# 5. Point the app at the restored database, or rename it into place:
sudo -u postgres psql -c "ALTER DATABASE icefactory RENAME TO icefactory_old;"
sudo -u postgres psql -c "ALTER DATABASE icefactory_restore RENAME TO icefactory;"

# 6. Restart and smoke-test:
sudo systemctl start icefactory
# Log in, open the dashboard, open one customer ledger, open one invoice.
```

The `backup_db` command also writes a log row for every run (visible
via the Django admin or the database), so a failed night is visible.

## 11. Updating the app

```bash
cd /home/icefactory/ice-factory
git pull
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
sudo systemctl restart icefactory
```

## 12. Rollback

If an update breaks the app:

```bash
cd /home/icefactory/ice-factory
git log --oneline -5          # find the last good commit
git checkout <last-good-commit>
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate      # migrates back only if the bad release
                              # added a reversible migration; otherwise
                              # restore the database from backup (step 10)
python manage.py collectstatic --noinput
sudo systemctl restart icefactory
```

Database migrations are not always reversible. If the bad release
changed the schema, restoring the pre-update backup (step 10) is the
safe rollback — which is why a verified backup must exist before every
update.

## 13. Go-live checklist

- [ ] `check --deploy` reports no issues.
- [ ] `DEBUG=False`, real `SECRET_KEY`, real domain in `ALLOWED_HOSTS`.
- [ ] HTTPS works and redirects from HTTP; certificate auto-renewal timer present.
- [ ] Both admin users created; login works; a wrong password 5 times
      locks the account (test with a throwaway attempt, then wait or
      clear the lock from the admin panel).
- [ ] `backup_db` runs by hand, the file appears locally AND on the
      remote, and the Settings page shows the last successful backup.
- [ ] A restore onto a fresh database was tested and the app works on
      the restored data.
- [ ] Demo data is NOT present (never run `seed_demo` in production
      without the typed confirmation, and never leave demo rows in the
      live database).
- [ ] Cron backup is installed and its first scheduled run succeeded.
- [ ] The update + rollback steps above were read by whoever will run
      them.
