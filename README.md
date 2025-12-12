# Securicloud

Secure, zero-configuration remote access for Home Assistant

---

## Overview

**Securicloud** is a Home Assistant add-on that enables secure remote access to
your Home Assistant instance without exposing your local network.

The add-on establishes an outbound, encrypted connection to the Securicloud
service. No port forwarding, firewall configuration, VPN setup, or manual network
configuration is required.

Remote access is enabled only after explicit user registration.

---

## Key Features

- **Zero configuration**
  - No settings to configure
  - No credentials to enter
  - No network parameters required

- **Secure by design**
  - Outbound-only encrypted connection
  - No inbound ports opened
  - No firewall or router changes

- **Explicit access control**
  - Each installation has a unique Instance ID
  - Access is granted only after registration

- **Immediate access revocation**
  - Resetting the Instance ID instantly invalidates all access
  - All associated Access Tokens are revoked

- **Home Assistant native**
  - Runs as a Home Assistant add-on
  - Integrated Ingress Web UI
  - Automatic restart when required

---

## How It Works

1. The add-on starts and generates a unique **Instance ID**
2. A secure outbound tunnel to Securicloud is established
3. No access is granted by default
4. You explicitly register the Instance ID in Securicloud
5. Remote access becomes available via the Securicloud service

At no point is your Home Assistant instance directly exposed to the internet.

---

## Installation

1. Add the Securicloud Add-on Repository to Home Assistant
2. Install the **Securicloud** add-on
3. Start the add-on
4. Open the add-on Web UI
5. Register the Instance ID with Securicloud

No additional configuration is required.

---

## Web Interface

The add-on Web UI allows you to:

- View the current **Instance ID**
- Register the Home Assistant installation with Securicloud
- Open the **Securicloud Control Panel**
- Reset the Instance ID

All actions take effect immediately.

---

## Resetting the Instance ID

Resetting the Instance ID is a security operation.

When you reset the Instance ID:

- All active remote access sessions are terminated
- All Access Tokens associated with this installation are invalidated
- A new Instance ID is generated automatically
- The add-on restarts to apply the change

Use this feature if access credentials are compromised or if access must be
revoked.

---

## Security Model

Securicloud is designed with a minimal attack surface:

- **Outbound-only connectivity**
  - The add-on initiates all connections
  - No inbound connections are accepted

- **Installation-bound identity**
  - Access is tied to a specific Home Assistant installation
  - Identity can be rotated at any time via Instance ID reset

- **No credential storage**
  - No usernames or passwords are stored
  - Authentication is token-based and managed by Securicloud

This approach minimizes exposure while maintaining controlled remote access.

---

## Troubleshooting

- Ensure the add-on is running
- Verify that the Instance ID is registered in Securicloud
- Check the add-on logs for connection status messages

Resetting the Instance ID can resolve issues related to revoked or expired access.

---

## Support

For documentation, updates, and support, visit:

https://securicloud.me
