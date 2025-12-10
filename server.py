"""
Alfa Web Chatbot
A web-based chatbot for candidates and interpreters with Zoho CRM integration.
Clerk Authentication with CRM Email Verification (Sign-In Only Mode).
"""

import os
import logging
import json
import uuid
import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

import jwt
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

# Clerk Authentication
from clerk_backend_api import Clerk

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY")

clerk_sdk = None
if CLERK_SECRET_KEY:
    clerk_sdk = Clerk(bearer_auth=CLERK_SECRET_KEY)

# Configuration
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KNOWLEDGE_BASE_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30

DB_PATH = "/root/fogo-web-chatbot/chat.db"

zoho_token_cache = {"access_token": None, "expires_at": None}
active_sessions = {}

def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {message}"
    print(msg)
    with open("/root/fogo-web-chatbot/debug.log", "a") as f:
        f.write(msg + "\n")

def debug(message: str):
    if DEBUG:
        log(f"[DEBUG] {message}")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            picture TEXT,
            clerk_user_id TEXT,
            crm_id TEXT,
            crm_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    try:
        c.execute("ALTER TABLE users ADD COLUMN clerk_user_id TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            messages TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()
    log("Database initialized")

def get_user_by_email(email: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email.lower(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_or_update_user(email: str, name: str, picture: str, clerk_user_id: str = None, crm_id: str = None, crm_data: dict = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = get_user_by_email(email)
    if existing:
        c.execute("UPDATE users SET name = ?, picture = ?, clerk_user_id = ?, crm_id = ?, crm_data = ?, last_login = ? WHERE email = ?",
                  (name, picture, clerk_user_id, crm_id, json.dumps(crm_data) if crm_data else None, datetime.now(), email.lower()))
        user_id = existing["id"]
    else:
        c.execute("INSERT INTO users (email, name, picture, clerk_user_id, crm_id, crm_data, last_login) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (email.lower(), name, picture, clerk_user_id, crm_id, json.dumps(crm_data) if crm_data else None, datetime.now()))
        user_id = c.lastrowid
    conn.commit()
    conn.close()
    return user_id

def save_conversation(user_id: int, messages: list, conversation_id: int = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if conversation_id:
        c.execute("UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                  (json.dumps(messages), datetime.now(), conversation_id, user_id))
    else:
        c.execute("INSERT INTO conversations (user_id, messages) VALUES (?, ?)", (user_id, json.dumps(messages)))
        conversation_id = c.lastrowid
    conn.commit()
    conn.close()
    return conversation_id

def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except:
        return None

async def verify_clerk_token(token: str) -> Optional[dict]:
    if not clerk_sdk:
        return None
    try:
        from jwt import PyJWKClient
        jwks_url = "https://organic-mayfly-21.clerk.accounts.dev/.well-known/jwks.json"
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False})
        clerk_user_id = payload.get("sub")
        email = name = picture = None
        if clerk_user_id:
            try:
                user = clerk_sdk.users.get(user_id=clerk_user_id)
                if user:
                    if user.email_addresses:
                        email = user.email_addresses[0].email_address
                    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                    picture = user.image_url
            except Exception as e:
                log(f"Failed to fetch user from Clerk: {e}")
        if not email:
            log("No email found for Clerk user")
            return None
        return {"clerk_user_id": clerk_user_id, "email": email, "name": name or email, "picture": picture}
    except Exception as e:
        log(f"Error verifying Clerk token: {e}")
        return None

async def get_zoho_access_token() -> Optional[str]:
    global zoho_token_cache
    if zoho_token_cache["access_token"] and zoho_token_cache["expires_at"] and datetime.now() < zoho_token_cache["expires_at"]:
        return zoho_token_cache["access_token"]
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://accounts.zoho.com/oauth/v2/token",
                params={"refresh_token": ZOHO_REFRESH_TOKEN, "client_id": ZOHO_CLIENT_ID, "client_secret": ZOHO_CLIENT_SECRET, "grant_type": "refresh_token"})
            data = response.json()
            if "access_token" in data:
                zoho_token_cache["access_token"] = data["access_token"]
                zoho_token_cache["expires_at"] = datetime.now() + timedelta(seconds=data.get("expires_in", 3600) - 300)
                debug("Zoho access token refreshed")
                return data["access_token"]
    except Exception as e:
        log(f"Error refreshing Zoho token: {e}")
    return None

async def search_leads_by_email(email: str) -> Optional[dict]:
    access_token = await get_zoho_access_token()
    if not access_token:
        return None
    query = f'select id, First_Name, Last_Name, Email, Phone, Lead_Status, Language, Training_Status, Stage, Tier_Level, Candidate_Recruitment_Owner from Leads where Email = "{email}" limit 1'
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://www.zohoapis.com/crm/v8/coql",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
                json={"select_query": query})
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]
    except Exception as e:
        log(f"Error searching leads: {e}")
    return None

async def search_contacts_by_email(email: str) -> Optional[dict]:
    access_token = await get_zoho_access_token()
    if not access_token:
        return None
    query = f'select id, First_Name, Last_Name, Email, Phone from Contacts where Email = "{email}" limit 1'
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://www.zohoapis.com/crm/v8/coql",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
                json={"select_query": query})
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]
    except Exception as e:
        log(f"Error searching contacts: {e}")
    return None

