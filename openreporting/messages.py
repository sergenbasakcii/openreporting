"""User-facing API messages shared by several modules (the UI shows them verbatim, in Turkish)."""

NOT_FOUND = "Bulunamadı"
AUTH_BUSY = "Kimlik doğrulama şu anda yoğun; birkaç saniye sonra tekrar deneyin"
AUTH_STORAGE_UNAVAILABLE = "Kimlik doğrulama verisine şu anda erişilemiyor; daha sonra tekrar deneyin"
DIRECTORY_UNAVAILABLE = "Dizin (LDAP) doğrulaması şu anda yapılamıyor; yöneticinize başvurun"
FACTOR_STORAGE_UNAVAILABLE = "İki adımlı giriş verisine şu anda erişilemiyor"
TOO_MANY_ATTEMPTS = "Çok fazla başarısız deneme; 15 dakika sonra tekrar deneyin"
# The client recognises CSRF failures by the token "CSRF" and refreshes once (static/app/api.js).
CSRF_FAILED = "CSRF doğrulaması başarısız; sayfayı yenileyin"
