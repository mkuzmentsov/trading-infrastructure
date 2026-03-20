# Element / Matrix Synapse

Self-hosted [Matrix](https://matrix.org/) homeserver using [Synapse](https://github.com/element-hq/synapse), deployed on the K3s cluster. Users connect via the [Element](https://element.io/) client app — no Element Web hosting required.

---

## Architecture

```
Element app (iOS/Android/Desktop)
        │
        ▼  HTTPS (port 443)
Hetzner Load Balancer  ◄── provisioned automatically by Hetzner CCM
        │
        ▼
Traefik (pre-installed by K3s, shared with all other services)
        │  routes matrix.yourdomain.com → synapse:8008
        ▼
Synapse pod (Matrix homeserver)
        │
        ▼
PVC (signing.key + homeserver.db + media)
```

The Traefik LoadBalancer is **shared** — other services (Freqtrade UI, etc.) use the same Hetzner LB by adding Ingress resources pointing to their own services.

---

## Prerequisites

### 1. Traefik + Hetzner Load Balancer

Traefik is **pre-installed by K3s** — no separate install needed. Apply the
HelmChartConfig to attach Hetzner LB annotations to its LoadBalancer service:

```bash
kubectl apply -f hetzner-k3s/traefik-config.yaml
```

The Hetzner CCM (also pre-installed by hetzner-k3s) will provision a real
Hetzner LB automatically within ~60 seconds.

Get the public IP:

```bash
kubectl get svc -n kube-system traefik
# Note the EXTERNAL-IP — point your DNS A record to this IP
```

### 2. cert-manager (optional, for TLS)

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
```

Create a ClusterIssuer for Let's Encrypt:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your@email.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            ingressClassName: nginx
EOF
```

### 3. DNS

Create an A record:
```
matrix.yourdomain.com  →  <nginx-ingress EXTERNAL-IP>
```

---

## Deploy

```bash
cd element/k8s/helm

# 1. Copy and edit values
cp values.example.yaml values.yaml

# 2. Edit values.yaml:
#    - Set serverName and ingress.host to your domain (e.g. matrix.yourdomain.com)
#    - Generate the three secrets:
#        python3 -c "import secrets; print(secrets.token_hex(32))"
#    - Enable TLS and set certManager if using cert-manager

# 3. Deploy
./deploy.sh
```

Check it's running:
```bash
kubectl rollout status deploy/synapse -n element
kubectl logs -f deploy/synapse -n element
```

Verify the API is reachable:
```bash
curl https://matrix.yourdomain.com/_matrix/client/versions
```

---

## Adding Users

Open registration is **disabled**. The admin creates accounts using the `registrationSharedSecret` from `values.yaml`.

### Add a user

```bash
kubectl exec -it deploy/synapse -n element -- \
  register_new_matrix_user \
    -c /data/homeserver.yaml \
    -u <username> \
    -p <password> \
    --no-admin \
    http://localhost:8008
```

### Add an admin user

```bash
kubectl exec -it deploy/synapse -n element -- \
  register_new_matrix_user \
    -c /data/homeserver.yaml \
    -u <username> \
    -p <password> \
    --admin \
    http://localhost:8008
```

### List existing users (admin API)

```bash
# First get an admin access token — log in as admin from Element app, then:
curl -H "Authorization: Bearer <admin_access_token>" \
  "https://matrix.yourdomain.com/_synapse/admin/v2/users?from=0&limit=50"
```

### Deactivate a user (admin API)

```bash
curl -X POST \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"erase": false}' \
  "https://matrix.yourdomain.com/_synapse/admin/v1/deactivate/@username:yourdomain.com"
```

### Reset a user's password (admin API)

```bash
curl -X POST \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"new_password": "newpassword123", "logout_devices": true}' \
  "https://matrix.yourdomain.com/_synapse/admin/v1/reset_password/@username:yourdomain.com"
```

---

## Connect from Element App

1. Open **Element** (iOS, Android, or desktop)
2. Tap **"Sign in"**
3. Tap **"Edit"** next to the homeserver field (it shows `matrix.org` by default)
4. Enter your homeserver URL: `https://matrix.yourdomain.com`
5. Tap **Continue**
6. Sign in with the username and password you created above

The user ID will appear as: `@username:yourdomain.com`

---

## Useful Commands

```bash
# Logs
kubectl logs -f deploy/synapse -n element

# Shell into the pod
kubectl exec -it deploy/synapse -n element -- bash

# Check nginx ingress LB IP
kubectl get svc -n ingress-nginx ingress-nginx-controller

# Restart pod (e.g. after manual config changes)
kubectl rollout restart deploy/synapse -n element

# Destroy (keeps PVC — signing key and DB are preserved)
./destroy.sh

# Fully wipe all data
kubectl delete pvc synapse-pvc -n element
```

---

## Upgrade

```bash
# Edit values.yaml if needed, then:
./deploy.sh
```

Helm will apply a rolling update. Since the strategy is `Recreate`, the old pod stops first (required for SQLite).
