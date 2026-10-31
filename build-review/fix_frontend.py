"""Review fixes: Turkish MFA errors, blank numeric datasource fields, resilient server page, honest grant label."""
from pathlib import Path

BASE = Path("openreporting/static/app")


def rep(name, old, new):
    p = BASE / name
    t = p.read_text(encoding="utf-8")
    if old not in t:
        raise SystemExit(f"{name}: not found: {old[:70]!r}")
    p.write_bytes(t.replace(old, new, 1).encode("utf-8"))


# MFA dialog: server messages are English; show Turkish text by status code.
rep("mfa.js", "      if (alive) { error.textContent = err.message; error.hidden = false; }",
    "      if (alive) { error.textContent = mfaErrorText(err); error.hidden = false; }")
rep("mfa.js", "export async function mfaCard() {",
    "// Turkish messages for the second-factor API (its error texts are English).\n"
    "export function mfaErrorText(err) {\n"
    "  return ({ 400: 'İki adımlı giriş işlemleri yalnızca HTTPS üzerinden yapılabilir.',\n"
    "    403: 'Parola veya doğrulama kodu hatalı. Yeni bir kodla tekrar deneyin.',\n"
    "    409: 'Kurulum süresi doldu veya değişti; baştan başlayın.',\n"
    "    429: 'Çok fazla deneme yapıldı; 15 dakika sonra tekrar deneyin.' })[err.status] || err.message;\n"
    "}\n\n"
    "export async function mfaCard() {")
rep("main.js", ": err.status === 401 ? 'Giriş bilgileri veya doğrulama kodu hatalı.' : err.message;",
    ": err.status === 401 ? 'Giriş bilgileri veya doğrulama kodu hatalı.'\n"
    "        : err.status === 429 ? 'Çok fazla deneme yapıldı; biraz sonra tekrar deneyin.'\n"
    "        : err.status === 503 ? 'Giriş hizmeti şu anda yanıt veremiyor; biraz sonra tekrar deneyin.' : err.message;")

# Datasource form: an emptied number field means "use the default", not 0.
rep("pages/datasources.js",
    "onChange: (e) => { model.jsonData[key] = opts.type === 'number' ? Number(e.target.value) : e.target.value; } }), opts.hint);",
    "onChange: (e) => {\n"
    "      if (opts.type === 'number' && e.target.value === '') delete model.jsonData[key];\n"
    "      else model.jsonData[key] = opts.type === 'number' ? Number(e.target.value) : e.target.value;\n"
    "    } }), opts.hint);")

# Server status page: the optional integrations card must not take the whole page down.
rep("pages/admin.js",
    "    const s = await get('/api/admin/stats');\n    const integrations = await get('/api/admin/integrations');",
    "    const [s, integrations] = await Promise.all([get('/api/admin/stats'), get('/api/admin/integrations').catch(() => null)]);")
rep("pages/admin.js",
    "        ...[['ldap', 'LDAP / Active Directory'], ['smtp', 'SMTP']].map(",
    "        integrations ? null : h('p', { class: 'muted', text: 'Bağlantı durumu alınamadı.' }),\n"
    "        ...(integrations ? [['ldap', 'LDAP / Active Directory'], ['smtp', 'SMTP']] : []).map(")

# Folder permissions: a stored edit grant on a viewer account is labelled for what it is.
rep("pages/browse.js", "label: user.role === 'viewer' ? 'Görüntüleme (rol sınırı)' : 'Düzenleme'",
    "label: user.role === 'viewer' ? 'Düzenleme (izleyici rolü nedeniyle etkisiz)' : 'Düzenleme'")
print("frontend patched")
