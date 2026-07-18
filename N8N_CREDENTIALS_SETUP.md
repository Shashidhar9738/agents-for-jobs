# N8N Workflow - Credentials Setup Guide

## Step 1: Access n8n Dashboard

1. Open browser: **http://localhost:5678**
2. Login with:
   - Email: `admin`
   - Password: `ChangeThisNow123!`

## Step 2: Set Up Required Credentials

### 2.1 OpenAI API Key
1. Go to **Credentials** in the left sidebar
2. Click **+ New** → Select **OpenAI**
3. Name: `openai-api`
4. API Key: Paste your OpenAI API key from https://platform.openai.com/api-keys
5. Click **Save**

### 2.2 Gmail OAuth2 (For Email Notifications)
1. **Credentials** → **+ New** → **Gmail**
2. Name: `gmail-oauth`
3. Follow OAuth flow to authorize Gmail access
4. Select the email account to use for notifications
5. Click **Save**

### 2.3 File System Access (Local Files)
1. **Credentials** → **+ New** → **File System**
2. Name: `file-system`
3. Base Path: `C:\Users\shashidhar.yadala\Videos\auto apply the jobs`
4. Click **Save**

## Step 3: Import the Workflow

1. Click **Workflows** in sidebar
2. Click **+ New**
3. Click **Menu** (three dots) → **Import from File**
4. Select: `n8n-job-agent-workflow.json`
5. Click **Save**

## Step 4: Configure Environment Variables

In n8n Settings, add these environment variables:

```
OPENAI_API_KEY=sk-proj-xxxxx...
MINIMUM_MATCH_SCORE=80
NOTIFICATION_EMAIL=your.email@example.com
GMAIL_CLIENT_ID=xxxxx...
GMAIL_CLIENT_SECRET=xxxxx...
GMAIL_REFRESH_TOKEN=xxxxx...
```

## Step 5: Enable & Test

1. Open your imported workflow
2. Toggle **Active** to ON
3. Click **Execute Workflow** to test
4. Check execution logs for any errors

## Workflow Overview

The workflow:
1. **Runs Daily** (configurable)
2. **Loads** your profile & preferences
3. **Searches** for jobs matching your criteria
4. **Scores** job matches via OpenAI
5. **Filters** jobs above match threshold
6. **Generates** tailored resume & cover letter
7. **Updates** AppliedJobs.csv tracking
8. **Sends** email notification

## Troubleshooting

### Credentials Not Found
- Check credential names match exactly in nodes
- Ensure credentials are saved properly

### File System Access Errors
- Verify base path exists and is readable
- Check Windows file permissions

### Gmail Not Sending
- Ensure Gmail OAuth token is fresh
- Check "Less Secure Apps" settings if using Basic Auth

### OpenAI Errors
- Verify API key is valid
- Check API quota/billing at https://platform.openai.com/account/billing/overview

## Next Steps

1. Customize the workflow to add:
   - LinkedIn job search integration
   - Slack notifications
   - Database logging (MySQL/PostgreSQL)
   - Browser automation for LinkedIn Easy Apply

2. Adjust the daily schedule as needed
3. Add error handling and retry logic
4. Set up monitoring and logs