async def verify_email_in_crm(email: str) -> tuple:
    lead = await search_leads_by_email(email)
    if lead:
        return lead, "candidate"
    contact = await search_contacts_by_email(email)
    if contact:
        return contact, "interpreter"
    return None, None

async def get_lead_with_documents(email: str) -> Optional[dict]:
    access_token = await get_zoho_access_token()
    if not access_token:
        return None
    query = f'select id, First_Name, Last_Name, Email, Lead_Status, Language, Training_Status, Stage, Tier_Level, Candidate_Recruitment_Owner from Leads where Email = "{email}" limit 1'
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://www.zohoapis.com/crm/v8/coql",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}", "Content-Type": "application/json"},
                json={"select_query": query})
            data = response.json()
            if "data" not in data or len(data["data"]) == 0:
                return None
            lead = data["data"][0]
            lead_id = lead.get("id")
            if lead_id:
                detail_response = await client.get(f"https://www.zohoapis.com/crm/v8/Leads/{lead_id}",
                    headers={"Authorization": f"Zoho-oauthtoken {access_token}"})
                detail_data = detail_response.json()
                if "data" in detail_data and len(detail_data["data"]) > 0:
                    full_lead = detail_data["data"][0]
                    lead["Government_issued_ID"] = full_lead.get("Government_issued_ID")
                    lead["Background_check_report"] = full_lead.get("Background_check_report")
                    lead["Resume"] = full_lead.get("Resume")
            return lead
    except Exception as e:
        log(f"Error fetching lead: {e}")
    return None

async def lookup_application_status(email: str = None, **kwargs) -> dict:
    if email:
        lead = await search_leads_by_email(email)
        if lead:
            return {"found": True, "verified": True, "first_name": lead.get("First_Name"), "last_name": lead.get("Last_Name"),
                    "status": lead.get("Lead_Status"), "language": lead.get("Language"), "stage": lead.get("Stage")}
    return {"found": False, "message": "No application found."}

async def search_knowledge_base(query: str) -> dict:
    return {"found": False, "message": "Knowledge base not configured."}

async def transfer_to_human(reason: str = "") -> dict:
    log(f"Human transfer requested: {reason}")
    return {"success": True, "message": "I have notified our support team."}

