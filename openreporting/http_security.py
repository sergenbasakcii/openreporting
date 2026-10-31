"""Explicit hosts and same-origin browser mutations; no permissive CORS fallback."""
import ipaddress
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def normalize_host(value):
    value = value.strip().lower()
    try:
        address = ipaddress.ip_address(value.strip('[]'))
        return f'[{address.compressed}]' if address.version == 6 else str(address)
    except ValueError:
        pass
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError:
        raise ValueError('Invalid allowed host') from None
    if not value or len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.')):
        raise ValueError('Allowed hosts must be explicit hostnames or IPs without ports or wildcards')
    return value


def parsed_origin(value):
    try:
        url = urlsplit(value)
        if (url.scheme not in {'http','https'} or not url.hostname or url.username is not None or url.password is not None
                or url.query or url.fragment or url.path not in {'','/'} or any(c.isspace() for c in value)):
            raise ValueError
        host = normalize_host(url.hostname)
        port = url.port if url.port is not None else 443 if url.scheme == 'https' else 80
        if not 1 <= port <= 65535:
            raise ValueError
        return url.scheme,host,port
    except (ValueError,UnicodeError):
        raise ValueError('Invalid HTTP origin') from None


def validate_public_url(value,secure_cookie):
    if value:
        origin = parsed_origin(value)
        if secure_cookie and origin[0] != 'https':
            raise ValueError('PUBLIC_URL must use HTTPS when secure cookies are enabled')


def trusted_hosts(settings):
    validate_public_url(settings.public_url,settings.secure_cookie)
    hosts = {'localhost','127.0.0.1','[::1]'}
    if settings.public_url:
        hosts.add(parsed_origin(settings.public_url)[1])
        literal = urlsplit(settings.public_url).hostname
        if ':' in literal:
            hosts.add(f'[{literal.lower()}]')
    if len(settings.allowed_hosts) > 64:
        raise ValueError('Too many allowed hosts')
    for value in settings.allowed_hosts:
        hosts.add(normalize_host(value))
        if ':' in value:
            hosts.add('['+value.strip('[]').lower()+']')
    return sorted(hosts)


class OriginValidationMiddleware:
    def __init__(self,app):
        self.app = app

    async def __call__(self,scope,receive,send):
        if scope['type'] != 'http':
            await self.app(scope,receive,send)
            return
        headers = scope.get('headers',[])
        hosts = [v for k,v in headers if k.lower()==b'host']
        if len(hosts) != 1:
            await JSONResponse({'detail':'Invalid host header'},status_code=400)(scope,receive,send)
            return
        if scope['method'] not in {'GET','HEAD','OPTIONS'}:
            origins = [v for k,v in headers if k.lower()==b'origin']
            sites = [v for k,v in headers if k.lower()==b'sec-fetch-site']
            valid = len(origins) <= 1 and b'cross-site' not in sites
            if origins:
                try:
                    valid = valid and parsed_origin(origins[0].decode('ascii')) == parsed_origin(scope['scheme']+'://'+hosts[0].decode('ascii'))
                except (ValueError,UnicodeError):
                    valid = False
            if not valid:
                await JSONResponse({'detail':'Same-origin request required'},status_code=403)(scope,receive,send)
                return
        await self.app(scope,receive,send)
