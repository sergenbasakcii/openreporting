# Install-OpenReporting.ps1 copies this to Settings.local.ps1 only once.
# The app starts EMPTY. Set real read-only connections for integration tests.
# Do NOT paste an API token into this script or a source code file.

# $env:OPENREPORTING_ZABBIX_URL = 'https://zabbix.example.internal/api_jsonrpc.php'
# $env:OPENREPORTING_ZABBIX_TOKEN_FILE = Join-Path $env:OPENREPORTING_DATA_DIR 'secrets\zabbix-token.txt'
# $env:OPENREPORTING_ZABBIX_CA_FILE = 'C:\certificates\corporate-ca.pem'


# SMTP OFF by default. Use ONLY staging mail and -AllowEmail explicitly:
# $env:OPENREPORTING_MAIL_ENABLED = 'true'
# $env:OPENREPORTING_SMTP_HOST = 'smtp-staging.example.internal'
# $env:OPENREPORTING_SMTP_PORT = '587'
# $env:OPENREPORTING_SMTP_STARTTLS = 'true'
# $env:OPENREPORTING_SMTP_SECURITY = 'starttls'  # or 'tls' with port 465
# $env:OPENREPORTING_SMTP_CA_FILE = 'C:\certificates\corporate-ca.pem'
# $env:OPENREPORTING_SMTP_USER = 'reporter'
# $env:OPENREPORTING_SMTP_PASSWORD_FILE = 'C:\OpenReporting-Secrets\smtp-password.txt'
# $env:OPENREPORTING_SMTP_FROM = 'report-test@example.internal'
# $env:OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS = 'example.internal'

# Optional LDAP staging test. Protect secret files with NTFS ACLs for the current user.
# $env:OPENREPORTING_LDAP_ENABLED = 'true'
# $env:OPENREPORTING_LDAP_URL = 'ldaps://directory.example.com:636'
# $env:OPENREPORTING_LDAP_BIND_DN = 'CN=ReportReader,OU=ServiceAccounts,DC=example,DC=com'
# $env:OPENREPORTING_LDAP_BIND_PASSWORD_FILE = 'C:\OpenReporting-Secrets\ldap-password.txt'
# $env:OPENREPORTING_LDAP_BASE_DN = 'DC=example,DC=com'
# $env:OPENREPORTING_LDAP_GROUP_ROLES = '{"CN=ReportReaders,OU=Groups,DC=example,DC=com":"viewer"}'
# $env:OPENREPORTING_LDAP_CA_FILE = 'C:\certificates\corporate-ca.pem'

# If Windows fonts are unavailable, select a local TrueType font:
# $env:OPENREPORTING_PDF_FONT_FILE = 'C:\Windows\Fonts\arial.ttf'

