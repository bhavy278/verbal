import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  Phone, PhoneCall, Send, Wrench, CheckCircle2, Clock, Utensils, Receipt, Sparkles,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CHIPS = [
  "I'd like a large pepperoni pizza with extra cheese",
  "Make that two",
  "And a can of soda",
  "What's my total?",
  "Yes, place the order",
];

const STATUS_COLORS = {
  draft: "text-[var(--v-muted)] border-[var(--v-border)]",
  quoted: "text-[var(--v-amber)] border-[var(--v-amber)]",
  confirmed: "text-[var(--v-amber)] border-[var(--v-amber)]",
  submitted: "text-[var(--v-terra)] border-[var(--v-terra)]",
  accepted: "text-emerald-400 border-emerald-500",
};

function StatusBadge({ status }) {
  const cls = STATUS_COLORS[status] || STATUS_COLORS.draft;
  return (
    <span data-testid="order-status" className={`text-xs uppercase tracking-widest px-2 py-1 border rounded-full ${cls}`}>
      {status || "idle"}
    </span>
  );
}

function ToolChips({ tools }) {
  if (!tools?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {tools.map((t, i) => (
        <span key={i} className="inline-flex items-center gap-1 text-[10px] text-[var(--v-amber)] bg-[var(--v-amber)]/10 border border-[var(--v-amber)]/25 rounded px-1.5 py-0.5">
          <Wrench size={10} /> {t.tool}
        </span>
      ))}
    </div>
  );
}

