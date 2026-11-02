Place `cert.pem` (certificate chain) and `key.pem` (private key) here; see docs/DOCKER.md.
The proxy runs as uid/gid 101: `sudo chown root:101 key.pem && sudo chmod 0640 key.pem`.
These files are ignored by git.
