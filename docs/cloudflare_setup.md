# Cloudflare Tunnel Setup Guide

This guide walks you through setting up a Cloudflare Tunnel (formerly "Argo Tunnel") to expose your local Label Studio instance to the internet without opening ports on your router.

## 1. Access the Dashboard
1.  Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/).
2.  On the left sidebar, click **Zero Trust**. (You may need to select your account first).

## 2. Create the Tunnel
1.  In the Zero Trust dashboard, go to **Networks > Tunnels** on the left sidebar.
2.  Click **Create a Tunnel**.
3.  Select **Cloudflared** (connector).
4.  **Name**: Give it a name like `monarch-eval` or `home-lab`. Click **Save Tunnel**.

## 3. Get the Token
1.  You will see a screen titled "Install and run a connector".
2.  Look for the box with command line instructions.
3.  You don't need to run these commands! You just need the **token**.
4.  It is the long string of random characters following the flag `--token`.
    *   *Example*: `eyJhIjoi...`
5.  **Copy this token**. This is your `TUNNEL_TOKEN`.
6.  Paste this into your Portainer Stack environment variables or your `.env` file.

## 4. Configure the Public Hostname
After copying the token, click **Next** in the Cloudflare dashboard to go to the **Public Hostnames** tab.

1.  Click **Add a public hostname**.
2.  **Subdomain**: `monarch-eval` (or whatever you want).
3.  **Domain**: `baywood-labs.com`.
4.  **Service**:
    *   **Type**: `HTTP`
    *   **URL**: `label-studio:8080`
    
    > **Make sure to use `label-studio` as the hostname!**
    > Since Cloudflared is running inside our Docker network, it can "see" the other container by its service name (`label-studio`) defined in our `docker-compose.yml`. Do not use `localhost` or `127.0.0.1`.

5.  Click **Save Hostname**.

## 5. Verifiction
1.  Ensure your Docker Stack is running (and the `tunnel` container is up).
2.  Visit `https://monarch-eval.baywood-labs.com` on your phone (disconnect from WiFi to test true remote access).
3.  You should see the Label Studio login page.