CHAT_TOOLS = [
    {"type": "function", "function": {"name": "lookup_application_status", "description": "Look up application status",
        "parameters": {"type": "object", "properties": {"email": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "search_knowledge_base", "description": "Search knowledge base",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "transfer_to_human", "description": "Transfer to human",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}}
]

def get_system_prompt(user_data: dict = None, language: str = "en") -> str:
    lang_note = "Respond in Spanish." if language == "es" else "Respond in English."
    user_info = ""
    if user_data:
        user_info = f"\nUser: {user_data.get('name')} ({user_data.get('email')})"
    return f"You are Angela, a helpful assistant for Alfa Interpreting. {lang_note}{user_info}"

async def get_chat_response(messages: list, user_data: dict = None, language: str = "en") -> str:
    system_prompt = get_system_prompt(user_data, language)
    api_messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o", "messages": api_messages, "tools": CHAT_TOOLS, "tool_choice": "auto", "temperature": 0.7})
            data = response.json()
            if "error" in data:
                return "I'm having trouble. Please try again."
            assistant_message = data["choices"][0]["message"]
            if assistant_message.get("tool_calls"):
                messages.append(assistant_message)
                for tool_call in assistant_message["tool_calls"]:
                    fn = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])
                    debug(f"Tool call: {fn}({args})")
                    if fn == "lookup_application_status":
                        if user_data and "email" not in args:
                            args["email"] = user_data.get("email")
                        result = await lookup_application_status(**args)
                    elif fn == "search_knowledge_base":
                        result = await search_knowledge_base(**args)
                    else:
                        result = await transfer_to_human(**args)
                    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": json.dumps(result)})
                api_messages = [{"role": "system", "content": system_prompt}] + messages
                final = await client.post("https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "gpt-4o", "messages": api_messages, "temperature": 0.7})
                assistant_message = final.json()["choices"][0]["message"]
            return assistant_message["content"]
    except Exception as e:
        log(f"Chat error: {e}")
        return "I encountered an error. Please try again."

APPLICATION_STAGES = ["Application Review", "Candidate Interview", "Candidate Language Assessment",
    "Candidate ID/Background Verification", "Contract & Payment Setup", "Training Required",
    "Client Tool Orientation", "Interpreter Ready for Production"]

def calculate_progress(stage: str) -> int:
    try:
        return int(((APPLICATION_STAGES.index(stage) + 1) / len(APPLICATION_STAGES)) * 100)
    except:
        return 0

def derive_tasks_from_data(lead_data: dict, stage: str) -> list:
    tasks = [{"id": "application", "title": "Complete application form", "description": "Submitted", "completed": True}]
    tasks.append({"id": "upload_id", "title": "Upload government ID", "completed": lead_data.get("Government_issued_ID") is not None})
    tasks.append({"id": "background_check", "title": "Complete background check", "completed": lead_data.get("Background_check_report") is not None})
    return tasks

def derive_documents_from_data(lead_data: dict) -> list:
    return [
        {"name": "Resume", "status": "uploaded" if lead_data.get("Resume") else "pending"},
        {"name": "Government ID", "status": "uploaded" if lead_data.get("Government_issued_ID") else "pending"},
        {"name": "Background Check", "status": "uploaded" if lead_data.get("Background_check_report") else "pending"}
    ]

def get_recruiter_info(owner_name: str) -> Optional[dict]:
    if owner_name:
        return {"name": str(owner_name), "title": "Recruitment Coordinator", "email": None}
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    log("Starting Alfa Web Chatbot server...")
    init_db()
    yield
    log("Shutting down server...")

app = FastAPI(title="Alfa Web Chatbot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/health")
async def health():
    return {"status": "healthy", "active_sessions": len(active_sessions)}


# Zoho CRM Webhook - Auto-invite new leads/contacts to Clerk
ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET", "")  # Optional: for signature verification

@app.post("/api/zoho-webhook")
async def zoho_webhook(request: Request):
    """
    Webhook endpoint for Zoho CRM.
    When a new Lead or Contact is created, Zoho calls this endpoint.
    We then send a Clerk invitation to that email address.
    
    Zoho Webhook Setup:
    1. Go to Zoho CRM → Settings → Developer Hub → Actions → Webhooks
    2. Create webhook with URL: https://your-domain.com/api/zoho-webhook
    3. Trigger: On Create (for Leads and/or Contacts modules)
    4. Parameters: Add ${Leads.Email}, ${Leads.First_Name}, ${Leads.Last_Name}
       Or for Contacts: ${Contacts.Email}, ${Contacts.First_Name}, ${Contacts.Last_Name}
    """
    try:
        # Parse webhook payload
        body = await request.json()
        logging.info(f"Zoho webhook received: {body}")
        
        # Extract email from payload - Zoho sends data in various formats
        email = None
        first_name = None
        last_name = None
        
        # Handle different Zoho payload formats
        if isinstance(body, dict):
            # Direct field mapping
            email = body.get("Email") or body.get("email")
            first_name = body.get("First_Name") or body.get("first_name") or body.get("First Name")
            last_name = body.get("Last_Name") or body.get("last_name") or body.get("Last Name")
            
            # Nested data format
            if not email and "data" in body:
                data = body["data"]
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                if isinstance(data, dict):
                    email = data.get("Email") or data.get("email")
                    first_name = data.get("First_Name") or data.get("first_name")
                    last_name = data.get("Last_Name") or data.get("last_name")
        
        if not email:
            logging.warning("Zoho webhook: No email found in payload")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No email in payload"}
            )
        
        # Check if Clerk SDK is available
        if not clerk_sdk:
            logging.error("Clerk SDK not initialized - cannot send invitation")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Clerk not configured"}
            )
        
        # Check if user already exists in Clerk
        try:
            existing_users = clerk_sdk.users.list(email_address=[email])
            if existing_users and len(existing_users.data) > 0:
                logging.info(f"User {email} already exists in Clerk, skipping invitation")
                return JSONResponse(
                    status_code=200,
                    content={"success": True, "message": "User already exists in Clerk", "email": email}
                )
        except Exception as e:
            logging.warning(f"Error checking existing Clerk user: {e}")
            # Continue to try invitation anyway
        
        
        # Create Clerk user silently (no notification)
        try:
            clerk_sdk.users.create(
                email_address=[email],
                first_name=first_name or "",
                last_name=last_name or "",
                skip_password_requirement=True,
                public_metadata={"source": "zoho_crm"}
            )
            logging.info(f"Clerk user created for {email}")
            return JSONResponse(
                status_code=200,
                content={"success": True, "message": "User created", "email": email}
            )
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                logging.info(f"User {email} already exists in Clerk")
                return JSONResponse(
                    status_code=200,
                    content={"success": True, "message": "User already exists", "email": email}
                )
            logging.error(f"Failed to send Clerk invitation to {email}: {e}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Failed to send invitation: {error_msg}"}
            )
            
    except Exception as e:
        logging.error(f"Zoho webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )



# Manual sync endpoint - for syncing existing CRM users to Clerk
@app.post("/api/sync-crm-to-clerk")
async def sync_crm_to_clerk(request: Request):
    """Sync all existing Zoho CRM leads and contacts to Clerk silently."""
    admin_key = request.headers.get("X-Admin-Key")
    expected_key = os.getenv("ADMIN_SECRET_KEY", "")
    
    if not expected_key or admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    if not clerk_sdk:
        raise HTTPException(status_code=500, detail="Clerk not configured")
    
    try:
        access_token = await get_zoho_access_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="Failed to get Zoho access token")
        
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        results = {"leads": 0, "contacts": 0, "created": 0, "existing": 0, "errors": 0, "error_details": []}
        
        async with httpx.AsyncClient() as client:
            # Fetch Leads
            resp = await client.post(
                "https://www.zohoapis.com/crm/v8/coql",
                headers=headers,
                json={"select_query": "SELECT Email, First_Name, Last_Name FROM Leads WHERE Email is not null LIMIT 200"}
            )
            if resp.status_code == 200:
                leads = resp.json().get("data", [])
                results["leads"] = len(leads)
            else:
                leads = []
            
            # Fetch Contacts
            resp = await client.post(
                "https://www.zohoapis.com/crm/v8/coql",
                headers=headers,
                json={"select_query": "SELECT Email, First_Name, Last_Name FROM Contacts WHERE Email is not null LIMIT 200"}
            )
            if resp.status_code == 200:
                contacts = resp.json().get("data", [])
                results["contacts"] = len(contacts)
            else:
                contacts = []
        
        # Combine and dedupe by email
        all_records = leads + contacts
        seen_emails = set()
        
        for record in all_records:
            email = record.get("Email")
            if not email or email.lower() in seen_emails:
                continue
            seen_emails.add(email.lower())
            
            try:
                existing = clerk_sdk.users.list(request={"email_address": [email]})
                if existing and len(existing.data) > 0:
                    results["existing"] += 1
                    continue
                
                clerk_sdk.users.create(
                    email_address=[email],
                    first_name=record.get("First_Name") or "",
                    last_name=record.get("Last_Name") or "",
                    skip_password_requirement=True,
                    public_metadata={"source": "zoho_crm_sync"}
                )
                results["created"] += 1
                logging.info(f"Created Clerk user: {email}")
                await asyncio.sleep(0.5)  # Rate limit: wait between API calls
            except Exception as e:
                error_msg = str(e)
                if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                    results["existing"] += 1
                else:
                    results["errors"] += 1
                    results["error_details"].append({"email": email, "error": error_msg[:100]})
        
        return results
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/candidate-data")
async def get_candidate_data(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header.split(" ")[1]
    payload = await verify_clerk_token(token) if clerk_sdk else None
    if not payload:
        payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = payload["email"]
    crm_data, user_type = await verify_email_in_crm(email)
    if not crm_data:
        raise HTTPException(status_code=403, detail="Email not registered in CRM")
    lead_data = await get_lead_with_documents(email)
    if not lead_data:
        return {"name": payload.get("name", email), "email": email, "language": None, "stage": None,
                "progress_percent": 0, "upcoming": None, "tasks": [], "documents": [], "recruiter": None}
    stage = lead_data.get("Stage", "Application Review")
    return {
        "name": f"{lead_data.get('First_Name', '')} {lead_data.get('Last_Name', '')}".strip() or payload.get("name", email),
        "email": email, "language": lead_data.get("Language"), "stage": stage, "status": lead_data.get("Lead_Status"),
        "progress_percent": calculate_progress(stage), "upcoming": None,
        "tasks": await get_tasks_for_lead(lead_data.get("id")), "documents": derive_documents_from_data(lead_data),
        "recruiter": get_recruiter_info(lead_data.get("Candidate_Recruitment_Owner"))
    }

@app.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    user_data = None
    user_id = None
    language = "en"
    messages = []
    conversation_id = None
    debug(f"New WebSocket connection: {session_id}")
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "auth":
                token = data.get("token")
                language = data.get("language", "en")
                if token:
                    payload = await verify_clerk_token(token) if clerk_sdk else None
                    if payload:
                        email = payload["email"]
                        clerk_user_id = payload.get("clerk_user_id")
                        name = payload.get("name", email)
                        picture = payload.get("picture")
                        crm_data, user_type = await verify_email_in_crm(email)
                        if not crm_data:
                            log(f"Access denied: {email} not found in CRM")
                            await websocket.send_json({"type": "auth_failed", "reason": "email_not_registered",
                                "message": "This email is not registered. Please complete the interpreter application form first."})
                            continue
                        crm_id = crm_data.get("id")
                        user_id = create_or_update_user(email, name, picture, clerk_user_id, crm_id, crm_data)
                        user_data = {"id": user_id, "email": email, "name": name, "crm_data": crm_data}
                        active_sessions[session_id] = {"user_id": user_id, "language": language}
                        first_name = name.split()[0] if name else "there"
                        welcome = f"Hola {first_name}!" if language == "es" else f"Hello {first_name}! How can I help you today?"
                        await websocket.send_json({"type": "auth_success", "user": {"email": email, "name": name, "picture": picture, "crm_data": crm_data}})
                        await websocket.send_json({"type": "message", "content": welcome})
                        messages.append({"role": "assistant", "content": welcome})
                        log(f"User authenticated: {email} ({user_type})")
                        continue
                await websocket.send_json({"type": "auth_failed", "reason": "invalid_token"})
                continue
            if data.get("type") == "set_language":
                language = data.get("language", "en")
                continue
            if data.get("type") == "message":
                user_message = data.get("content", "")
                if not user_message:
                    continue
                debug(f"[{session_id}] User: {user_message}")
                messages.append({"role": "user", "content": user_message})
                await websocket.send_json({"type": "typing", "status": True})
                response = await get_chat_response(messages, user_data, language)
                messages.append({"role": "assistant", "content": response})
                if user_id:
                    conversation_id = save_conversation(user_id, messages, conversation_id)
                debug(f"[{session_id}] Assistant: {response[:100]}...")
                await websocket.send_json({"type": "message", "content": response})
            if data.get("type") == "new_conversation":
                messages = []
                conversation_id = None
    except WebSocketDisconnect:
        debug(f"Session disconnected: {session_id}")
        if session_id in active_sessions:
            del active_sessions[session_id]
    except Exception as e:
        log(f"WebSocket error: {e}")
        if session_id in active_sessions:
            del active_sessions[session_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)

# =============================================================================
# Zoho Tasks Integration
# =============================================================================

async def get_tasks_for_lead(lead_id: str) -> list:
    """Fetch tasks from Zoho CRM Tasks module related to a Lead."""
    access_token = await get_zoho_access_token()
    if not access_token or not lead_id:
        return []
    
    query = f"select id, Subject, Due_Date, Status, Priority, Description from Tasks where What_Id = {lead_id} limit 20"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://www.zohoapis.com/crm/v8/coql",
                headers={
                    "Authorization": f"Zoho-oauthtoken {access_token}",
                    "Content-Type": "application/json"
                },
                json={"select_query": query}
            )
            data = response.json()
            
            if "data" in data:
                tasks = []
                for task in data["data"]:
                    status = task.get("Status", "")
                    tasks.append({
                        "id": task.get("id"),
                        "title": task.get("Subject", "Untitled Task"),
                        "description": task.get("Description", ""),
                        "due_date": task.get("Due_Date"),
                        "priority": task.get("Priority", "Normal"),
                        "status": status,
                        "completed": status in ["Completed", "Done"]
                    })
                return tasks
            return []
    except Exception as e:
        log(f"Error fetching tasks: {e}")
        return []