function Message({ m }) {
  const isAgent = m.role === "agent";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
      className={`flex ${isAgent ? "justify-start" : "justify-end"}`}
      data-testid={`msg-${m.role}`}
    >
      <div className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
        isAgent ? "bg-[var(--v-panel-2)] text-[var(--v-cream)] rounded-tl-sm border border-[var(--v-border)]"
                : "bg-[var(--v-amber)] text-[#14110d] rounded-tr-sm font-medium"}`}>
        <div className="flex items-center gap-1.5 mb-0.5 text-[10px] uppercase tracking-widest opacity-60">
          {isAgent ? <><PhoneCall size={11}/> Verbal</> : "Caller"}
        </div>
        {m.text}
        {isAgent && <ToolChips tools={m.tools} />}
      </div>
    </motion.div>
  );
}

function OrderTicket({ order }) {
  const q = order?.quote;
  return (
    <div className="bg-[var(--v-panel)] border border-[var(--v-border)] rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 text-[var(--v-cream)] font-display font-semibold">
          <Receipt size={16} className="text-[var(--v-terra)]" /> Live Order
        </div>
        <StatusBadge status={order?.status} />
      </div>
      {!order?.lines?.length ? (
        <p className="text-[var(--v-muted)] text-sm py-8 text-center">No items yet — start a call.</p>
      ) : (
        <div className="space-y-2.5">
          {order.lines.map((l) => (
            <div key={l.line_id} className="flex justify-between gap-3 text-sm border-b border-dashed border-[var(--v-border)] pb-2.5">
              <div className="text-[var(--v-cream)]">
                <span className="text-[var(--v-amber)] font-semibold">{l.quantity}×</span> {l.description}
              </div>
              <div className="text-[var(--v-cream)] whitespace-nowrap font-medium" data-testid="line-total">{l.line_total.display}</div>
            </div>
          ))}
          {q && (
            <div className="pt-2 space-y-1 text-sm">
              <Row label="Subtotal" value={q.subtotal.display} />
              <Row label="Tax" value={q.tax.display} />
              <div className="flex justify-between pt-1.5 mt-1 border-t border-[var(--v-border)] text-[var(--v-cream)] font-display font-bold text-lg">
                <span>Total</span><span data-testid="order-total">{q.total.display}</span>
              </div>
            </div>
          )}
          {order.pos_order_id && (
            <div className="mt-3 flex items-center gap-2 text-emerald-400 text-sm" data-testid="pos-confirmation">
              <CheckCircle2 size={16} /> Accepted by POS · {order.pos_order_id}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const Row = ({ label, value }) => (
  <div className="flex justify-between text-[var(--v-muted)]">
    <span>{label}</span><span>{value}</span>
  </div>
);

function MenuCard({ menu }) {
  if (!menu) return null;
  return (
    <div className="bg-[var(--v-panel)] border border-[var(--v-border)] rounded-xl p-5">
      <div className="flex items-center gap-2 text-[var(--v-cream)] font-display font-semibold mb-3">
        <Utensils size={16} className="text-[var(--v-terra)]" /> {menu.name}
      </div>
      <div className="grid grid-cols-1 gap-1.5">
        {menu.items.map((it) => (
          <div key={it.id} className="flex justify-between text-xs text-[var(--v-muted)]">
            <span className="text-[var(--v-cream)]">{it.name}</span>
            <span>{it.variants.map((v) => `$${(v.price/100).toFixed(2)}`).join(" / ")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [menu, setMenu] = useState(null);
  const [callSid, setCallSid] = useState(null);
  const [messages, setMessages] = useState([]);
  const [order, setOrder] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => { axios.get(`${API}/menu`).then((r) => setMenu(r.data)).catch(() => {}); }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" }); }, [messages]);

  const startCall = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/voice/simulate/start`, {});
      setCallSid(data.call_sid);
      setMessages([{ role: "agent", text: data.reply }]);
      setOrder(null);
    } finally { setBusy(false); }
  };

  const refreshOrder = async (id) => {
    if (!id) return;
    try { const { data } = await axios.get(`${API}/orders/${id}`); setOrder(data); } catch {}
  };

  const send = async (text) => {
    if (!text.trim() || !callSid || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/voice/simulate/turn`, { call_sid: callSid, text });
      setMessages((m) => [...m, { role: "agent", text: data.reply, tools: data.tool_calls }]);
      if (data.order) { setOrder(data.order); if (data.order.status === "submitted") setTimeout(() => refreshOrder(data.order.order_id), 1500); }
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen v-grain text-[var(--v-cream)]" style={{ background: "var(--v-bg)" }}>
      <header className="border-b border-[var(--v-border)] bg-[var(--v-panel)]/60 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[var(--v-terra)] flex items-center justify-center">
              <Phone size={18} className="text-[#14110d]" />
            </div>
            <div>
              <div className="font-display font-extrabold text-xl leading-none">Verbal</div>
              <div className="text-[10px] uppercase tracking-[0.25em] text-[var(--v-muted)]">Voice Ordering Console</div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--v-muted)]">
            <span className="v-live-dot w-2 h-2 rounded-full bg-emerald-400" /> server-authoritative · mock voice model
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 grid lg:grid-cols-[1.6fr_1fr] gap-6">
        {/* Call console */}
        <section className="bg-[var(--v-panel)] border border-[var(--v-border)] rounded-2xl flex flex-col overflow-hidden" style={{ minHeight: 560 }}>
          <div className="px-5 py-4 border-b border-[var(--v-border)] flex items-center justify-between">
            <div className="font-display font-semibold flex items-center gap-2"><PhoneCall size={16} className="text-[var(--v-amber)]" /> Call Simulator</div>
            {!callSid ? (
              <button data-testid="start-call-btn" onClick={startCall} disabled={busy}
                className="inline-flex items-center gap-2 bg-[var(--v-terra)] hover:brightness-110 transition text-[#14110d] font-semibold text-sm px-4 py-2 rounded-full disabled:opacity-50">
                <Phone size={14} /> Start Call
              </button>
            ) : (
              <span className="text-[10px] text-[var(--v-muted)] font-mono">{callSid}</span>
            )}
          </div>

          <div ref={scrollRef} className="v-scroll flex-1 overflow-y-auto px-5 py-5 space-y-3">
            {!messages.length && (
              <div className="h-full flex flex-col items-center justify-center text-center text-[var(--v-muted)] gap-3 py-16">
                <Sparkles className="text-[var(--v-amber)]" />
                <p className="max-w-xs text-sm">Press <span className="text-[var(--v-cream)]">Start Call</span> to talk to the ordering agent. Every price and total is computed by the server — the agent only reads them back.</p>
              </div>
            )}
            <AnimatePresence>{messages.map((m, i) => <Message key={i} m={m} />)}</AnimatePresence>
          </div>

          {callSid && (
            <div className="border-t border-[var(--v-border)] p-4 space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {CHIPS.map((c) => (
                  <button key={c} data-testid="chip" onClick={() => send(c)} disabled={busy}
                    className="text-[11px] text-[var(--v-muted)] hover:text-[var(--v-cream)] hover:border-[var(--v-amber)] border border-[var(--v-border)] rounded-full px-2.5 py-1 transition disabled:opacity-40">
                    {c}
                  </button>
                ))}
              </div>
              <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex gap-2">
                <input data-testid="turn-input" value={input} onChange={(e) => setInput(e.target.value)}
                  placeholder="Speak to Verbal…" disabled={busy}
                  className="flex-1 bg-[var(--v-panel-2)] border border-[var(--v-border)] focus:border-[var(--v-amber)] outline-none rounded-xl px-4 py-2.5 text-sm text-[var(--v-cream)] placeholder:text-[var(--v-muted)] transition" />
                <button data-testid="send-turn-btn" type="submit" disabled={busy || !input.trim()}
                  className="bg-[var(--v-amber)] hover:brightness-110 transition text-[#14110d] rounded-xl px-4 disabled:opacity-40">
                  <Send size={16} />
                </button>
              </form>
            </div>
          )}
        </section>

        {/* Right rail */}
        <section className="space-y-6">
          <OrderTicket order={order} />
          <MenuCard menu={menu} />
          <div className="flex items-center gap-2 text-[11px] text-[var(--v-muted)] px-1">
            <Clock size={12} /> Outbox worker delivers to the sandbox POS asynchronously.
          </div>
        </section>
      </main>
    </div>
  );
}
