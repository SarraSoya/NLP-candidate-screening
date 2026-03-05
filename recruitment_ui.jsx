import { useState, useEffect, useRef } from "react";

const CANDIDATES = [
  {
    id: "alice_johnson", name: "Alice Johnson", email: "alice@example.com",
    score: 0.91, finalScore: 0.95, status: "ready_for_hr",
    skills: ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Redis"],
    experience: 7, role: "Senior Backend Engineer",
    gaps: [{ req: "Kubernetes", answer: "Currently studying CKA certification", status: "answered" }],
    delta: "+0.04",
  },
  {
    id: "bob_martinez", name: "Bob Martinez", email: "bob@example.com",
    score: 0.78, finalScore: 0.82, status: "ready_for_hr",
    skills: ["Python", "Django", "PostgreSQL", "GCP", "Kafka", "CI/CD"],
    experience: 5, role: "Backend Developer",
    gaps: [{ req: "Redis", answer: "Used Memcached, open to Redis", status: "answered" }],
    delta: "+0.04",
  },
  {
    id: "carol_white", name: "Carol White", email: "carol@example.com",
    score: 0.72, finalScore: 0.72, status: "shortlisted",
    skills: ["Python", "FastAPI", "MySQL", "Docker", "GitHub Actions"],
    experience: 4, role: "Python Developer",
    gaps: [{ req: "Cloud platforms", answer: null, status: "unanswered" }],
    delta: null,
  },
  {
    id: "david_chen", name: "David Chen", email: "david@example.com",
    score: 0.61, finalScore: 0.61, status: "shortlisted",
    skills: ["Python", "Flask", "MongoDB", "Docker"],
    experience: 3, role: "Junior Backend",
    gaps: [{ req: "Microservices", answer: null, status: "unanswered" }],
    delta: null,
  },
  {
    id: "sara_patel", name: "Sara Patel", email: "sara@example.com",
    score: 0.38, finalScore: 0.38, status: "rejected",
    skills: ["Python", "Pandas", "NumPy", "Jupyter"],
    experience: 2, role: "Data Analyst",
    gaps: [{ req: "Backend APIs", answer: null, status: "unanswered" }, { req: "PostgreSQL", answer: null, status: "unanswered" }],
    delta: null,
  },
];

const CHAT_QUESTIONS = [
  "You have experience with Docker — have you deployed containerized applications to Kubernetes in production?",
  "Can you walk me through your experience designing microservices architecture? What patterns did you use?",
  "The role involves Redis for caching. Could you describe a specific use case where you optimized performance with caching?",
];

const statusConfig = {
  ready_for_hr: { label: "Ready for HR", color: "#10b981", bg: "rgba(16,185,129,0.12)", dot: "#10b981" },
  shortlisted:  { label: "Shortlisted",  color: "#6366f1", bg: "rgba(99,102,241,0.12)", dot: "#6366f1" },
  in_chat:      { label: "Interviewing", color: "#f59e0b", bg: "rgba(245,158,11,0.12)",  dot: "#f59e0b" },
  rejected:     { label: "Rejected",     color: "#ef4444", bg: "rgba(239,68,68,0.12)",   dot: "#ef4444" },
};

const ScoreBar = ({ score, size = "md" }) => {
  const pct = Math.round(score * 100);
  const color = score >= 0.8 ? "#10b981" : score >= 0.6 ? "#f59e0b" : "#ef4444";
  const h = size === "sm" ? 4 : 6;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <div style={{ flex: 1, background: "rgba(255,255,255,0.08)", borderRadius: 99, height: h, overflow: "hidden", minWidth: 60 }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 99,
          background: `linear-gradient(90deg, ${color}cc, ${color})`,
          transition: "width 1s cubic-bezier(.4,0,.2,1)",
          boxShadow: `0 0 8px ${color}66`
        }} />
      </div>
      <span style={{ fontSize: size === "sm" ? 11 : 13, fontWeight: 700, color, minWidth: 34, fontFamily: "'DM Mono', monospace" }}>{pct}%</span>
    </div>
  );
};

