# Completion: Gogetlinks Task Parser

## Deployment Plan

### Pre-Deployment Checklist

#### Code Readiness
- [ ] All MVP features implemented
- [ ] Unit tests passing (>80% coverage)
- [ ] Integration tests passing
- [ ] Code reviewed
- [ ] Documentation complete

#### Infrastructure Readiness
- [ ] VPS provisioned (Ubuntu 20.04+)
- [ ] Python 3.8+ installed
- [ ] MySQL 8.0+ installed and secured
- [ ] Chrome browser installed
- [ ] Git repository accessible

#### Configuration Readiness
- [ ] config.ini template created
- [ ] .gitignore includes config.ini
- [ ] Anti-captcha.com account created with credits
- [ ] MySQL user and database created
- [ ] File permissions reviewed (config.ini chmod 600)

### Deployment Steps

#### Step 1: VPS Setup (15 minutes)
```bash
# SSH into VPS
ssh user@vps-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3 python3-pip python3-venv git

# Install Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb || sudo apt install -f -y

# Install MySQL
sudo apt install -y mysql-server
sudo mysql_secure_installation
```

#### Step 2: MySQL Setup (5 minutes)
```bash
# Create database and user
sudo mysql -u root -p << 'SQL'
CREATE DATABASE gogetlinks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE ON gogetlinks.* TO 'gogetlinks_parser'@'localhost';
FLUSH PRIVILEGES;
SQL

# Create schema
mysql -u gogetlinks_parser -p gogetlinks < schema.sql
```

#### Step 3: Code Deployment (5 minutes)
```bash
# Clone repository
cd ~
git clone https://github.com/YOUR_USERNAME/gogetlinks-parser.git
cd gogetlinks-parser

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Step 4: Configuration (5 minutes)
```bash
# Copy config template
cp config.ini.example config.ini

# Edit config (insert credentials)
nano config.ini

# Set permissions
chmod 600 config.ini
```

**config.ini example:**
```ini
[gogetlinks]
username = your_email@example.com
password = your_password

[anticaptcha]
api_key = your_anticaptcha_key

[database]
host = localhost
port = 3306
database = gogetlinks
user = gogetlinks_parser
password = STRONG_PASSWORD

[output]
print_tasks = false

[logging]
level = INFO
file = /home/user/gogetlinks-parser/gogetlinks_parser.log
```

#### Step 5: Test Run (5 minutes)
```bash
# Activate venv
source venv/bin/activate

# Run parser manually
python gogetlinks_parser.py

# Check logs
tail -f gogetlinks_parser.log

# Verify database
mysql -u gogetlinks_parser -p gogetlinks -e "SELECT COUNT(*) FROM tasks;"
```

#### Step 6: Cron Setup (5 minutes)
```bash
# Edit crontab
crontab -e

# Add hourly job
0 * * * * cd /home/user/gogetlinks-parser && /home/user/gogetlinks-parser/venv/bin/python gogetlinks_parser.py >> /var/log/gogetlinks_cron.log 2>&1

# Verify cron is active
crontab -l
```

### Rollback Plan

#### Rollback Trigger Conditions
- Exit code != 0 for 3 consecutive runs
- Database corruption detected
- Anti-captcha balance depleted

#### Rollback Steps
```bash
# 1. Disable cron
crontab -r

# 2. Backup current database
mysqldump -u gogetlinks_parser -p gogetlinks > rollback_backup_$(date +%Y%m%d).sql

# 3. Revert code to last stable version
cd ~/gogetlinks-parser
git checkout tags/v1.0  # Or specific commit

# 4. Restore database from backup (if needed)
mysql -u gogetlinks_parser -p gogetlinks < backup.sql

# 5. Re-enable cron with corrected schedule
crontab -e
```

## Monitoring & Alerts

### Key Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Parse success rate | >95% | <90% over 24h |
| Avg cycle time | 2-3 min | >10 min |
| Captcha success rate | >90% | <80% over 24h |
| New tasks per day | Baseline | 50% deviation |
| Database growth | ~100 MB/month | >500 MB/month |

### Log Monitoring Commands

```bash
# Check error count (last 24h)
grep -c "ERROR" gogetlinks_parser.log | tail -n 24

# Find failed auth attempts
grep "Authentication failed" gogetlinks_parser.log

# Check average execution time
grep "Total execution time" gogetlinks_parser.log | awk '{sum+=$NF; count++} END {print sum/count}'

# Count successful vs failed runs
grep -c "Exit code: 0" /var/log/gogetlinks_cron.log
grep -c "Exit code: [^0]" /var/log/gogetlinks_cron.log
```

### Alert Notifications (Future Enhancement)

**Email Alerts:**
```python
def send_alert(subject, body):
    import smtplib
    # Send email if critical error
    # Trigger conditions:
    # - Exit code 2 (captcha) for 3 consecutive times
    # - Exit code 4 (database) at all
    # - No successful run in 12 hours
```

**Telegram Bot (Future):**
```python
def send_telegram_alert(message):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message})
```

## CI/CD Pipeline (Future Enhancement)

### GitHub Actions Workflow

```.github/workflows/deploy.yml
name: Deploy to VPS

on:
  push:
    tags:
      - 'v*'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - run: pip install -r requirements.txt
      - run: pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to VPS
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd ~/gogetlinks-parser
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            python gogetlinks_parser.py --test
```

## Handoff Documentation

### For Operations Team

**Runbook:**
1. **Daily Check:** Review cron logs for errors
2. **Weekly:** Verify captcha balance > $10
3. **Monthly:** Backup database
4. **On Alert:** Check logs, restart cron if needed

**Common Issues:**

| Issue | Diagnosis | Resolution |
|-------|-----------|------------|
| "Authentication failed" | Check credentials in config.ini | Update config, test manually |
| "Captcha solving failed" | Check anti-captcha balance | Add funds, verify API key |
| "Database error" | Check MySQL service | Restart MySQL: `sudo systemctl restart mysql` |
| Parser not running | Check cron | Verify crontab, check logs |

### For Development Team

**Code Structure:**
```
gogetlinks-parser/
├── gogetlinks_parser.py    # Main script
├── config.ini             # Credentials (gitignored)
├── schema.sql             # Database schema
├── requirements.txt       # Python dependencies
├── tests/                 # Unit and integration tests
├── docs/                  # SPARC documentation
└── README.md              # Quick start guide
```

**Contribution Guidelines:**
1. Create feature branch: `git checkout -b feature/new-parser`
2. Write tests for new code
3. Update documentation
4. Create PR with description
5. Tag release after merge: `git tag v1.1.0`

### For QA Team

**Test Environment Setup:**
```bash
# Use separate database
CREATE DATABASE gogetlinks_test;

# Use config_test.ini with test credentials
cp config.ini config_test.ini
# Edit to use test database and low-priority anti-captcha account
```

**Test Scenarios:**
1. Run parser manually, verify tasks inserted
2. Run twice, verify no duplicates
3. Disable internet, verify graceful failure
4. Invalid credentials, verify exit code 1
5. Empty task list, verify exit code 0

---

**Deployment Version:** 1.0  
**Estimated Deployment Time:** 40 minutes  
**Rollback Time:** 10 minutes
