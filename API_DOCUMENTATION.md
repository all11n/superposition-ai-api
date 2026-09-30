# Superposition AI API

FastAPI-сервис для подключения алгоритмов управления AI соперником в игре «Суперпозиция»

Сервис получает снимок текущего состояния игровой партии, выбирает одно допустимое действие для игрока, управляемого сервером, и возвращает это действие в формате, совместимом с backend игры

## Доступные модели

API предоставляет три уровня принятия решений:

| Модель | Метод                   | Назначение                                                   |
| ------ | ----------------------- | ------------------------------------------------------------ |
| `low`  | Эвристический поиск     | Быстрое решение на основе непосредственного эффекта действия |
| `mcts` | Monte Carlo Tree Search | Поиск по дереву возможных продолжений                        |
| `high` | MLP                     | Оценка допустимых действий нейросетевой моделью              |

Модель выбирается параметром `model` в запросе
Пример:

```json
{
  "model": "mcts"
}
```

Для `mcts` установлен временной лимит поиска до **4.5 секунд**


# Основной endpoint

```http
POST /choose-action
```
Endpoint получает текущее состояние партии и возвращает одно действие, которое AI предлагает выполнить следующим

После применения действия backend может повторно обратиться к этому endpoint с обновлённым состоянием

## Формат запроса

Основные поля:

```json
{
  "model": "mcts",

  "aiPlayerId": "player-ai",
  "opponentPlayerId": "player-human",

  "dice": {
    "player-ai": ["ZERO", "PLUS", "ONE", "I"],
    "player-human": ["MINUS", "ZERO", "I_MINUS", "PLUS"]
  },

  "targets": {
    "player-ai": ["ONE", "ZERO", "PLUS", "I"],
    "player-human": ["MINUS", "ONE", "I", "PLUS"]
  },

  "aiHand": [
    {
      "id": "card-uuid-1",
      "type": "PAULI_X"
    },
    {
      "id": "card-uuid-2",
      "type": "HADAMARD"
    }
  ],

  "opponentHand": [
    {
      "id": "card-uuid-3",
      "type": "PAULI_Z"
    }
  ],

  "deck": [],
  "discard": [],

  "protected": {
    "player-ai": [false, false, false, false],
    "player-human": [false, false, false, false]
  },

  "appliedCards": {
    "player-ai": [
      [],
      [],
      [],
      []
    ],
    "player-human": [
      [],
      [],
      [],
      []
    ]
  },

  "activeRow": null,
  "kroneckerRemainingActions": 0,

  "moveNumber": 12,
  "maxMoves": 80,
  "remainingMoves": 1,

  "currentPlayerId": "player-ai",
  "finished": false
}
```

### Обязательные поля

| Поле               | Тип      | Описание                                               |
| ------------------ | -------- | ------------------------------------------------------ |
| `model`            | `string` | `low`, `mcts` или `high`                               |
| `aiPlayerId`       | `string` | Идентификатор игрока, за которого принимает решение AI |
| `opponentPlayerId` | `string` | Идентификатор соперника                                |
| `dice`             | `object` | Текущие состояния кубиков по игрокам                   |
| `targets`          | `object` | Целевые состояния кубиков                              |
| `aiHand`           | `array`  | Карты, доступные AI                                    |
| `opponentHand`     | `array`  | Карты соперника                                        |

Остальные поля имеют значения по умолчанию, однако для корректного моделирования партии backend должен передавать их актуальные значения

---

# Состояние кубиков

Каждый кубик передаётся как строковое значение `DiceType`
Допустимые состояния:

```text
ZERO
ONE
PLUS
MINUS
I
I_MINUS
```

Пример:

```json
"dice": {
  "player-ai": [
    "ZERO",
    "PLUS",
    "ONE",
    "I"
  ]
}
```

