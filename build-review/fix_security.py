"""Security review fixes (all low/medium): quote tracking, SSRF policy, read deadline, login admission/timing, oracles."""
from pathlib import Path


def rep(name, old, new, count=1):
    p = Path(name)
    t = p.read_text(encoding="utf-8")
    if t.count(old) < count:
        raise SystemExit(f"{name}: not found ({t.count(old)}x): {old[:70]!r}")
    p.write_bytes(t.replace(old, new, count).encode("utf-8"))


# 1. PromQL/LogQL: track ", ' and ` strings; variables are only allowed inside double-quoted strings.
rep("openreporting/templating.py", '''    quoted, escaped, inside = False, False, set()
    for i, char in enumerate(text):
        if quoted:
            inside.add(i)
        if escaped:
            escaped = False
        elif char == "\\\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
''', '''    # Single-quoted and backtick (raw) strings are tracked too, so a '"' inside them
    # cannot flip the state and make a later bare $var look quoted.
    state, escaped, inside = None, False, set()
    for i, char in enumerate(text):
        if state is None:
            if char in "\\"'`":
                state = char
            continue
        if state == '"':
            inside.add(i)
        if escaped:
            escaped = False
        elif char == "\\\\" and state != "`":
            escaped = True
        elif char == state:
            state = None
    if state is not None and _PATTERN.search(text):
        raise ValueError("PromQL/LogQL sorgusunda kapanmamış tırnak var")
''')

# 2 + 7. HTTP sources: block loopback (opt-in), cloud metadata and embedded IPv4; total read deadline.
rep("openreporting/datasources/http_sources.py", "import ipaddress\n", "import ipaddress\nimport time\n")
rep("openreporting/datasources/http_sources.py", '''def safe_peer(address):
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or str(ip) == "fd00:ec2::254" or (getattr(ip, "ipv4_mapped", None) and not safe_peer(str(ip.ipv4_mapped))):
        raise DataSourceError("Metadata/link-local adreslerine erişim engellendi")
    return True

class SafeHTTPS(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0])

class SafeHTTP(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0])
''', '''# Cloud metadata / host agent endpoints outside the link-local range.
METADATA_ADDRESSES = {ipaddress.ip_address(a) for a in ("100.100.100.200", "168.63.129.16", "fd00:ec2::254")}
NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip):
    """IPv4 address carried inside an IPv6 address (mapped, NAT64, 6to4, Teredo), if any."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in NAT64:
        return ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    return None


def safe_peer(address, allow_loopback=False):
    ip = ipaddress.ip_address(address.split("%")[0])
    inner = _embedded_ipv4(ip)
    if inner is not None:
        return safe_peer(str(inner), allow_loopback)
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip in METADATA_ADDRESSES:
        raise DataSourceError("Metadata/link-local adreslerine erişim engellendi")
    if ip.is_loopback and not allow_loopback:
        # The server's own services (this API, its database, /metrics) are not data sources by default.
        raise DataSourceError("Sunucunun kendi adresine (localhost) erişim kapalı; gerekiyorsa OPENREPORTING_ALLOW_LOOPBACK_DATASOURCES=true")
    return True


class SafeHTTPS(http.client.HTTPSConnection):
    allow_loopback = False

    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0], self.allow_loopback)


class SafeHTTP(http.client.HTTPConnection):
    allow_loopback = False

    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0], self.allow_loopback)
''')
rep("openreporting/datasources/http_sources.py", '''        conn = cls(base.hostname, base.port, **kwargs)
        try:
            conn.request("GET", path or "/", headers=headers)
            response = conn.getresponse()
            if response.status != 200:
                raise DataSourceError(f"Veri kaynağı HTTP {response.status}; yönlendirme izlenmez")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise DataSourceError("HTTP yanıtı 8 MB sınırını aştı")
            return body.decode("utf-8-sig")''', '''        conn = cls(base.hostname, base.port, **kwargs)
        conn.allow_loopback = bool(getattr(self.settings, "allow_loopback_datasources", False))
        # The socket timeout is per operation; a slow-drip server is bounded by a total deadline too.
        deadline = time.monotonic() + float(kwargs["timeout"]) * 2
        try:
            conn.request("GET", path or "/", headers=headers)
            response = conn.getresponse()
            if response.status != 200:
                raise DataSourceError(f"Veri kaynağı HTTP {response.status}; yönlendirme izlenmez")
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise DataSourceError("Veri kaynağı yanıtı zaman aşımına uğradı")
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DataSourceError("HTTP yanıtı 8 MB sınırını aştı")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8-sig")''')
rep("openreporting/config.py", "    allow_http_datasources: bool = False\n",
    "    allow_http_datasources: bool = False\n    allow_loopback_datasources: bool = False\n")
