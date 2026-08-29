# Superposition AI API

FastAPI-сервис для интеграции трёх уровней ИИ игры «Суперпозиция».

## Что делает сервер

Мобильное приложение отправляет текущее состояние игры и карты ИИ. Сервер выбирает полный ход из двух карт и возвращает его в JSON.

Доступные модели:

- `low` — эвристический алгоритм;
- `mcts` — MCTS, до 4.5 секунд;
- `high` — нейросетевой MLP.

Подробный контракт: `API_DOCUMENTATION.md`.

## Основной запрос

```text
POST /choose-action
```

Минимальный рекомендуемый JSON:

```json
{
  "model": "mcts",
  "board": [4, 2, 5, 0, 0, 3, 0, 4],
  "targets": [
    [3, 0, 4, 5],
    [5, 3, 0, 2]
  ],
  "hands": {
    "ai": ["Y", "Z3", "RX", "IDENTITY"],
    "opponent": ["X", "S_DAG", "BARRIER", "RESHUFFLE"]
  }
}
```

Ответ содержит:

```json
{
  "model": "mcts",
  "action": {
    "first": {"card_id": "Z3", "targets": [0, 1, 2]},
    "second": {"card_id": "Y", "targets": [6]}
  },
  "thinking_time_ms": 4502.1,
  "favorability": 1,
  "iterations": 3796
}
```

Для игры главное поле — `action`. Остальные поля диагностические.

## Почему нужен `targets`

Если передавать только карты и `board`, модель не знает целевое состояние регистра. Тогда она не может корректно определить, какие кубиты уже правильные и какие действия приближают ИИ к цели, поэтому в текущем API `targets` обязателен

## GET

```text
GET /health
GET /models
```

`/health` проверяет сервер, `/models` показывает доступные уровни.

## Запуск локально

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Установка:

```bash
pip install -r requirements.txt
```

Запуск:

```bash
uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
```

После запуска:

```text
http://localhost:8000/health
http://localhost:8000/models
http://localhost:8000/docs
```

`/docs` — автоматически созданная FastAPI Swagger-документация, через которую можно тестировать POST без мобильного приложения.

## Развёртывание

Для разработки сервис можно запускать на своём компьютере. Для подключения мобильного приложения нужен доступный ему сервер/VPS/PaaS с публичным HTTPS-адресом.

Команда production-запуска:

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

## Структура

- `api_server.py` — HTTP API;
- `model_engine.py` — игровой движок и три модели;
- `neural_model_demo.npz` — сохранённые веса демонстрационной MLP;
- `API_DOCUMENTATION.md` — подробный контракт интеграции;
- `requirements.txt` — зависимости;
- `Dockerfile` — контейнеризация.

## Ограничения прототипа

Сейчас используется мобильная конфигурация 8 кубитов: 4 ИИ + 4 соперника.

`GATE_TRANSITIONS` и `CARD_DB` в текущем прототипе должны быть синхронизированы с реальными правилами мобильной игры перед production.