Порядок элементов соответствует индексам игровых слотов {0, 1, 2, 3}
```

Целевые состояния передаются отдельно,что позволяет алгоритму оценивать положение каждого кубика относительно его целевого состояния:

```json
"targets": {
  "player-ai": [
    "ONE",
    "ZERO",
    "PLUS",
    "I"
  ]
}
```

# Игровые карты

Карта представляется двумя полями:

```json
{
  "id": "card-uuid",
  "type": "PAULI_X"
}
```

`id` — фактический идентификатор карты в партии
`type` — тип карты

Поддерживаемые типы:

```text
HADAMARD
HADAMARD_3
PAULI_X
PAULI_X_3
PAULI_Y
PAULI_Y_3
PAULI_Z
PAULI_Z_3
PHASE_FORWARD
PHASE_BACKWARD
ROTATE_X
ROTATE_Y
ROTATE_Z
IDENTITY
MEASUREMENT
KRONECKER_MULTIPLICATION
QUANTUM_NOISE
SWAP
RESHUFFLE
```


# Защищённые слоты

Поле `protected` содержит информацию о слотах, на которые обычные карты не могут воздействовать

Пример:

```json
"protected": {
  "player-ai": [false, true, false, false],
  "player-human": [false, false, false, true]
}
```

В данном состоянии:

* слот `1` игрока `player-ai` защищён
* слот `3` игрока `player-human` защищён


# История применённых карт

Поле `appliedCards` содержит историю карт, применённых к слотам

Формат:

```text
playerId
    └── 4 игровых слота
          └── список применённых карт
```

Пример:

```json
"appliedCards": {
  "player-ai": [
    [
      {
        "id": "card-1",
        "type": "PAULI_X"
      }
    ],
    [
      {
        "id": "card-2",
        "type": "HADAMARD"
      },
      {
        "id": "card-3",
        "type": "PHASE_FORWARD"
      }
    ],
    [],
    []
  ]
}
```

Последняя карта в списке считается верхней картой истории соответствующего слота
Для карт `_3` история применения хранится только в центральном слоте действия

# Специальное состояние KRONECKER_MULTIPLICATION

`KRONECKER_MULTIPLICATION` может предоставить дополнительные действия, и чтобы состояние этого эффекта сохранялось между отдельными HTTP-запросами, API использует два поля:

```json
"activeRow": "player-ai",
"kroneckerRemainingActions": 1
```

### `activeRow`

Определяет строку, в которой должны выполняться последующие действия после начала соответствующей последовательности
В обычном состоянии:

```json
"activeRow": null
```

### `kroneckerRemainingActions`

Количество дополнительных действий, которые ещё необходимо выполнить
В обычном состоянии:

```json
"kroneckerRemainingActions": 0
```

Backend должен обновлять эти значения после применения действия и передавать их в следующий запрос


# RESHUFFLE и колода

Для выбора карты `RESHUFFLE` AI определяет, какие карты текущей руки следует заменить
В ответ передаётся список идентификаторов карт:

```json
{
  "cardsToChange": [
    "card-uuid-1",
    "card-uuid-7"
  ]
}
```

Если `deck` передаётся полностью, то симуляция может учитывать доступные карты колоды:

```json
"deck": [
  {
    "id": "deck-card-1",
    "type": "PAULI_X"
  },
  {
    "id": "deck-card-2",
    "type": "HADAMARD"
  }
]
```

Если колода не передана, действие `RESHUFFLE` всё равно может быть сформировано, однако точное моделирование получаемых после замены карт ограничено


# Ответ

Успешный запрос возвращает:

```json
{
  "model": "mcts",
  "action": {
    "type": "PLAY_CARD",
    "playerId": "player-ai",
    "cardId": "card-uuid-1",
    "targetSlotIndex": 2,
    "targetPlayerId": "player-ai"
  },
  "thinkingTimeMs": 4312.57,
  "iterations": 3562
}
```

Главное поле ответа:

```text
action
```

Оно содержит конкретное действие, которое должен применить backend
`thinkingTimeMs`, `iterations` и другие дополнительные поля предназначены для диагностики и мониторинга работы алгоритма


# Типы возвращаемых действий

API поддерживает следующие типы:

```text
PLAY_CARD
ROTATE_DICE
SWAP_DICES
DOUBLE_TAP
RESHUFFLE_CARD
SURRENDER
```

## PLAY_CARD

Применение карты к одному слоту:

```json
{
  "type": "PLAY_CARD",
  "playerId": "player-ai",
  "cardId": "card-uuid-1",
  "targetSlotIndex": 2,
  "targetPlayerId": "player-ai"
}
```

## ROTATE_DICE

Изменение состояния конкретного кубика:

```json
{
  "type": "ROTATE_DICE",
  "playerId": "player-ai",
  "cardId": "card-uuid-2",
  "targetSlotIndex": 1,
  "newState": "PLUS",
  "targetPlayerId": "player-ai"
}
```

## SWAP_DICES

Обмен состояниями двух кубиков:

```json
{
  "type": "SWAP_DICES",
  "playerId": "player-ai",
  "cardId": "card-uuid-3",
  "firstSlotIndex": 0,
  "secondSlotIndex": 2,
  "firstSlotOwner": "player-ai",
  "secondSlotOwner": "player-human"
}
```

## DOUBLE_TAP

Специальное действие без выбора отдельного игрового слота:

```json
{
  "type": "DOUBLE_TAP",
  "playerId": "player-ai",
  "cardId": "card-uuid-4"
}
```

## RESHUFFLE_CARD

Замена выбранных карт руки:

```json
{
  "type": "RESHUFFLE_CARD",
  "playerId": "player-ai",
  "cardId": "reshuffle-card-uuid",
  "cardsToChange": [
    "card-uuid-1",
    "card-uuid-5"
  ]
}
```

## SURRENDER

Завершение партии сдачей:

```json
{
  "type": "SURRENDER",
  "playerId": "player-ai"
}
```

# Игровой цикл

Один запрос соответствует одному решению AI
Типичный цикл выглядит следующим образом:

```text
1. Backend формирует состояние партии
             │
             ▼
