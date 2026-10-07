import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  api,
  type AssistantEvent,
  type LlmProfile,
  type PendingMutation,
} from "../api/client";

type Props = {
  documentId: number;
  onMessage?: (msg: string) => void;
  onError?: (msg: string) => void;
  onGraphChanged?: () => void;
};

const ROLE_LABEL: Record<string, string> = {
  user: "Вы",
  assistant: "Ассистент",
  tool: "Шаг",
  decision: "Итог",
};

export default function AssistantChatPanel({
  documentId,
  onMessage,
  onError,
  onGraphChanged,
}: Props) {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<AssistantEvent[]>([]);
  const [pending, setPending] = useState<PendingMutation[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await api.listProfiles();
        setProfiles(res.profiles);
        if (res.profiles[0]) setProfileId(res.profiles[0].id);
      } catch (err) {
        onError?.(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    setEvents([]);
    setPending([]);
    void (async () => {
      try {
        const thread = await api.assistantThread(documentId);
        if (cancelled) return;
        setEvents(thread.events || []);
        setPending(thread.pending_mutations || []);
      } catch (err) {
        if (!cancelled) {
          onError?.(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, onError]);

  useEffect(() => {
    const node = logRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [events, busy]);

  const canSend = useMemo(
    () => Boolean(input.trim()) && Boolean(profileId) && !busy,
    [input, profileId, busy],
  );

  const onSend = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend) return;
    const text = input.trim();
    const pendingBefore = pending.length;
    setInput("");
    setBusy(true);
    try {
      const res = await api.assistantChat({
        document_id: documentId,
        content: text,
        llm_profile_id: profileId,
      });
      setEvents(res.events || []);
      setPending(res.pending_mutations || []);
      const added = (res.pending_mutations || []).length - pendingBefore;
      if (added > 0) {
        onMessage?.(`Ассистент предложил действий: ${added}`);
      }
    } catch (err) {
      setInput(text);
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const confirmOne = async (mut: PendingMutation) => {
    setBusy(true);
    try {
      const res = await api.assistantConfirm({
        document_id: documentId,
        mutations: [mut],
      });
      setEvents(res.events || []);
      setPending(res.pending_mutations || []);
      if (res.errors?.length) {
        onError?.(res.errors.map((e) => e.error).join("; "));
      } else {
        onMessage?.(mut.summary || "Действие применено");
        onGraphChanged?.();
      }
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const rejectOne = async (mut: PendingMutation) => {
    if (!mut.id) {
      setPending((list) => list.filter((m) => m !== mut));
      return;
    }
    setBusy(true);
    try {
      const res = await api.assistantReject({
        document_id: documentId,
        mutation_ids: [mut.id],
      });
      setEvents(res.events || []);
      setPending(res.pending_mutations || []);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const confirmAll = async () => {
    if (!pending.length) return;
    setBusy(true);
    try {
      const res = await api.assistantConfirm({
        document_id: documentId,
        mutations: pending,
      });
      setEvents(res.events || []);
      setPending(res.pending_mutations || []);
      if (res.errors?.length) {
        onError?.(res.errors.map((e) => e.error).join("; "));
      }
      if (res.applied?.length) {
        onMessage?.(`Применено: ${res.applied.length}`);
        onGraphChanged?.();
      }
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="assistant-chat stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Ассистент</h3>
        <label className="row">
          <span className="muted">Модель</span>
          <select
            value={profileId}
            onChange={(e) => setProfileId(e.target.value)}
            disabled={busy}
          >
            {profiles.length === 0 ? (
              <option value="">Нет профилей</option>
            ) : null}
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">
        История сохраняется для этой статьи. Шаги вроде поиска и предложений
        остаются в журнале.
      </p>

      <div className="chat-log" ref={logRef}>
        {events.length === 0 && !busy ? (
          <p className="muted">Напишите запрос к графу или тексту статьи.</p>
        ) : (
          events.map((event) => (
            <div
              key={event.id}
              className={`chat-bubble chat-${event.kind} ${event.status || ""}`}
            >
              <div className="chat-role">
                {ROLE_LABEL[event.kind] || "Ассистент"}
                {event.tool ? <span className="badge">{event.tool}</span> : null}
                {event.status === "accepted" ? (
                  <span className="badge">принято</span>
                ) : null}
                {event.status === "rejected" ? (
                  <span className="badge warn">отклонено</span>
                ) : null}
              </div>
              <div className="chat-content">{event.content}</div>
            </div>
          ))
        )}
        {busy ? <p className="muted">Ассистент работает…</p> : null}
      </div>

      {pending.length > 0 ? (
        <div className="pending-mutations stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>Предложения ({pending.length})</strong>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void confirmAll()}
            >
              Подтвердить все
            </button>
          </div>
          <ul className="list compact">
            {pending.map((m) => (
              <li key={m.id || JSON.stringify(m.args)}>
                <div>
                  <span className="badge">{m.action || m.tool}</span>{" "}
                  {m.summary || "действие"}
                </div>
                <div className="row">
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => void confirmOne(m)}
                  >
                    Принять
                  </button>
                  <button
                    type="button"
                    className="btn secondary"
                    disabled={busy}
                    onClick={() => void rejectOne(m)}
                  >
                    Отклонить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <form className="row chat-input" onSubmit={(e) => void onSend(e)}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Сообщение ассистенту…"
          disabled={busy || !profileId}
        />
        <button type="submit" className="btn" disabled={!canSend}>
          {busy ? "…" : "Отправить"}
        </button>
      </form>
    </div>
  );
}
