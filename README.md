# Paper2Data

Локальное веб-приложение для человеко-управляемого извлечения графа сущностей из научных статей (FastAPI + React).

## Требования

- Python 3.11+
- Node.js 18+ (для сборки frontend)
- Windows / Linux / macOS

## Быстрый старт (Windows)

```bat
start.bat
```

Скрипт создаст `backend/.venv`, установит зависимости, при наличии npm соберёт frontend и запустит сервер на [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Запуск вручную

```bash
# Backend
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt

# Frontend (dev)
cd ../frontend
npm install
npm run dev
```

В отдельном терминале из корня репозитория:

```bash
python run.py --no-browser
```

- API: `http://127.0.0.1:8765/api/health`
- UI (Vite): `http://127.0.0.1:5173` (проксирует `/api` на backend)

Продакшен-режим (одна точка входа):

```bash
cd frontend && npm run build
cd .. && python run.py
```

## Структура проекта-папки

При создании/открытии проекта в выбранной папке появляются:

| Путь | Назначение |
|------|------------|
| `project.yaml` | Настройки и LLM-профили |
| `paper2data.sqlite` | База проекта |
| `papers/` | PDF статей и ESI |
| `cache/` | Кэш разбора и ответов LLM |
| `exports/` | Экспорт |

API-ключи LLM хранятся **вне проекта**: `~/.paper2data/secrets`.

## Что есть в M0

- Создание и открытие проекта (системный диалог папки)
- SQLite + SQLAlchemy + Alembic
- LLM-профили (OpenAI-compatible API через `httpx`) с проверкой подключения
- Страницы: **Проекты**, **Настройки**, заглушка **Статьи**

> Клиент LLM в M0 вызывает `POST {base_url}/chat/completions` напрямую. Пакет `openai` можно добавить позже для structured output / streaming.

## Рисунки (M5)

- Извлечение при ingest: встроенные изображения PDF + рендер области над подписью (`Fig.` / `Scheme` / `Table`).
- **DocLayout / YOLO не используются** (тяжёлые зависимости, слабая практичность на Windows) — достаточно caption/embedded regions.
- Галерея: `/figures` (фильтр по статье через `?document_id=`), ручная разметка, создание классов.
- Классификатор: эмбеддинги + kNN/прототипы, порог уверенности → корзина «Не уверен».
- Заготовка `FigureDataExtractor` для будущего OCSR / дигитайзера графиков.

### CLIP (опционально)

По умолчанию используется **stub**-эмбеддинг (детерминированный вектор из байтов файла) — UI и API полностью работают без ML.

Для реального CLIP на Windows попробуйте один из вариантов (могут требовать Visual C++ / CUDA):

```bash
pip install open-clip-torch pillow
# или
pip install sentence-transformers
```

Бэкенд выбирается автоматически: `open_clip` → `sentence-transformers` → `stub`. Статус: `GET /api/figures/status`.

## Шаблоны схем

В `templates/` лежат YAML-шаблоны схем и пример рецепта (см. также `docs/ARCHITECTURE.md`). Редактор схемы в UI — этап M2.

## Разработка

```
backend/paper2data/{api,core,db,ingest,schema,graph,llm,extraction,evaluation,chem,figures,assistant}
backend/tests/
frontend/src/{pages,components,api,store}
run.py, start.bat
```
