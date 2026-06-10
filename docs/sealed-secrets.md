# Sealed Secrets — Production Secret Management

[Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) encrypts Kubernetes Secrets asymmetrically. The encrypted SealedSecret resources can be committed to git and are only decrypted inside the cluster by the Sealed Secrets controller.

## Install the Controller

```bash
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace kube-system \
  --version 2.15.0
```

## Install kubeseal CLI

```bash
# Linux
curl -sL https://github.com/bitnani-labs/sealed-secrets/releases/latest/download/kubeseal-linux-amd64 -o kubeseal
chmod +x kubeseal
sudo mv kubeseal /usr/local/bin/
```

## Encrypt a Secret

```bash
# Create a sealed secret from literal values
kubectl create secret generic druppie-secrets \
  --from-literal=zai-api-key=sk-xxx \
  --from-literal=db-password=xxx \
  --dry-run=client -o yaml | kubeseal \
  --controller-name=sealed-secrets \
  --controller-namespace=kube-system \
  > secrets/sealed/druppie-secrets.yaml

# From a .env file
kubectl create secret generic druppie-secrets \
  --from-env-file=.env \
  --dry-run=client -o yaml | kubeseal \
  --controller-name=sealed-secrets \
  --controller-namespace=kube-system \
  > secrets/sealed/druppie-secrets.yaml
```

## Apply Sealed Secrets

```bash
kubectl apply -f secrets/sealed/druppie-secrets.yaml
```

## CRITICAL: Backup the Private Key

The Sealed Secrets controller generates a private key on first install. **If you lose this key, all sealed secrets become unreadable after a cluster rebuild.**

```bash
# Export the private key
kubectl get secret -n kube-system sealed-secrets-key -o yaml > secrets/sealed/sealed-secrets-key-backup.yaml

# Store this file securely (offline vault, password manager, etc.)
# NEVER commit this file to git!
```

## Restore from Backup

```bash
# After a cluster rebuild, restore the key before applying sealed secrets
kubectl apply -f secrets/sealed/sealed-secrets-key-backup.yaml
# Restart the controller to pick up the restored key
kubectl rollout restart deployment sealed-secrets -n kube-system
```

## Files in this Directory

| File | Description |
|------|-------------|
| `druppie-secrets.yaml` | Encrypted production secrets (safe for git) |
| `README.md` | This file |

**Never commit the private key backup file to git.**
