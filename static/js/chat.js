/**
 * Alfa Web Chatbot - Candidate Portal
 * Clerk Authentication (Sign-In Only) + Zoho CRM Verification
 */

const i18n = {
    en: {
        welcome: "Welcome", signInPrompt: "Sign in to check your application status, ask questions, or get support.",
        loginNote: "Use the email you used to apply or register with Alfa Interpreting.",
        chatSupport: "Chat Support", checkStatus: "Check Application Status", haveQuestion: "I have a question",
        talkHuman: "Talk to a human", typeMessage: "Type your message...", connecting: "Connecting...",
        progress: "Progress", stages: "Stages", signOut: "Sign Out", typicallyReplies: "Typically replies in minutes",
        upcoming: "Upcoming", tasks: "Tasks", documents: "Documents", yourRecruiter: "Your Recruiter",
        joinMeeting: "Join Meeting", reschedule: "Reschedule", noUpcoming: "No upcoming events",
        uploaded: "Uploaded", pending: "Pending", required: "Required",
        emailNotRegistered: "This email is not registered. Please complete the interpreter application form first.",
        applyNow: "Apply Now"
    },
    es: {
        welcome: "Bienvenido", signInPrompt: "Inicia sesion para verificar el estado de tu aplicacion.",
        loginNote: "Usa el correo con el que aplicaste en Alfa Interpreting.",
        chatSupport: "Soporte", checkStatus: "Ver Estado", haveQuestion: "Tengo una pregunta",
        talkHuman: "Hablar con una persona", typeMessage: "Escribe tu mensaje...", connecting: "Conectando...",
        progress: "Progreso", stages: "Etapas", signOut: "Cerrar Sesion", typicallyReplies: "Responde en minutos",
        upcoming: "Proximo", tasks: "Tareas", documents: "Documentos", yourRecruiter: "Tu Reclutador",
        joinMeeting: "Unirse", reschedule: "Reprogramar", noUpcoming: "Sin eventos",
        uploaded: "Subido", pending: "Pendiente", required: "Requerido",
        emailNotRegistered: "Este correo no esta registrado. Completa el formulario de aplicacion primero.",
        applyNow: "Aplicar"
    }
};

const quickActionMessages = {
    en: { status: "I want to check my application status", question: "I have a question", human: "I would like to speak with a human" },
    es: { status: "Quiero verificar el estado de mi aplicacion", question: "Tengo una pregunta", human: "Quiero hablar con una persona" }
};

const APPLICATION_STAGES = [
    { key: "Application Review", label: "Applied", labelEs: "Aplicado" },
    { key: "Candidate Interview", label: "Interview", labelEs: "Entrevista" },
    { key: "Candidate Language Assessment", label: "Assessment", labelEs: "Evaluacion" },
    { key: "Candidate ID/Background Verification", label: "Verification", labelEs: "Verificacion" },
    { key: "Contract & Payment Setup", label: "Contract", labelEs: "Contrato" },
    { key: "Training Required", label: "Training", labelEs: "Capacitacion" },
    { key: "Client Tool Orientation", label: "Orientation", labelEs: "Orientacion" },
    { key: "Interpreter Ready for Production", label: "Ready", labelEs: "Listo" }
];

class ChatApp {
    constructor() {
        this.socket = null;
        this.clerkUser = null;
        this.candidateData = null;
        this.language = localStorage.getItem("chat_language") || "en";
        this.isConnected = false;
        this.isConnecting = false;
        this.clerkMounted = false;
        this.authHandled = false;
        
        this.loginScreen = document.getElementById("loginScreen");
        this.portalScreen = document.getElementById("portalScreen");
        this.messagesContainer = document.getElementById("chatMessages");
        this.messageInput = document.getElementById("messageInput");
        this.chatForm = document.getElementById("chatForm");
        this.sendButton = document.getElementById("sendButton");
        this.typingIndicator = document.getElementById("typingIndicator");
        this.quickActions = document.getElementById("quickActions");
        this.sidebarAvatar = document.getElementById("sidebarAvatar");
        this.sidebarUserName = document.getElementById("sidebarUserName");
        this.sidebarUserRole = document.getElementById("sidebarUserRole");
        this.progressPercent = document.getElementById("progressPercent");
        this.progressFill = document.getElementById("progressFill");
        this.verticalTimeline = document.getElementById("verticalTimeline");
        this.taskList = document.getElementById("taskList");
        this.taskCount = document.getElementById("taskCount");
        this.docList = document.getElementById("docList");
        this.recruiterCard = document.getElementById("recruiterCard");
        this.upcomingCard = document.getElementById("upcomingCard");
        this.upcomingEmpty = document.getElementById("upcomingEmpty");
        
        this.init();
    }
    
