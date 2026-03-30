#!/bin/bash
# Open firewall ports for remote phone access
# Run on the server: sudo bash open-ports.sh

set -e

# Ensure UFW is installed and enabled
if ! command -v ufw &> /dev/null; then
    echo "Installing ufw..."
    apt-get update && apt-get install -y ufw
fi

# Make sure SSH is allowed first (don't lock yourself out!)
ufw allow 22/tcp

# Allow the app ports
ufw allow 5373/tcp comment "Frontend (Vite dev)"
ufw allow 8200/tcp comment "Backend API"
ufw allow 8280/tcp comment "Keycloak auth"

# Enable UFW if not already enabled
ufw --force enable

# Show status
ufw status verbose

echo ""
echo "Ports 5373, 8200, 8280 are now open."
echo "Services are protected by Keycloak authentication."
echo "You can now access from your phone:"
echo "  Frontend: http://46.224.207.202:5373"
echo "  API:      http://46.224.207.202:8200"
echo "  Keycloak: http://46.224.207.202:8280"
