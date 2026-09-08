# API игры «Суперпозиция»

## Назначение
API принимает актуальный снапшот состояния игры (`GameState`) и возвращает **одно следующее оптимальное действие** ИИ

Сервис не хранит состояние между запросами. Вся игровая логика, валидация ходов и применение эффектов карт остаются ответственностью основного Spring Boot сервера

Доступны три уровня принятия решений:
- `low` — быстрая эвристическая оценка.
- `mcts` — поиск методом Монте-Карло (MCTS) с лимитом времени до 4.5 секунд.
- `high` — оценка действий с помощью нейросетевой MLP-модели.

---

## 1. Основной endpoint

### `POST /choose-action`
Используется Spring Boot сервером для получения следующего хода ИИ

### Входной JSON
```json
{
  "model": "mcts",
  "aiPlayerId": "ai-uuid-1234-5678",
  "opponentPlayerId": "opp-uuid-8765-4321",
  "dice": {
    "ai-uuid-1234-5678": ["ZERO", "PLUS", "MINUS", "I"],
    "opp-uuid-8765-4321": ["ONE", "ZERO", "I_MINUS", "PLUS"]
  },
  "targets": {
    "ai-uuid-1234-5678": ["PLUS", "PLUS", "MINUS", "I"],
    "opp-uuid-8765-4321": ["ZERO", "ONE", "I_MINUS", "PLUS"]
  },
  "aiHand": [
    { "id": "card-uuid-pauli-x-1", "type": "PAULI_X" },
    { "id": "card-uuid-swap-1", "type": "SWAP" }
  ],
  "opponentHand": [
    { "id": "card-uuid-hadamard-1", "type": "HADAMARD" }
  ],
  "deck": [],
  "discard": [],
  "protected": {
    "ai-uuid-1234-5678": [false, false, false, false],
    "opp-uuid-8765-4321": [false, false, false, false]
  },
  "moveNumber": 5,
  "maxMoves": 80,
  "remainingMoves": 1,
  "currentPlayerId": "ai-uuid-1234-5678",
  "finished": false
}
```

### Описание обязательных полей:
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `model` | `string` | Уровень AI: `"low"`, `"mcts"` или `"high"`. |
| `aiPlayerId` | `string` | Уникальный идентификатор (UUID) игрока-ИИ. |
| `opponentPlayerId`| `string` | Уникальный идентификатор (UUID) игрока-оппонента. |
| `dice` | `object` | Словарь. Ключ: `playerId`, Значение: массив из **ровно 4** строк текущих состояний кубиков. |
| `targets` | `object` | Словарь. Ключ: `playerId`, Значение: массив из **ровно 4** строк целевых состояний кубиков. |
| `aiHand` | `array` | Массив объектов карт в руке ИИ. Каждый объект: `{"id": "uuid", "type": "CARD_TYPE"}`. |

*(Поля `opponentHand`, `deck`, `discard`, `protected`, `moveNumber`, `maxMoves`, `remainingMoves`, `currentPlayerId`, `finished` являются опциональными, но крайне рекомендуются для корректной работы MCTS).*

---

## 2. Справочник состояний и типов

Чтобы избежать рассинхронизации, AI использует **строго те же строковые значения**, что и Java на сервере

### `DiceType`
Используются в полях `dice` и `targets`, а также в ответе `newState`:
- `"ZERO"`, `"ONE"`, `"PLUS"`, `"MINUS"`, `"I"`, `"I_MINUS"`

### `CardType`
Используются в поле `type` объектов карт. Карта `BARRIER` исключена.
- `"PAULI_X"`, `"PAULI_Y"`, `"PAULI_Z"`
- `"PAULI_X_3"`, `"PAULI_Y_3"`, `"PAULI_Z_3"`
- `"HADAMARD"`, `"HADAMARD_3"`
- `"ROTATE_X"`, `"ROTATE_Y"`, `"ROTATE_Z"`
- `"PHASE_FORWARD"`, `"PHASE_BACKWARD"`
- `"IDENTITY"`, `"MEASUREMENT"`, `"KRONECKER_MULTIPLICATION"`
- `"QUANTUM_NOISE"`, `"SWAP"`, `"RESHUFFLE"`

---

## 3. Ответ API

AI возвращает **одно действие** 