    async init() {
        this.applyLanguage(this.language);
        document.querySelectorAll(".lang-btn, .lang-toggle-btn").forEach(btn => {
            btn.addEventListener("click", (e) => this.setLanguage(e.target.dataset.lang));
        });
        this.chatForm.addEventListener("submit", (e) => { e.preventDefault(); this.sendMessage(); });
        this.renderVerticalTimeline();
        await this.initClerk();
    }
    
    async initClerk() {
        let attempts = 0;
        while (!window.Clerk && attempts < 50) {
            await new Promise(r => setTimeout(r, 100));
            attempts++;
        }
        if (!window.Clerk) { this.showSignIn(); return; }
        
        if (!window.Clerk.loaded) {
            try { await window.Clerk.load(); } catch(e) {}
        }
        
        window.Clerk.addListener((resources) => {
            if (this.authHandled) return;
            if (resources.user) {
                this.authHandled = true;
                this.clerkUser = resources.user;
                this.onUserSignedIn();
            } else {
                this.onUserSignedOut();
            }
        });
        
        if (window.Clerk.user) {
            this.authHandled = true;
            this.clerkUser = window.Clerk.user;
            this.onUserSignedIn();
        } else {
            this.showSignIn();
        }
    }
    
    showSignIn() {
        this.loginScreen.style.display = "flex";
        this.portalScreen.style.display = "none";
        this.hideAuthError();
        
        const signInDiv = document.getElementById("clerk-sign-in");
        if (signInDiv && window.Clerk && !this.clerkMounted) {
            signInDiv.innerHTML = "";
            window.Clerk.mountSignIn(signInDiv, {
                appearance: {
                    elements: {
                        rootBox: { width: "100%", maxWidth: "400px", margin: "0 auto" },
                        card: { boxShadow: "none", border: "none", backgroundColor: "transparent" },
                        headerTitle: { display: "none" }, headerSubtitle: { display: "none" },
                        footer: { display: "none" }, footerAction: { display: "none" },
                        formButtonPrimary: { backgroundColor: "#1e3a5f" },
                        socialButtonsBlockButton: { border: "1px solid #e5e7eb", borderRadius: "8px" }
                    },
                    layout: { socialButtonsPlacement: "top", socialButtonsVariant: "blockButton" }
                }
            });
            this.clerkMounted = true;
        }
    }
    
    showAuthError(message, showApplyLink = false) {
        let errorContainer = document.getElementById("authErrorContainer");
        if (!errorContainer) {
            errorContainer = document.createElement("div");
            errorContainer.id = "authErrorContainer";
            errorContainer.className = "auth-error";
            const signInDiv = document.getElementById("clerk-sign-in");
            if (signInDiv) signInDiv.parentNode.insertBefore(errorContainer, signInDiv);
        }
        const strings = i18n[this.language] || i18n.en;
        errorContainer.innerHTML = `<p>${message}</p>` + (showApplyLink ? 
            `<a href="https://alfainterpreting.com/apply" target="_blank" class="apply-link">${strings.applyNow}</a>` : "");
        errorContainer.style.display = "block";
    }
    
    hideAuthError() {
        const el = document.getElementById("authErrorContainer");
        if (el) el.style.display = "none";
    }
    
    onUserSignedIn() {
        if (this.clerkMounted) {
            const signInDiv = document.getElementById("clerk-sign-in");
            if (signInDiv && window.Clerk) {
                try { window.Clerk.unmountSignIn(signInDiv); } catch(e) {}
                this.clerkMounted = false;
            }
        }
        this.hideAuthError();
        this.showPortal();
        if (!this.isConnected && !this.isConnecting) {
            this.connect();
        }
        this.loadCandidateData();
    }
    