const Badge = ({ status }) => {
  const cfg = statusConfig[status] || { label: status, color: "#94a3b8", bg: "rgba(148,163,184,0.12)", dot: "#94a3b8" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}33`,
      borderRadius: 99, padding: "3px 10px", fontSize: 11, fontWeight: 600, letterSpacing: .3, whiteSpace: "nowrap"
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: cfg.dot, boxShadow: `0 0 6px ${cfg.dot}` }} />
      {cfg.label}
    </span>
  );
};

const Avatar = ({ name, size = 40 }) => {
  const initials = name.split(" ").map(n => n[0]).join("").slice(0, 2);
  const hue = name.charCodeAt(0) * 37 % 360;
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", flexShrink: 0,
      background: `linear-gradient(135deg, hsl(${hue},60%,45%), hsl(${(hue + 60) % 360},70%,55%))`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: size * 0.35, fontWeight: 700, color: "#fff",
      fontFamily: "'DM Sans', sans-serif", letterSpacing: 0.5,
    }}>
      {initials}
    </div>
  );
};

// ─── PAGES ─────────────────────────────────────────────────────────────────

const Landing = ({ onSelect }) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", padding: 32 }}>
    <div style={{
      position: "absolute", inset: 0, pointerEvents: "none",
      background: "radial-gradient(ellipse 80% 60% at 50% -20%, rgba(99,102,241,0.18) 0%, transparent 70%)",
    }} />
    <div style={{ textAlign: "center", maxWidth: 520, position: "relative" }}>
      <div style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.3)",
        borderRadius: 99, padding: "6px 16px", marginBottom: 32,
        fontSize: 12, fontWeight: 600, color: "#818cf8", letterSpacing: 1.5, textTransform: "uppercase"
      }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#6366f1", boxShadow: "0 0 8px #6366f1", animation: "pulse 2s infinite" }} />
        AI-Powered Recruitment
      </div>

      <div style={{ fontSize: 56, lineHeight: 1, fontFamily: "'Playfair Display', Georgia, serif", fontWeight: 700, marginBottom: 8 }}>
        <span style={{ color: "#f8fafc" }}>Talent</span>
        <span style={{
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          background: "linear-gradient(135deg, #6366f1, #818cf8, #a78bfa)"
        }}> Scout</span>
      </div>
      <div style={{ fontSize: 15, color: "#94a3b8", marginBottom: 48, lineHeight: 1.7 }}>
        Intelligent candidate screening for <strong style={{ color: "#cbd5e1" }}>Senior Python Backend Engineer</strong>.<br />
        AI-driven analysis · Automated interviews · Smart shortlisting.
      </div>

      <div style={{ display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap" }}>
        <button onClick={() => onSelect("candidate")} style={{
          background: "linear-gradient(135deg, #6366f1, #818cf8)", color: "#fff",
          border: "none", borderRadius: 12, padding: "14px 28px", fontSize: 15, fontWeight: 600,
          cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
          boxShadow: "0 0 32px rgba(99,102,241,0.4)", transition: "all .2s",
          fontFamily: "'DM Sans', sans-serif"
        }}
          onMouseEnter={e => e.currentTarget.style.transform = "translateY(-2px)"}
          onMouseLeave={e => e.currentTarget.style.transform = "translateY(0)"}
        >
          <span style={{ fontSize: 18 }}>👤</span> Apply as Candidate
        </button>
        <button onClick={() => onSelect("hr")} style={{
          background: "rgba(255,255,255,0.05)", color: "#cbd5e1",
          border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12, padding: "14px 28px",
          fontSize: 15, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
          transition: "all .2s", fontFamily: "'DM Sans', sans-serif"
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.08)"; e.currentTarget.style.transform = "translateY(-2px)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; e.currentTarget.style.transform = "translateY(0)"; }}
        >
          <span style={{ fontSize: 18 }}>🔐</span> HR Dashboard
        </button>
      </div>

      <div style={{ display: "flex", gap: 32, marginTop: 64, justifyContent: "center" }}>
        {[["5", "CVs Analyzed"], ["3", "Shortlisted"], ["2", "Interviewed"]].map(([n, l]) => (
          <div key={l} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: "#f8fafc", fontFamily: "'Playfair Display', serif" }}>{n}</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>{l}</div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

const CandidatePortal = ({ onBack, onStartInterview }) => {
  const [phase, setPhase] = useState("menu"); // menu | ingesting | screening | done
  const [logs, setLogs] = useState([]);
  const [progress, setProgress] = useState(0);

  const runPhase = (name) => {
    setPhase(name === "ingest" ? "ingesting" : "screening");
    setLogs([]);
    setProgress(0);
    const msgs = name === "ingest"
      ? ["📄 Processing Alice_Johnson.pdf → alice_johnson", "📄 Processing Bob_Martinez.pdf → bob_martinez", "📄 Processing Carol_White.pdf → carol_white", "📄 Processing David_Chen.pdf → david_chen", "📄 Processing Sara_Patel.pdf → sara_patel", "✅ 5 CVs ingested successfully"]
      : ["🔍 Embedding job description...", "📋 Fetching candidate list from Pinecone...", "👥 Found 5 candidates", "⚙️  Screening: alice_johnson → 91%  ✅ shortlisted", "⚙️  Screening: bob_martinez → 78%  ✅ shortlisted", "⚙️  Screening: carol_white → 72%  ✅ shortlisted", "⚙️  Screening: david_chen → 61%  ✅ shortlisted", "⚙️  Screening: sara_patel → 38%  🔴 rejected", "✅ Screening complete!"];
    let i = 0;
    const t = setInterval(() => {
      if (i < msgs.length) {
        setLogs(l => [...l, msgs[i]]);
        setProgress(Math.round((i + 1) / msgs.length * 100));
        i++;
      } else {
        clearInterval(t);
        setTimeout(() => setPhase("done"), 600);
      }
    }, 500);
  };

  const jobDesc = `Position: Senior Python Backend Engineer\n\nRequirements:\n• 5+ years Python development\n• FastAPI or Django REST Framework\n• PostgreSQL & Redis\n• Docker & Kubernetes\n• AWS, GCP, or Azure\n• Microservices architecture\n• CI/CD (GitHub Actions, Jenkins)\n• Message queues (RabbitMQ, Kafka)`;

  if (phase === "ingesting" || phase === "screening") {
    return (
      <div style={{ padding: "48px 32px", maxWidth: 640, margin: "0 auto" }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#f8fafc", marginBottom: 4 }}>
            {phase === "ingesting" ? "📤 Submitting CVs..." : "🔍 Running AI Screening..."}
          </div>
          <div style={{ fontSize: 13, color: "#64748b" }}>Please wait, do not close this window.</div>
        </div>
        <div style={{ background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.2)", borderRadius: 8, overflow: "hidden", marginBottom: 20 }}>
          <div style={{ height: 4, background: "rgba(255,255,255,0.06)" }}>
            <div style={{ width: `${progress}%`, height: "100%", background: "linear-gradient(90deg,#6366f1,#818cf8)", transition: "width .4s" }} />
          </div>
          <div style={{ padding: 16, fontFamily: "'DM Mono', 'Courier New', monospace", fontSize: 12, color: "#94a3b8", maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
            {logs.map((l, i) => <div key={i} style={{ color: l.startsWith("✅") ? "#10b981" : l.startsWith("❌") || l.includes("rejected") ? "#ef4444" : "#94a3b8" }}>{l}</div>)}
            {progress < 100 && <div style={{ color: "#6366f1" }}>█ <span style={{ animation: "blink 1s infinite" }}>_</span></div>}
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#475569" }}>{progress}% complete</div>
      </div>
    );
  }

  return (
    <div style={{ padding: "48px 32px", maxWidth: 800, margin: "0 auto" }}>
      <button onClick={onBack} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6, marginBottom: 32, fontFamily: "'DM Sans', sans-serif" }}>
        ← Back to home
      </button>

      <div style={{ marginBottom: 40 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#6366f1", letterSpacing: 1, textTransform: "uppercase", marginBottom: 8 }}>Candidate Portal</div>
        <h1 style={{ fontSize: 32, fontWeight: 700, color: "#f8fafc", fontFamily: "'Playfair Display', serif", margin: 0, marginBottom: 4 }}>Senior Python Backend Engineer</h1>
        <div style={{ fontSize: 14, color: "#64748b" }}>TechCorp · Full-time · Remote friendly</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 32 }}>
        {[
          { icon: "📤", title: "Submit CV", desc: "Upload your PDF to the screening system", action: () => runPhase("ingest"), color: "#6366f1" },
          { icon: "🔍", title: "Run AI Screening", desc: "AI matches your profile to job requirements", action: () => runPhase("screen"), color: "#8b5cf6" },
          { icon: "💬", title: "Start Interview", desc: "Answer gap-filling questions with AI interviewer", action: onStartInterview, color: "#06b6d4" },
        ].map(({ icon, title, desc, action, color }) => (
          <button key={title} onClick={action} style={{
            background: "rgba(255,255,255,0.03)", border: `1px solid rgba(255,255,255,0.08)`,
            borderRadius: 16, padding: "20px 22px", cursor: "pointer", textAlign: "left",
            transition: "all .2s", fontFamily: "'DM Sans', sans-serif",
            gridColumn: title === "Start Interview" ? "1 / span 2" : "auto"
          }}
            onMouseEnter={e => { e.currentTarget.style.background = `${color}10`; e.currentTarget.style.borderColor = `${color}40`; e.currentTarget.style.transform = "translateY(-1px)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)"; e.currentTarget.style.transform = "translateY(0)"; }}
          >
            <div style={{ fontSize: 26, marginBottom: 10 }}>{icon}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#f1f5f9", marginBottom: 4 }}>{title}</div>
            <div style={{ fontSize: 13, color: "#64748b" }}>{desc}</div>
          </button>
        ))}
      </div>

      <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 16, padding: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", letterSpacing: 1, textTransform: "uppercase", marginBottom: 12 }}>Job Description</div>
        <pre style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: "#64748b", margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.8 }}>{jobDesc}</pre>
      </div>
    </div>
  );
};

const InterviewChat = ({ candidate, onBack }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [qIndex, setQIndex] = useState(0);
  const [done, setDone] = useState(false);
  const [typing, setTyping] = useState(false);
  const bottomRef = useRef();

  useEffect(() => {
    setTimeout(() => {
      setTyping(true);
      setTimeout(() => {
        setTyping(false);
        setMessages([{
          role: "assistant",
          text: `Hello **${candidate.name}**! 👋\n\nYou've been shortlisted for **Senior Python Backend Engineer**. I have ${CHAT_QUESTIONS.length} questions to better understand your background.\n\n---\n\n**Question 1 of ${CHAT_QUESTIONS.length}**\n\n${CHAT_QUESTIONS[0]}`
        }]);
      }, 1200);
    }, 300);
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, typing]);

  const send = () => {
    if (!input.trim() || done) return;
    const ans = input.trim();
    setInput("");
    setMessages(m => [...m, { role: "user", text: ans }]);
    const next = qIndex + 1;
    setQIndex(next);
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      if (next < CHAT_QUESTIONS.length) {
        setMessages(m => [...m, { role: "assistant", text: `**Question ${next + 1} of ${CHAT_QUESTIONS.length}**\n\n${CHAT_QUESTIONS[next]}` }]);
      } else {
        setDone(true);
        setMessages(m => [...m, { role: "assistant", text: `✅ **Thank you! Your pre-screening is complete.**\n\nOur HR team will review your profile and contact you within 3–5 business days.\n\n---\n\n**Final Score: 95%** 📈 +4%\n\nYou demonstrated strong technical depth. Your profile has been forwarded to the recruitment team.` }]);
      }
    }, 1400);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", maxWidth: 680, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.08)", display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <button onClick={onBack} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>←</button>
        <div style={{ width: 36, height: 36, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>🤖</div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9" }}>AI Interviewer</div>
          <div style={{ fontSize: 11, color: "#10b981", display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10b981", boxShadow: "0 0 6px #10b981" }} /> Online
          </div>
        </div>
        <div style={{ marginLeft: "auto", fontSize: 12, color: "#475569" }}>
          {candidate.name} · Score: <span style={{ color: "#f59e0b", fontWeight: 700 }}>{Math.round(candidate.score * 100)}%</span>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 24px 0" }}>
        {messages.map((m, i) => (
          <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: 16 }}>
            {m.role === "assistant" && (
              <div style={{ width: 28, height: 28, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0, marginRight: 10, marginTop: 2 }}>🤖</div>
            )}
            <div style={{
              maxWidth: "75%", background: m.role === "user" ? "linear-gradient(135deg,#6366f1,#818cf8)" : "rgba(255,255,255,0.05)",
              border: m.role === "user" ? "none" : "1px solid rgba(255,255,255,0.08)",
              borderRadius: m.role === "user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
              padding: "12px 16px", fontSize: 14, color: "#f1f5f9", lineHeight: 1.6,
              fontFamily: "'DM Sans', sans-serif",
            }}>
              {m.text.split("\n").map((line, j) => {
                const bold = line.replace(/\*\*(.+?)\*\*/g, (_, t) => `<strong>${t}</strong>`);
                return <div key={j} style={{ marginBottom: line === "---" ? 8 : 2 }} dangerouslySetInnerHTML={{ __html: line === "---" ? "<hr style='border-color:rgba(255,255,255,0.1);margin:8px 0'/>" : bold || "&nbsp;" }} />;
              })}
            </div>
          </div>
        ))}
        {typing && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <div style={{ width: 28, height: 28, borderRadius: "50%", background: "linear-gradient(135deg,#6366f1,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>🤖</div>
            <div style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "18px 18px 18px 4px", padding: "12px 18px", display: "flex", gap: 4 }}>
              {[0, 1, 2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: "#6366f1", display: "inline-block", animation: `bounce 1.2s ${i * 0.2}s infinite` }} />)}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 24, borderTop: "1px solid rgba(255,255,255,0.08)" }}>
        {!done ? (
          <div style={{ display: "flex", gap: 10 }}>
            <input value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
              placeholder="Type your answer..." disabled={typing}
              style={{
                flex: 1, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 12, padding: "12px 16px", color: "#f1f5f9", fontSize: 14,
                outline: "none", fontFamily: "'DM Sans', sans-serif",
              }} />
            <button onClick={send} disabled={!input.trim() || typing} style={{
              background: "linear-gradient(135deg,#6366f1,#818cf8)", border: "none", borderRadius: 12,
              padding: "12px 20px", color: "#fff", fontSize: 18, cursor: "pointer",
              opacity: !input.trim() || typing ? 0.5 : 1, transition: "opacity .2s",
            }}>↑</button>
          </div>
        ) : (
          <button onClick={onBack} style={{ width: "100%", background: "linear-gradient(135deg,#10b981,#059669)", border: "none", borderRadius: 12, padding: "14px", color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            ← Back to Portal
          </button>
        )}
      </div>
    </div>
  );
};