### Пример ответа (Вариант 1: Вращение кубика)
```json
{
  "model": "mcts",
  "action": {
    "type": "ROTATE_DICE",
    "playerId": "ai-uuid-1234-5678",
    "cardId": "card-uuid-pauli-x-1",
    "targetSlotIndex": 0,
    "newState": "PLUS",
    "targetPlayerId": "ai-uuid-1234-5678"
  },
  "thinkingTimeMs": 142.5,
  "iterations": 11240,
  "rootChildren": 18
}
```

### Пример ответа
```json
{
  "model": "mcts",
  "action": {
    "type": "SWAP_DICES",
    "playerId": "ai-uuid-1234-5678",
    "cardId": "card-uuid-swap-1",
    "firstSlotIndex": 0,
    "secondSlotIndex": 1,
    "firstSlotOwner": "ai-uuid-1234-5678",
    "secondSlotOwner": "opp-uuid-8765-4321"
  },
  "thinkingTimeMs": 85.2,
  "iterations": 8500,
  "rootChildren": 12
}
```

### Структура поля `action` по типам:
1. **`PLAY_CARD`**: `type`, `playerId`, `cardId`, `targetSlotIndex`, `targetPlayerId`
2. **`ROTATE_DICE`**: `type`, `playerId`, `cardId`, `targetSlotIndex`, `newState`, `targetPlayerId` *(новое состояние указано явно)*
3. **`SWAP_DICES`**: `type`, `playerId`, `cardId`, `firstSlotIndex`, `secondSlotIndex`, `firstSlotOwner`, `secondSlotOwner`
4. **`RESHUFFLE_CARD`**: `type`, `playerId`, `cardId`, `cardsToChange` (массив UUID)
5. **`DOUBLE_TAP`**: `type`, `playerId`, `cardId`
6. **`SURRENDER`**: `type`, `playerId`

---

## 4. Логика взаимодействия

В отличие от предыдущих версий, AI не возвращает два действия сразу. Цикл выглядит так:

```text
SPRING BOOT
  ├─ 1. Применяет ход игрока.
  ├─ 2. Проверяет remainingMoves. Если > 0 и ход ИИ:
  ▼
  │ 3. Формирует снапшот GameState и отправляет POST /choose-action
FASTAPI
  ├─ 4. Оценивает состояние (Low / MCTS / High)
  ├─ 5. Возвращает JSON с ОДНИМ действием (MoveDto)
  ▼
SPRING BOOT
  ├─ 6. Десериализует ответ в соответствующий DTO (например, RotateDiceDto)
  ├─ 7. Находит карту по UUID (cardId) и удаляет её из руки
  ├─ 8. Вызывает CardEffectsRepository.apply(...) для изменения GameState
  ├─ 9. Уменьшает remainingMoves на 1
  └─ 10. Если remainingMoves > 0 и игра не закончена - возврат к шагу 3
       Если remainingMoves == 0 - передача хода следующему игроку
```

---

## 5. GET Endpoints

### `GET /health`
Проверка доступности сервиса и статуса загрузки моделей
```json
{
  "status": "ok",
  "models": ["low", "mcts", "high"],
  "neural_model": "loaded"
}
```

### `GET /models`
Возвращает конфигурацию доступных уровней ИИ
```json
{
  "models": ["low", "mcts", "high"],
  "mctsTimeLimitSec": 4.5,
  "neuralLoaded": true
}
```

---

## 6. Минимальный рекомендуемый контракт для тестирования

Для базовой проверки работы API достаточно отправить следующий минимальный JSON (все UUID и типы замените на реальные из вашей БД):

```json
{
  "model": "mcts",
  "aiPlayerId": "ai-123",
  "opponentPlayerId": "opp-456",
  "dice": {
    "ai-123": ["ZERO", "ONE", "PLUS", "MINUS"],
    "opp-456": ["MINUS", "I", "I_MINUS", "ZERO"]
  },
  "targets": {
    "ai-123": ["PLUS", "ONE", "PLUS", "MINUS"],
    "opp-456": ["I", "I", "I_MINUS", "ZERO"]
  },
  "aiHand": [
    { "id": "card-uuid-1", "type": "PAULI_X" }
  ],
  "opponentHand": [],
  "deck": [],
  "discard": [],
  "protected": {},
  "moveNumber": 1,
  "maxMoves": 80,
  "remainingMoves": 1,
  "currentPlayerId": "ai-123",
  "finished": false
}
```