    onUserSignedOut() {
        this.clerkUser = null;
        this.authHandled = false;
        this.isConnected = false;
        this.isConnecting = false;
        if (this.socket) { this.socket.close(); this.socket = null; }
        this.showSignIn();
    }
    
    setLanguage(lang) {
        this.language = lang;
        localStorage.setItem("chat_language", lang);
        this.applyLanguage(lang);
        if (this.candidateData) this.renderVerticalTimeline(this.candidateData.stage);
        if (this.socket && this.isConnected) {
            this.socket.send(JSON.stringify({ type: "set_language", language: lang }));
        }
    }
    
    applyLanguage(lang) {
        const strings = i18n[lang] || i18n.en;
        document.querySelectorAll("[data-i18n]").forEach(el => {
            if (strings[el.dataset.i18n]) el.textContent = strings[el.dataset.i18n];
        });
        document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
            if (strings[el.dataset.i18nPlaceholder]) el.placeholder = strings[el.dataset.i18nPlaceholder];
        });
        document.querySelectorAll(".lang-btn, .lang-toggle-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.lang === lang);
        });
    }
    
    showPortal() {
        this.loginScreen.style.display = "none";
        this.portalScreen.style.display = "flex";
        if (this.clerkUser) {
            const name = this.clerkUser.fullName || this.clerkUser.primaryEmailAddress?.emailAddress || "User";
            if (this.clerkUser.imageUrl) {
                this.sidebarAvatar.innerHTML = `<img src="${this.clerkUser.imageUrl}" alt="">`;
            } else {
                this.sidebarAvatar.textContent = name.substring(0, 2).toUpperCase();
            }
            this.sidebarUserName.textContent = name;
        }
    }
    
    async getSessionToken() {
        if (!window.Clerk?.session) return null;
        try { return await window.Clerk.session.getToken(); } catch(e) { return null; }
    }
    
    async loadCandidateData() {
        try {
            const token = await this.getSessionToken();
            if (!token) return;
            const response = await fetch("/api/candidate-data", { headers: { "Authorization": "Bearer " + token } });
            if (response.ok) {
                this.candidateData = await response.json();
                this.updateSidebar();
                this.updateInfoPanel();
            } else if (response.status === 403) {
                await window.Clerk.signOut();
                this.showSignIn();
                this.showAuthError(i18n[this.language].emailNotRegistered, true);
            }
        } catch(e) { console.error("Failed to load candidate data:", e); }
    }
    
    updateSidebar() {
        if (!this.candidateData) return;
        if (this.candidateData.language) this.sidebarUserRole.textContent = `${this.candidateData.language} Interpreter`;
        const progress = this.candidateData.progress_percent || 0;
        this.progressPercent.textContent = progress + "%";
        this.progressFill.style.width = progress + "%";
        this.renderVerticalTimeline(this.candidateData.stage);
    }
    
    renderVerticalTimeline(currentStage = null) {
        const currentIndex = currentStage ? APPLICATION_STAGES.findIndex(s => s.key === currentStage) : -1;
        this.verticalTimeline.innerHTML = "";
        APPLICATION_STAGES.forEach((stage, index) => {
            const row = document.createElement("div");
            row.className = "timeline-row" + (index < currentIndex ? " completed" : "") + (index === currentIndex ? " active" : "");
            row.innerHTML = `<div class="step-circle"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>
                <span class="step-label">${this.language === "es" ? stage.labelEs : stage.label}</span>`;
            this.verticalTimeline.appendChild(row);
        });
    }
    
    updateInfoPanel() {
        if (!this.candidateData) return;
        // Upcoming
        if (this.candidateData.upcoming?.title) {
            this.upcomingCard.style.display = "block";
            this.upcomingEmpty.style.display = "none";
        } else {
            this.upcomingCard.style.display = "none";
            this.upcomingEmpty.style.display = "block";
        }
        // Documents
        const docs = this.candidateData.documents || [];
        const strings = i18n[this.language];
        this.docList.innerHTML = docs.map(d => `<div class="doc-item">
            <div class="doc-icon">${d.name.substring(0,3).toUpperCase()}</div>
            <div class="doc-info"><h4>${d.name}</h4></div>
            <span class="doc-status ${d.status}">${d.status === "uploaded" ? strings.uploaded : strings.pending}</span></div>`).join("") || "<p>No documents</p>";
        // Recruiter
        const recruiter = this.candidateData.recruiter;
        if (recruiter?.name) {
            this.recruiterCard.style.display = "flex";
            document.getElementById("recruiterAvatar").textContent = recruiter.name.substring(0, 2).toUpperCase();
            document.getElementById("recruiterName").textContent = recruiter.name;
            document.getElementById("recruiterTitle").textContent = recruiter.title || "Coordinator";
        } else {
            this.recruiterCard.style.display = "none";
        }
    }
    
    async connect() {
        if (this.isConnecting || this.isConnected) return;
        this.isConnecting = true;
        
        const token = await this.getSessionToken();
        if (!token) { this.isConnecting = false; return; }
        
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        this.socket = new WebSocket(protocol + "//" + window.location.host + "/chat");
        
        this.socket.onopen = () => {
            this.isConnected = true;
            this.isConnecting = false;
            this.setInputEnabled(true);
            this.socket.send(JSON.stringify({ type: "auth", token: token, language: this.language }));
        };
        
        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "auth_success") {
                this.showQuickActions();
            } else if (data.type === "auth_failed") {
                if (data.reason === "email_not_registered") {
                    window.Clerk?.signOut();
                    this.showSignIn();
                    this.showAuthError(i18n[this.language].emailNotRegistered, true);
                }
            } else if (data.type === "message") {
                this.hideTypingIndicator();
                this.addMessage(data.content, "assistant");
            } else if (data.type === "typing" && data.status) {
                this.showTypingIndicator();
            }
        };
        
        this.socket.onclose = () => {
            this.isConnected = false;
            this.isConnecting = false;
            this.setInputEnabled(false);
            setTimeout(() => { if (this.clerkUser && !this.isConnected) this.connect(); }, 3000);
        };
        
        this.socket.onerror = () => { this.isConnecting = false; };
    }
    
    sendMessage(content = null) {
        const message = content || this.messageInput.value.trim();
        if (!message || !this.isConnected) return;
        this.hideQuickActions();
        this.addMessage(message, "user");
        this.socket.send(JSON.stringify({ type: "message", content: message }));
        this.messageInput.value = "";
    }
    
    addMessage(content, role) {
        const div = document.createElement("div");
        div.className = "message " + role;
        div.innerHTML = `<div class="message-content">${content.replace(/\n/g, "<br>")}</div>
            <div class="message-time">${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</div>`;
        this.messagesContainer.appendChild(div);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
    
    showQuickActions() { this.quickActions.style.display = "flex"; }
    hideQuickActions() { this.quickActions.style.display = "none"; }
    handleQuickAction(action) {
        const msg = quickActionMessages[this.language]?.[action];
        if (msg) this.sendMessage(msg);
    }
    showTypingIndicator() { this.typingIndicator.classList.add("active"); }
    hideTypingIndicator() { this.typingIndicator.classList.remove("active"); }
    setInputEnabled(enabled) {
        this.messageInput.disabled = !enabled;
        this.sendButton.disabled = !enabled;
        this.messageInput.placeholder = i18n[this.language][enabled ? "typeMessage" : "connecting"];
    }
    newConversation() {
        if (this.socket && this.isConnected) {
            this.messagesContainer.innerHTML = "";
            this.showQuickActions();
            this.socket.send(JSON.stringify({ type: "new_conversation" }));
        }
    }
}

async function logout() { if (window.Clerk) await window.Clerk.signOut(); }
function newConversation() { window.chatApp?.newConversation(); }
function handleQuickAction(action) { window.chatApp?.handleQuickAction(action); }
function toggleMobileSidebar() {
    document.querySelector(".status-sidebar").classList.toggle("active");
    document.getElementById("mobileOverlay").classList.toggle("active");
}
function toggleMobileInfoPanel() {
    document.getElementById("infoPanel").classList.toggle("active");
    document.getElementById("mobileOverlay").classList.toggle("active");
}
function closeMobilePanels() {
    document.querySelector(".status-sidebar").classList.remove("active");
    document.getElementById("infoPanel").classList.remove("active");
    document.getElementById("mobileOverlay").classList.remove("active");
}

document.addEventListener("DOMContentLoaded", () => { window.chatApp = new ChatApp(); });
