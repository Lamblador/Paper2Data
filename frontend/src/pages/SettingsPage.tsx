import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type LlmProfile } from "../api/client";
import { useProject } from "../store/project";

const emptyForm = {
  name: "",
  base_url: "https://api.openai.com/v1",
  model: "gpt-4o-mini",
  api_key: "",
  price_in_per_1m: 0,
  price_out_per_1m: 0,
  context_size: 128000,
  intelligence_level: "medium",
  supports_json_mode: true,
};

export default function SettingsPage() {
  const { project } = useProject();
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLElement>(null);

  const load = async () => {
    if (!project) {
      setProfiles([]);
      return;
    }
    const data = await api.listProfiles();
    setProfiles(data.profiles);
  };

  useEffect(() => {
    void load().catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [project]);

  if (!project) {
    return (
      <section className="panel">
        <h1>Настройки</h1>
        <p className="muted">Сначала откройте или создайте проект.</p>
      </section>
    );
  }

  const startEdit = (profile: LlmProfile) => {
    setEditingId(profile.id);
    setForm({
      name: profile.name,
      base_url: profile.base_url,
      model: profile.model,
      api_key: "",
      price_in_per_1m: profile.price_in_per_1m,
      price_out_per_1m: profile.price_out_per_1m,
      context_size: profile.context_size,
      intelligence_level: profile.intelligence_level || "medium",
      supports_json_mode: profile.supports_json_mode,
    });
    setError(null);
    setMessage(null);
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
    setError(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (editingId) {
        const body: Record<string, unknown> = { ...form };
        if (!form.api_key.trim()) delete body.api_key;
        await api.updateProfile(editingId, body);
        setEditingId(null);
        setForm(emptyForm);
        setMessage("Профиль обновлён.");
      } else {
        await api.addProfile({
          ...form,
          api_key: form.api_key || null,
        });
        setForm(emptyForm);
        setMessage("Профиль добавлен. Ключ сохранён в ~/.paper2data/secrets.");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <section className="panel">
        <h1>Настройки LLM</h1>
        <p className="muted">
          Профили хранятся в <code>project.yaml</code>. API-ключи — отдельно в{" "}
          <code>~/.paper2data/secrets</code> (не попадают в папку проекта).
        </p>
      </section>

      <section className="panel" ref={formRef}>
        <h2>{editingId ? "Изменить профиль" : "Добавить профиль"}</h2>
        <form className="stack" onSubmit={onSubmit}>
          <div className="grid-2">
            <label>
              Название
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="OpenRouter / DeepSeek / Ollama"
              />
            </label>
            <label>
              Модель
              <input
                required
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
            </label>
            <label>
              Base URL
              <input
                required
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              />
            </label>
            <label>
              API-ключ
              <input
                type="password"
                value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder={
                  editingId
                    ? "пусто — ключ не менять"
                    : "необязательно для локальных серверов"
                }
              />
            </label>
            <label>
              Цена вход / 1M токенов
              <input
                type="number"
                step="0.01"
                value={form.price_in_per_1m}
                onChange={(e) =>
                  setForm({ ...form, price_in_per_1m: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Цена выход / 1M токенов
              <input
                type="number"
                step="0.01"
                value={form.price_out_per_1m}
                onChange={(e) =>
                  setForm({ ...form, price_out_per_1m: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Окно контекста, токены
              <input
                type="number"
                min={1}
                step={1}
                required
                value={form.context_size}
                onChange={(e) =>
                  setForm({ ...form, context_size: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Уровень интеллекта
              <select
                value={form.intelligence_level}
                onChange={(e) =>
                  setForm({ ...form, intelligence_level: e.target.value })
                }
              >
                <option value="low">низкий</option>
                <option value="medium">средний</option>
                <option value="high">высокий</option>
              </select>
            </label>
          </div>
          <label className="row" style={{ justifyContent: "flex-start" }}>
            <input
              type="checkbox"
              checked={form.supports_json_mode}
              onChange={(e) =>
                setForm({ ...form, supports_json_mode: e.target.checked })
              }
            />
            Поддержка JSON-режима
          </label>
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>
              {editingId ? "Сохранить изменения" : "Сохранить профиль"}
            </button>
            {editingId ? (
              <button
                className="btn secondary"
                type="button"
                disabled={busy}
                onClick={cancelEdit}
              >
                Отмена
              </button>
            ) : null}
          </div>
        </form>
        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
      </section>

      <section className="panel">
        <h2>Профили проекта</h2>
        {profiles.length === 0 ? (
          <p className="muted">Профилей пока нет.</p>
        ) : (
          <ul className="list">
            {profiles.map((p) => (
              <li key={p.id}>
                <div>
                  <div>
                    <strong>{p.name}</strong>{" "}
                    <span className="badge">{p.model}</span>{" "}
                    {p.has_api_key ? (
                      <span className="badge">ключ есть</span>
                    ) : (
                      <span className="badge warn">без ключа</span>
                    )}
                  </div>
                  <div className="muted path">{p.base_url}</div>
                  <div className="muted">
                    контекст {p.context_size.toLocaleString("ru-RU")} ток. ·{" "}
                    {p.price_in_per_1m}/{p.price_out_per_1m} $ за 1M
                  </div>
                </div>
                <div className="row">
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={busy}
                    onClick={() => startEdit(p)}
                  >
                    Изменить
                  </button>
                  <button
                    className="btn secondary"
                    disabled={busy}
                    onClick={() =>
                      void (async () => {
                        setBusy(true);
                        setError(null);
                        setMessage(null);
                        try {
                          const res = await api.testProfile(p.id);
                          if (res.ok) {
                            setMessage(
                              `Подключение OK (${p.name}): ${res.reply_preview || "ответ получен"}`,
                            );
                          } else {
                            setError(res.error || "Ошибка подключения");
                          }
                        } catch (err) {
                          setError(
                            err instanceof Error ? err.message : String(err),
                          );
                        } finally {
                          setBusy(false);
                        }
                      })()
                    }
                  >
                    Проверить
                  </button>
                  <button
                    className="btn danger"
                    disabled={busy}
                    onClick={() =>
                      void (async () => {
                        if (!confirm(`Удалить профиль «${p.name}»?`)) return;
                        setBusy(true);
                        try {
                          await api.deleteProfile(p.id);
                          if (editingId === p.id) {
                            setEditingId(null);
                            setForm(emptyForm);
                          }
                          await load();
                        } catch (err) {
                          setError(
                            err instanceof Error ? err.message : String(err),
                          );
                        } finally {
                          setBusy(false);
                        }
                      })()
                    }
                  >
                    Удалить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
