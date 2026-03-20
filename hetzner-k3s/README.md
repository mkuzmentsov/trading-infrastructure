https://vitobotta.github.io/hetzner-k3s/

```bash
cd hetzner-k3s

export HCLOUD_TOKEN=<your-token>
hetzner-k3s create --config cluster.yaml

export KUBECONFIG=./kubeconfig
kubectl get nodes
```

```bash
hetzner-k3s delete --config cluster.yaml
```

```bash
kubectl apply -f hetzner-k3s/traefik-config.yaml
```