# Alfa Web Chatbot

A web-based chatbot for candidates and interpreters with Zoho CRM integration.

## Features

- **Real-time Chat** - WebSocket-based chat interface
- **Zoho CRM Integration** - Look up application status and candidate information
- **Knowledge Base** - Answer questions using OpenAI Assistants
- **Identity Verification** - Verify users before sharing sensitive information
- **Human Handoff** - Transfer to human support when needed

## Target Users

1. **Candidates** - People who have applied for interpreter positions
   - Check application status
   - Ask questions about the hiring process

2. **Active Interpreters** - Fully onboarded interpreters
   - Ask operational questions (schedules, policies, procedures)
   - Get information from knowledge base

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required:
- `OPENAI_API_KEY` - Your OpenAI API key

Optional:
- `OPENAI_ASSISTANT_ID` - Assistant ID for knowledge base
- `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` - For CRM integration

### 3. Run the server

```bash
python server.py
```

Or with uvicorn:

```bash
uvicorn server:app --host 0.0.0.0 --port 8006
```

### 4. Access the chat

Open http://localhost:8006 in your browser.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Chat interface (static HTML) |
| `/chat` | WebSocket | Real-time chat connection |
| `/health` | GET | Health check |

## Deployment

For production, use a process manager like systemd:

```ini
[Unit]
Description=Alfa Web Chatbot
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/fogo-web-chatbot
ExecStart=/path/to/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8006
Restart=always

[Install]
WantedBy=multi-user.target
```

Use nginx as a reverse proxy with WebSocket support.

## License

Proprietary - Alfa Systems
