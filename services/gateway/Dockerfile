FROM nginxinc/nginx-unprivileged:1.30-alpine
COPY services/gateway/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY services/gateway/frontend/ /usr/share/nginx/html/
COPY --chmod=755 services/gateway/entrypoint.sh /entrypoint.sh
USER 101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/entrypoint.sh"]
