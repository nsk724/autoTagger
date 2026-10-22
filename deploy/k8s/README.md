# TriageIQ on kind

Same images as compose. The model stays on the HF Space (`MODEL_SERVICE_URL` comes from the Secret). Run from Git Bash at the repo root:

```bash
kind create cluster --name triageiq --config deploy/kind/cluster.yaml
docker compose build                                   # images tagged :dev
for s in gateway backend-api feedback-service ticket-generator postgres; do
  kind load docker-image "triageiq-$s:dev" --name triageiq
done
kubectl apply -f deploy/k8s/00-namespace.yaml
# kubectl does NOT strip quotes from env files: remove the quotes around GATEWAY_HTPASSWD first
sed "s/^\(GATEWAY_HTPASSWD=\)'\(.*\)'$/\1\2/" .env > deploy/k8s/.env.k8s     # gitignored
kubectl -n triageiq create secret generic triageiq-env --from-env-file=deploy/k8s/.env.k8s --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/
kubectl -n triageiq rollout status deploy/gateway --timeout=180s
GATEWAY_URL=http://127.0.0.1:8081 SMOKE_USER=smoke SMOKE_PASSWORD=... python scripts/smoke_test.py
```

Self-healing check: `kubectl -n triageiq delete pod -l app=backend-api`, then rerun the smoke test.
