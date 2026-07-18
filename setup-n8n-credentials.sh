#!/bin/bash
# N8N Credentials Setup Script
# This script configures all necessary credentials for the AI Job Application workflow

N8N_URL="http://localhost:5678"
N8N_USER="admin"
N8N_PASS="ChangeThisNow123!"

echo "[INFO] Getting n8n auth token..."

# Get auth token
AUTH_RESPONSE=$(curl -s -X POST "$N8N_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$N8N_USER\",\"password\":\"$N8N_PASS\"}")

AUTH_TOKEN=$(echo $AUTH_RESPONSE | jq -r '.data.token')
echo "[INFO] Auth token: $AUTH_TOKEN"

# 1. OpenAI API Credential
echo "[INFO] Setting up OpenAI API credential..."
curl -s -X POST "$N8N_URL/api/v1/credentials" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "name": "openai-api",
  "type": "openAiApi",
  "data": {
    "apiKey": "${OPENAI_API_KEY}"
  }
}
EOF

# 2. Gmail OAuth2 Credential
echo "[INFO] Setting up Gmail OAuth2 credential..."
curl -s -X POST "$N8N_URL/api/v1/credentials" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "name": "gmail-oauth",
  "type": "gmailOAuth2",
  "data": {
    "clientId": "${GMAIL_CLIENT_ID}",
    "clientSecret": "${GMAIL_CLIENT_SECRET}",
    "refreshToken": "${GMAIL_REFRESH_TOKEN}"
  }
}
EOF

# 3. File System Credential (Local Files)
echo "[INFO] Setting up File System credential..."
curl -s -X POST "$N8N_URL/api/v1/credentials" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "name": "file-system",
  "type": "fileSystemAPI",
  "data": {
    "basePath": "/path/to/workspace"
  }
}
EOF

echo "[INFO] Credentials setup complete!"