2. POST /choose-action
             │
             ▼
3. AI выбирает одно действие
             │
             ▼
4. Backend получает action
             │
             ▼
5. Backend проверяет и применяет действие
             │
             ▼
6. Backend обновляет состояние партии
             │
             ▼
7. Если AI должен выполнить ещё действие:
             │
             └──────► POST /choose-action
```

# GET /health

Проверка доступности сервиса:

```http
GET /health
```

Пример ответа:

```json
{
  "status": "ok",
  "models": [
    "low",
    "mcts",
    "high"
  ],
  "neural_model": "loaded"
}
```

Поле `neural_model` показывает, загружены ли веса модели для уровня `high`

---

# GET /models

Возвращает конфигурацию доступных моделей:

```http
GET /models
```

Пример:

```json
{
  "models": [
    "low",
    "mcts",
    "high"
  ],
  "mctsTimeLimitSec": 4.5,
  "neuralLoaded": true
}
```

# Документация OpenAPI

После запуска сервиса FastAPI автоматически предоставляет интерактивную документацию:

```text
http://localhost:8000/docs
```

Через неё можно отправлять запросы к `/choose-action` непосредственно из браузера

# Запуск локально

Создание виртуального окружения:

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Установка зависимостей:

```bash
pip install -r requirements.txt
```

Запуск сервера:

```bash
uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
```

После запуска:

```text
http://localhost:8000/health
http://localhost:8000/models
http://localhost:8000/docs
```

# Структура проекта

```text
.
├── api_server.py
├── model_engine.py
├── requirements.txt
├── Dockerfile
├── API_DOCUMENTATION.md
└── neural_model_demo.npz
```

### `api_server.py`

HTTP-слой приложения:

* описывает Pydantic-модель входного запроса;
* принимает состояние игры;
* передаёт его в `model_engine`;
* возвращает выбранное действие;
* предоставляет endpoints `/health` и `/models`

### `model_engine.py`

Основная логика принятия решений:

* представление игрового состояния;
* генерация допустимых действий;
* моделирование действий;
* эвристический алгоритм;
* MCTS;
* нейросетевой уровень;
* преобразование действий в DTO

# Ограничения

Текущая реализация ориентирована на конфигурацию игры с **8 кубиками: 4 кубика AI и 4 кубика соперника**.

Точность моделирования зависит от полноты состояния, переданного в запросе

В частности:
* без `appliedCards` невозможно полноценно учитывать историю применения карт;
* без `activeRow` и `kroneckerRemainingActions` невозможно восстановить незавершённую последовательность `KRONECKER_MULTIPLICATION`;
* без данных `deck` точное моделирование результата `RESHUFFLE` ограничено;
* backend должен передавать актуальные значения этих полей после каждого применённого действия.

Игровые правила в конечном счёте определяются реализацией `CardEffect` на стороне Spring Boot, поэтому при изменении правил игры логика моделирования в `model_engine.py` должна быть синхронизирована с backend


# Контракт интеграции

Для интеграции необходимо соблюдать следующие условия:

1. `aiPlayerId` должен соответствовать игроку, за которого AI принимает решение.
2. `currentPlayerId`, если передан, должен совпадать с `aiPlayerId`.
3. `cardId` в ответе должен соответствовать реальной карте из руки AI.
4. `targetPlayerId` и `targetSlotIndex` должны интерпретироваться относительно текущего состояния партии.
5. После применения действия backend должен сформировать новый снимок состояния.
6. AI не хранит состояние предыдущего запроса.
7. Backend самостоятельно проверяет и применяет полученное действие.


# Пример полного обмена

### Запрос

```http
POST /choose-action
Content-Type: application/json
```

```json
{
  "model": "mcts",
  "aiPlayerId": "ai",
  "opponentPlayerId": "human",

  "dice": {
    "ai": [
      "ZERO",
      "PLUS",
      "ONE",
      "I"
    ],
    "human": [
      "MINUS",
      "ZERO",
      "I_MINUS",
      "PLUS"
    ]
  },

  "targets": {
    "ai": [
      "ONE",
      "ZERO",
      "PLUS",
      "I"
    ],
    "human": [
      "MINUS",
      "ONE",
      "I",
      "PLUS"
    ]
  },

  "aiHand": [
    {
      "id": "a1",
      "type": "PAULI_X"
    },
    {
      "id": "a2",
      "type": "HADAMARD"
    }
  ],

  "opponentHand": [
    {
      "id": "h1",
      "type": "PAULI_Z"
    }
  ],

  "protected": {
    "ai": [false, false, false, false],
    "human": [false, false, false, false]
  },

  "appliedCards": {
    "ai": [[], [], [], []],
    "human": [[], [], [], []]
  },

  "activeRow": null,
  "kroneckerRemainingActions": 0,

  "moveNumber": 12,
  "maxMoves": 80,
  "remainingMoves": 1,
  "currentPlayerId": "ai",
  "finished": false
}
```

### Ответ

```json
{
  "model": "mcts",
  "action": {
    "type": "PLAY_CARD",
    "playerId": "ai",
    "cardId": "a1",
    "targetSlotIndex": 0,
    "targetPlayerId": "ai"
  },
  "thinkingTimeMs": 4387.21,
  "iterations": 3614
}
```

Backend применяет `PLAY_CARD`, обновляет состояние партии и при необходимости отправляет следующий запрос


# Проверка сервиса

После запуска можно проверить состояние:

```bash
curl http://localhost:8000/health
```

Проверка доступных моделей:

```bash
curl http://localhost:8000/models
```

Для ручного тестирования `/choose-action` удобнее использовать:

```text
http://localhost:8000/docs
```
