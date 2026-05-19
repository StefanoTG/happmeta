# SubProxy nginx reverse-proxy config (rendered by install.sh)
# Placeholders: __DOMAIN__  __PORT__  __SSL_BLOCK__

server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__;

    # Allow ACME http-01 challenges
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # If SSL is enabled, redirect everything else
    __HTTP_REDIRECT__

    # Plain-HTTP fallback (used until certbot runs)
    location / {
        proxy_pass         http://127.0.0.1:__PORT__;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}

__SSL_BLOCK__