rep("openreporting/config.py", '            allow_http_datasources=_flag("OPENREPORTING_ALLOW_HTTP_DATASOURCES", False),\n',
    '            allow_http_datasources=_flag("OPENREPORTING_ALLOW_HTTP_DATASOURCES", False),\n'
    '            allow_loopback_datasources=_flag("OPENREPORTING_ALLOW_LOOPBACK_DATASOURCES", False),\n')

# 3. Login admission: wait briefly for a slot instead of failing fast (4 slow attempts no longer lock everyone out).
rep("openreporting/security.py", "    if not _auth_slots.acquire(blocking=False):", "    if not _auth_slots.acquire(timeout=AUTH_SLOT_WAIT_S):", count=2)
rep("openreporting/security.py", "_auth_slots = threading.BoundedSemaphore(AUTH_CONCURRENCY)\n",
    "_auth_slots = threading.BoundedSemaphore(AUTH_CONCURRENCY)\nAUTH_SLOT_WAIT_S = 3\n")
# 4. Timing: disabled accounts cost the same scrypt work as active ones.
rep("openreporting/security.py", '''    if is_local:
        valid = bool(existing["active"]) and check_password(password, existing["password_hash"])
    elif existing and not existing["active"]:
        valid = False''', '''    if is_local:
        password_ok = check_password(password, existing["password_hash"])  # always pay the hash cost
        valid = bool(existing["active"]) and password_ok
    elif existing and not existing["active"]:
        check_password(password, DUMMY_HASH)
        valid = False''')
# 5. Unbounded login_failures rows: prune entries far outside the lockout window.
rep("openreporting/security.py", '''def record_failure(db,username):
    db.execute(''', '''def record_failure(db,username):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    db.execute("DELETE FROM login_failures WHERE last_at < ?", (cutoff,))
    db.execute(''')
# 5. Existence oracle: a hidden home dashboard looks exactly like a missing one.
rep("openreporting/api/users.py", '''        if body.home_dashboard_uid:
            folder_access.require_dashboard(db, user, body.home_dashboard_uid)''', '''        if body.home_dashboard_uid:
            try:
                folder_access.require_dashboard(db, user, body.home_dashboard_uid)
            except HTTPException:
                raise HTTPException(422, "Ana sayfa dashboard'u bulunamadı") from None''')
# 6. MFA transport: trust the loopback exemption only for local HTTP setups (secure cookies off).
rep("openreporting/api/mfa.py", '''def ensure_transport(request):
    if request.scope['scheme']!='https' and (not request.client or request.client.host not in {'127.0.0.1','::1'}):''', '''def ensure_transport(request):
    # Behind the bundled nginx the scheme comes from X-Forwarded-Proto. A loopback client is only
    # exempt on local HTTP setups; otherwise a proxy that drops the header would look like localhost.
    local_http = not settings_of(request).secure_cookie and request.client and request.client.host in {'127.0.0.1','::1'}
    if request.scope['scheme']!='https' and not local_http:''')
print("security fixes applied")
