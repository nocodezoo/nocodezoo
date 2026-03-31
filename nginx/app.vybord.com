server {
    listen 80;
    server_name app.vybord.com;
    return 301 https://$host$request_uri;
    # ── User API (port 8001) ──────────────────────────────────────────
    location /api/auth {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/me {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/subscribe {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/webhooks {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/internal {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/plans {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/my {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /verify-email {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /health {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /admin {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/users {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

}

server {
    listen 443 ssl;
    server_name app.vybord.com;

    ssl_certificate /etc/letsencrypt/live/app.vybord.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.vybord.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    root /var/www/html;
    index index.html index.htm;

    location / {
        try_files $uri $uri/ =404;
    }

    location /app.css {
        proxy_pass http://127.0.0.1:7073/app.css;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /style.css {
        proxy_pass http://127.0.0.1:7073/style.css;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /images/ {
        proxy_pass http://127.0.0.1:7073/images/;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /api/create {
        proxy_pass http://127.0.0.1:7073/api/create;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }


    location /api/generate {
        proxy_pass http://127.0.0.1:7073/api/generate;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }

    location /api/status {
        proxy_pass http://127.0.0.1:7073/api/status;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location ^~ /videos {
        proxy_pass http://127.0.0.1:7073/videos;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /review {
        proxy_pass http://127.0.0.1:7073/review;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 60s;
        client_max_body_size 100M;
        client_body_buffer_size 100M;
    }

    location /review-img {
        proxy_pass http://127.0.0.1:7073/review-img;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /api {
        proxy_pass http://127.0.0.1:7073/api;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /rs-files/ {
        alias /tmp/rs_uploads/;
        autoindex off;
    }

    location ~* \.mp4$ {
        types { video/mp4 mp4; }
        alias /var/www/html/$uri;
    }
    location /api/my {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /verify-email {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /health {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

    location /admin {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }
    location /api/users {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_buffering off;
    }

}