const HRLogin = ({ onLogin, onBack }) => {
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const attempt = () => {
    setLoading(true);
    setError("");
    setTimeout(() => {
      if (pw === "hr1234") onLogin();
      else { setError("Incorrect password. Please try again."); setLoading(false); }
    }, 800);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
      <div style={{ width: "100%", maxWidth: 380, padding: 32 }}>
        <button onClick={onBack} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6, marginBottom: 32, fontFamily: "'DM Sans', sans-serif" }}>← Back</button>

        <div style={{ fontSize: 32, marginBottom: 8 }}>🔐</div>
        <h2 style={{ fontSize: 26, fontWeight: 700, color: "#f8fafc", fontFamily: "'Playfair Display', serif", margin: "0 0 4px" }}>HR Admin Access</h2>
        <p style={{ fontSize: 14, color: "#64748b", margin: "0 0 32px" }}>Enter your credentials to access the dashboard.</p>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", letterSpacing: 0.5, display: "block", marginBottom: 8 }}>PASSWORD</label>
          <input type="password" value={pw} onChange={e => setPw(e.target.value)}
            onKeyDown={e => e.key === "Enter" && attempt()}
            placeholder="Enter HR password"
            style={{
              width: "100%", background: "rgba(255,255,255,0.05)", border: `1px solid ${error ? "#ef4444" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 10, padding: "12px 14px", color: "#f1f5f9", fontSize: 14,
              outline: "none", fontFamily: "'DM Sans', sans-serif", boxSizing: "border-box"
            }} />
          {error && <div style={{ fontSize: 12, color: "#ef4444", marginTop: 6 }}>❌ {error}</div>}
        </div>

        <button onClick={attempt} disabled={!pw || loading} style={{
          width: "100%", background: "linear-gradient(135deg,#6366f1,#818cf8)", border: "none",
          borderRadius: 10, padding: "13px", color: "#fff", fontSize: 14, fontWeight: 600,
          cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: !pw || loading ? 0.7 : 1,
        }}>
          {loading ? "Verifying..." : "Access Dashboard →"}
        </button>

        <div style={{ marginTop: 16, fontSize: 12, color: "#475569", textAlign: "center" }}>
          Demo password: <code style={{ color: "#818cf8" }}>hr1234</code>
        </div>
      </div>
    </div>
  );
};

const HRDashboard = ({ onBack }) => {
  const [selected, setSelected] = useState(null);
  const ranked = [...CANDIDATES].sort((a, b) => (b.finalScore || b.score) - (a.finalScore || a.score));
  const top3 = ranked.filter(c => c.status !== "rejected").slice(0, 3);
  const medals = ["🥇", "🥈", "🥉"];

  if (selected) {
    const c = selected;
    const profile = { skills: c.skills, experience: c.experience };
    return (
      <div style={{ padding: "40px 32px", maxWidth: 700, margin: "0 auto" }}>
        <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 6, marginBottom: 32, fontFamily: "'DM Sans', sans-serif" }}>← Back to Dashboard</button>

        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 32 }}>
          <Avatar name={c.name} size={56} />
          <div>
            <h2 style={{ fontSize: 24, fontWeight: 700, color: "#f8fafc", margin: "0 0 4px", fontFamily: "'Playfair Display', serif" }}>{c.name}</h2>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 13, color: "#64748b" }}>{c.role}</div>
              <Badge status={c.status} />
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
          {[
            { label: "Initial Score", value: `${Math.round(c.score * 100)}%` },
            { label: "Final Score", value: `${Math.round((c.finalScore || c.score) * 100)}%`, highlight: true },
            { label: "Experience", value: `${c.experience} years` },
          ].map(({ label, value, highlight }) => (
            <div key={label} style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>{label}</div>
              <div style={{ fontSize: 24, fontWeight: 800, color: highlight ? "#10b981" : "#f1f5f9", fontFamily: "'DM Mono', monospace" }}>{value}</div>
            </div>
          ))}
        </div>

        <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 12, padding: 20, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 14 }}>Skills & Technologies</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {c.skills.map(s => (
              <span key={s} style={{ background: "rgba(99,102,241,0.12)", color: "#818cf8", border: "1px solid rgba(99,102,241,0.25)", borderRadius: 6, padding: "4px 10px", fontSize: 12, fontWeight: 600 }}>{s}</span>
            ))}
          </div>
        </div>

        {c.gaps.filter(g => g.status === "answered").length > 0 && (
          <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 14 }}>Interview Q&A</div>
            {c.gaps.filter(g => g.status === "answered").map((g, i) => (
              <div key={i} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <div style={{ fontSize: 13, color: "#94a3b8", marginBottom: 6 }}>Q: {g.req}</div>
                <div style={{ fontSize: 14, color: "#f1f5f9", background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: 8, padding: "8px 12px" }}>→ {g.answer}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ padding: "40px 32px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 40 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#6366f1", letterSpacing: 1, textTransform: "uppercase", marginBottom: 6 }}>HR Admin Dashboard</div>
          <h1 style={{ fontSize: 30, fontWeight: 700, color: "#f8fafc", fontFamily: "'Playfair Display', serif", margin: 0 }}>Candidate Review</h1>
        </div>
        <button onClick={onBack} style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: "8px 16px", color: "#94a3b8", cursor: "pointer", fontSize: 13, fontFamily: "'DM Sans', sans-serif" }}>← Logout</button>
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 36 }}>
        {[
          { label: "Total Candidates", value: CANDIDATES.length, color: "#6366f1" },
          { label: "Ready for HR", value: CANDIDATES.filter(c => c.status === "ready_for_hr").length, color: "#10b981" },
          { label: "Shortlisted", value: CANDIDATES.filter(c => c.status === "shortlisted").length, color: "#f59e0b" },
          { label: "Rejected", value: CANDIDATES.filter(c => c.status === "rejected").length, color: "#ef4444" },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${color}22`, borderRadius: 14, padding: "18px 20px" }}>
            <div style={{ fontSize: 30, fontWeight: 800, color, fontFamily: "'Playfair Display', serif" }}>{value}</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Top 3 */}
      <div style={{ marginBottom: 36 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 16 }}>🏆 Top Candidates — Recommended for Interview</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
          {top3.map((c, i) => (
            <button key={c.id} onClick={() => setSelected(c)} style={{
              background: i === 0 ? "linear-gradient(135deg, rgba(99,102,241,0.15), rgba(139,92,246,0.08))" : "rgba(255,255,255,0.03)",
              border: i === 0 ? "1px solid rgba(99,102,241,0.3)" : "1px solid rgba(255,255,255,0.08)",
              borderRadius: 16, padding: 20, cursor: "pointer", textAlign: "left",
              transition: "all .2s", fontFamily: "'DM Sans', sans-serif",
            }}
              onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.borderColor = "#6366f155"; }}
              onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.borderColor = i === 0 ? "rgba(99,102,241,0.3)" : "rgba(255,255,255,0.08)"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                <span style={{ fontSize: 20 }}>{medals[i]}</span>
                <Avatar name={c.name} size={32} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: "#64748b" }}>{c.experience}y exp</div>
                </div>
              </div>
              <ScoreBar score={c.finalScore || c.score} />
              <div style={{ marginTop: 10 }}>
                <Badge status={c.status} />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* All candidates */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 14 }}>📊 All Candidates</div>
        <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 16, overflow: "hidden" }}>
          {ranked.map((c, i) => (
            <button key={c.id} onClick={() => setSelected(c)} style={{
              display: "flex", alignItems: "center", gap: 16, width: "100%",
              padding: "16px 20px", borderBottom: i < ranked.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
              background: "none", border: "none", cursor: "pointer", textAlign: "left",
              transition: "background .15s", fontFamily: "'DM Sans', sans-serif",
            }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
              onMouseLeave={e => e.currentTarget.style.background = "none"}
            >
              <span style={{ fontSize: 13, color: "#475569", width: 20, textAlign: "right", flexShrink: 0 }}>{i + 1}</span>
              <Avatar name={c.name} size={36} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#f1f5f9" }}>{c.name}</div>
                <div style={{ fontSize: 12, color: "#64748b" }}>{c.role} · {c.experience}y</div>
              </div>
              <div style={{ width: 160, flexShrink: 0 }}><ScoreBar score={c.finalScore || c.score} size="sm" /></div>
              <div style={{ flexShrink: 0 }}><Badge status={c.status} /></div>
              <div style={{ fontSize: 12, color: "#6366f1", flexShrink: 0 }}>→</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── ROOT ──────────────────────────────────────────────────────────────────

export default function App() {
  const [page, setPage] = useState("landing"); // landing | candidate | hr_login | hr | interview
  const [interviewCandidate, setInterviewCandidate] = useState(null);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
        body { margin: 0; background: #0a0c14; color: #f1f5f9; font-family: 'DM Sans', sans-serif; }
        input::placeholder { color: #475569; }
        input:focus { border-color: rgba(99,102,241,0.5) !important; box-shadow: 0 0 0 3px rgba(99,102,241,0.12); }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.6;transform:scale(1.2)} }
        @keyframes bounce { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-5px)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
      `}</style>

      {page === "landing" && <Landing onSelect={r => setPage(r === "candidate" ? "candidate" : "hr_login")} />}
      {page === "candidate" && (
        <CandidatePortal
          onBack={() => setPage("landing")}
          onStartInterview={() => {
            setInterviewCandidate(CANDIDATES.find(c => c.status === "shortlisted" || c.status === "ready_for_hr"));
            setPage("interview");
          }}
        />
      )}
      {page === "interview" && interviewCandidate && (
        <InterviewChat candidate={interviewCandidate} onBack={() => setPage("candidate")} />
      )}
      {page === "hr_login" && <HRLogin onLogin={() => setPage("hr")} onBack={() => setPage("landing")} />}
      {page === "hr" && <HRDashboard onBack={() => setPage("landing")} />}
    </>
  );
}
