# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Sequence, Any
from collections import defaultdict
import copy
import itertools
import json
import math
import random
import time


# КОНСТАНТЫ

N_PLAYERS = 2
N_OWN_QUBITS = 4
N_TOTAL_QUBITS = 8
N_STATES = 6

AI = 0
OPPONENT = 1


def global_slot(player: int, local_index: int) -> int:
    """Переводит индекс кубита внутри поля в общий индекс 0..7"""
    if not 0 <= local_index < N_OWN_QUBITS:
        raise ValueError("local_index должен быть от 0 до 3")
    return local_index if player == AI else 4 + local_index


def owner_of_slot(slot: int) -> int:
    if not 0 <= slot < N_TOTAL_QUBITS:
        raise ValueError("slot должен быть от 0 до 7")
    return AI if slot < 4 else OPPONENT


def local_index(slot: int) -> int:
    return slot if slot < 4 else slot - 4

# ОПИСАНИЕ КАРТ

@dataclass(frozen=True)
class Card:
    card_id: str
    name: str
    kind: str
    copies: int
    target_count: int = 0
    placement: str = "field"       # field / discard
    angle: Optional[int] = None


@dataclass(frozen=True)
class Action:
    """ ход - две разыгрываемые карты"""
    first: "CardPlay"
    second: "CardPlay"


@dataclass(frozen=True)
class CardPlay:
    card_id: str
    targets: Tuple[int, ...] = ()


@dataclass
class HistoryItem:
    board_value_before: int
    protected_before: bool
    last_effect_before: Optional[str]


@dataclass
class GameState:
    board: List[int]
    targets: List[List[int]]             # [AI][4], [OPPONENT][4]
    hands: List[List[str]]               # [AI hand, opponent hand]
    deck: List[str]
    discard: List[str]

    turn: int = AI
    skip_turns: List[int] = field(default_factory=lambda: [0, 0])
    protected: List[List[bool]] = field(
        default_factory=lambda: [[False] * 4, [False] * 4]
    )

    last_effect: List[Optional[str]] = field(
        default_factory=lambda: [None] * N_TOTAL_QUBITS
    )

    # История нужна для Quantum noise
    history: List[List[HistoryItem]] = field(
        default_factory=lambda: [[] for _ in range(N_TOTAL_QUBITS)]
    )

    move_number: int = 0
    max_moves: int = 80
    finished: bool = False
    winner: Optional[int] = None

    def clone(self) -> "GameState": # быстрая копия состояния вместо глубокой
        return GameState(
            board=self.board.copy(),
            targets=[row.copy() for row in self.targets],
            hands=[hand.copy() for hand in self.hands],
            deck=self.deck.copy(),
            discard=self.discard.copy(),
            turn=self.turn,
            skip_turns=self.skip_turns.copy(),
            protected=[row.copy() for row in self.protected],
            last_effect=self.last_effect.copy(),
            history=[
                [
                    HistoryItem(h.board_value_before, h.protected_before, h.last_effect_before)
                    for h in slot_history
                ]
                for slot_history in self.history
            ],
            move_number=self.move_number,
            max_moves=self.max_moves,
            finished=self.finished,
            winner=self.winner,
        )


# Тестовые данные колоды

CARD_DB: Dict[str, Card] = {
    "X": Card("X", "Pauli X", "PAULI", 8, 1, "field", 180),
    "Y": Card("Y", "Pauli Y", "PAULI", 8, 1, "field", 180),
    "Z": Card("Z", "Pauli Z", "PAULI", 8, 1, "field", 180),

    "X3": Card("X3", "Pauli X 3", "PAULI3", 4, 3),
    "Y3": Card("Y3", "Pauli Y 3", "PAULI3", 4, 3),
    "Z3": Card("Z3", "Pauli Z 3", "PAULI3", 4, 3),

    "S": Card("S", "Phase S", "PHASE", 8, 1, "field", 90),
    "S_DAG": Card("S_DAG", "Phase S†", "PHASE", 8, 1, "field", -90),

    "RX": Card("RX", "Rotate-X", "ROTATE", 4, 1),
    "RY": Card("RY", "Rotate-Y", "ROTATE", 4, 1),
    "RZ": Card("RZ", "Rotate-Z", "ROTATE", 4, 1),

    "H": Card("H", "Hadamard", "HADAMARD", 6, 1),
    "H3": Card("H3", "Hadamard 3", "HADAMARD3", 6, 3),

    "SWAP": Card("SWAP", "Swap", "SWAP", 6, 2, "discard"),
    "QUANTUM_NOISE": Card("QUANTUM_NOISE", "Quantum noise", "NOISE", 8, 1),
    "MEASUREMENT": Card("MEASUREMENT", "Measurement", "MEASUREMENT", 8, 1),

    "IDENTITY": Card("IDENTITY", "Identity", "IDENTITY", 8, 0),
    "BARRIER": Card("BARRIER", "Barrier", "BARRIER", 6, 0, "discard"),
    "RESHUFFLE": Card("RESHUFFLE", "Reshuffle", "RESHUFFLE", 6, 0, "discard"),

    "QUANTUM_LUCKY": Card("QUANTUM_LUCKY", "Quantum lucky", "LUCKY", 4, 1),
    "KRONECKER": Card("KRONECKER", "Kronecker multiplication", "KRONECKER", 6, 2, "discard"),
}


TEST_DECK = (
    ["X"] * 8 + ["Y"] * 8 + ["Z"] * 8
    + ["X3"] * 4 + ["Y3"] * 4 + ["Z3"] * 4
    + ["S"] * 8 + ["S_DAG"] * 8
    + ["RX"] * 4 + ["RY"] * 4 + ["RZ"] * 4
    + ["H"] * 6 + ["H3"] * 6
    + ["SWAP"] * 6 + ["QUANTUM_NOISE"] * 8
    + ["MEASUREMENT"] * 8 + ["IDENTITY"] * 8
    + ["BARRIER"] * 6 + ["RESHUFFLE"] * 6
    + ["QUANTUM_LUCKY"] * 4 + ["KRONECKER"] * 6
)


def validate_deck(deck: Sequence[str]) -> None:
    for card_id in deck:
        if card_id not in CARD_DB:
            raise ValueError(f"Неизвестная карта: {card_id}")


# ТЕСТОВАЯ МОДЕЛЬ ПЕРЕХОДОВ

# Формат:
# GATE_TRANSITIONS["X"][старое_состояние] = новое_состояние

def cyclic_transition(step: int) -> Dict[int, int]:
    return {s: (s + step) % N_STATES for s in range(N_STATES)}


GATE_TRANSITIONS: Dict[str, Dict[int, int]] = {
    "X": cyclic_transition(3),
    "Y": cyclic_transition(3),
    "Z": cyclic_transition(3),

    "S": cyclic_transition(1),
    "S_DAG": cyclic_transition(-1),

    # Временные переходы
    "RX": cyclic_transition(1),
    "RY": cyclic_transition(1),
    "RZ": cyclic_transition(1),

    "H": cyclic_transition(1),
}


def transition(state_value: int, gate: str) -> int:
    """Применение таблицы перехода"""
    if gate not in GATE_TRANSITIONS:
        raise ValueError(f"Нет таблицы переходов для {gate}")
    return GATE_TRANSITIONS[gate][state_value]


# ВАЛИДАЦИЯ

def validate_state(state: GameState) -> None:
    if len(state.board) != 8:
        raise ValueError("На доске должно быть ровно 8 кубитов") #в зависимости от числа кубитов

    if any(x < 0 or x >= 6 for x in state.board):
        raise ValueError("Состояние кубита должно быть 0..5")

    if len(state.targets) != 2 or any(len(x) != 4 for x in state.targets):
        raise ValueError("targets должен иметь форму [2][4]")

    for hand in state.hands:
        validate_deck(hand)

    validate_deck(state.deck)
    validate_deck(state.discard)


def correct_count(state: GameState, player: int) -> int:
    return sum(
        state.board[global_slot(player, i)] == state.targets[player][i]
        for i in range(4)
    )


def distance_to_target(state: GameState, player: int) -> int:
    return 4 - correct_count(state, player)


def is_win(state: GameState, player: int) -> bool:
    return correct_count(state, player) == 4


def terminal(state: GameState) -> bool:
    return (
        state.finished
        or is_win(state, AI)
        or is_win(state, OPPONENT)
        or state.move_number >= state.max_moves
        or (not state.deck and not state.hands[AI] and not state.hands[OPPONENT])
    )


def draw_to_hand(state: GameState, player: int, hand_size: int = 6) -> None:
    while len(state.hands[player]) < hand_size:
        if not state.deck:
            if state.discard:
                state.deck = state.discard[:]
                state.discard.clear()
                random.shuffle(state.deck)
            else:
                break

        state.hands[player].append(state.deck.pop())


def push_history(state: GameState, slot: int) -> None:
    side = owner_of_slot(slot)
    local = local_index(slot)
    state.history[slot].append(
        HistoryItem(
            board_value_before=state.board[slot],
            protected_before=state.protected[side][local],
            last_effect_before=state.last_effect[slot],
        )
    )


def undo_last_gate(state: GameState, slot: int) -> bool:
    """Quantum noise отменяет последнее действие над выбранным кубитом"""
    if not state.history[slot]:
        return False

    item = state.history[slot].pop()
    side = owner_of_slot(slot)
    local = local_index(slot)

    state.board[slot] = item.board_value_before
    state.protected[side][local] = item.protected_before
    state.last_effect[slot] = item.last_effect_before
    return True


# ГЕНЕРАЦИЯ ДЕЙСТВИЙ

def target_slots_for_card(card: Card, player: int) -> List[Tuple[int, ...]]:
    base = 0 if player == AI else 4

    if card.target_count == 0:
        return [()]

    if card.kind == "SWAP":
        return list(itertools.combinations(range(8), 2))

    if card.kind in ("PAULI3", "HADAMARD3"):
        return [
            (base + i, base + i + 1, base + i + 2)
            for i in range(2)
        ]

    #обычная карта может быть сыграна на любом из 8 кубитов
    return [(base + i,) for i in range(4)] + [
        (4 + i,) for i in range(4)
    ]


def card_play_candidates(state: GameState, card_id: str, player: int) -> List[CardPlay]:
    card = CARD_DB[card_id]
    return [
        CardPlay(card_id, targets)
        for targets in target_slots_for_card(card, player)
    ]


def _fast_apply_to_board(
    board: List[int],
    protected: List[List[bool]],
    targets: List[List[int]],
    play: CardPlay,
) -> None:
    card = CARD_DB[play.card_id]

    if card.kind == "SWAP":
        x, y = play.targets
        board[x], board[y] = board[y], board[x]
        return

    if card.kind == "LUCKY":
        slot = play.targets[0]
        side = owner_of_slot(slot)
        local = local_index(slot)
        board[slot] = targets[side][local]
        return

    if card.kind in {"PAULI", "PAULI3", "PHASE", "ROTATE", "HADAMARD", "HADAMARD3"}:
        if card.kind == "PAULI3":
            gate = play.card_id.replace("3", "")
        elif card.kind == "HADAMARD3":
            gate = "H"
        else:
            gate = play.card_id

        for slot in play.targets:
            side = owner_of_slot(slot)
            local = local_index(slot)
            if protected[side][local]:
                continue
            board[slot] = transition(board[slot], gate)


def fast_action_value(state: GameState, action: Action, player: int) -> float:
    board = state.board.copy()
    protected = [row.copy() for row in state.protected]

    before_me = correct_count(state, player)
    before_opp = correct_count(state, 1 - player)

    try:
        _fast_apply_to_board(board, protected, state.targets, action.first)
        _fast_apply_to_board(board, protected, state.targets, action.second)
    except (ValueError, IndexError, KeyError):
        return -1e9

    after_me = sum(
        board[global_slot(player, i)] == state.targets[player][i]
        for i in range(4)
    )
    after_opp = sum(
        board[global_slot(1 - player, i)] == state.targets[1 - player][i]
        for i in range(4)
    )
    return 4.0 * (after_me - before_me) - 2.0 * (after_opp - before_opp)


def generate_actions(state: GameState, player: int, max_actions: int = 250) -> List[Action]:
    hand = list(state.hands[player])

    if len(hand) < 2:
        return []

    actions: List[Action] = []

    for i, j in itertools.combinations(range(len(hand)), 2):
        c1, c2 = hand[i], hand[j]

        p1s = card_play_candidates(state, c1, player)
        p2s = card_play_candidates(state, c2, player)

        for p1 in p1s:
            for p2 in p2s:
                actions.append(Action(p1, p2))

    #оставляем наиболее лучшие действия
    if len(actions) > max_actions:
        scored = [
            (fast_action_value(state, a, player), a)
            for a in actions
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        actions = [a for _, a in scored[:max_actions]]

    return actions

# ПРИМЕНЕНИЕ АКРТ
def apply_card_play(state: GameState, play: CardPlay, player: int) -> None:
    if play.card_id not in state.hands[player]:
        raise ValueError(f"Карта {play.card_id} отсутствует на руке игрока")

    card = CARD_DB[play.card_id]
    state.hands[player].remove(play.card_id)

    # ---------- Barrier ----------
    if card.kind == "BARRIER":
        state.skip_turns[1 - player] += 1
        state.discard.append(play.card_id)
        return

    # ---------- Identity ----------
    if card.kind == "IDENTITY":
        state.skip_turns[player] += 1
        state.discard.append(play.card_id)
        return

    # ---------- Reshuffle ----------
    if card.kind == "RESHUFFLE":
        amount = min(4, len(state.deck))
        for _ in range(amount):
            if state.deck:
                state.discard.append(state.deck.pop(random.randrange(len(state.deck))))
        state.discard.append(play.card_id)
        return

    # ---------- Swap ----------
    if card.kind == "SWAP":
        if len(play.targets) != 2:
            raise ValueError("SWAP требует два кубита")
        a, b = play.targets
        if a == b:
            raise ValueError("SWAP не может менять кубит сам с собой")

        state.board[a], state.board[b] = state.board[b], state.board[a]
        state.last_effect[a] = "SWAP"
        state.last_effect[b] = "SWAP"
        state.history[a].clear()
        state.history[b].clear()
        state.discard.append(play.card_id)
        return

    # ---------- Quantum noise ----------
    if card.kind == "NOISE":
        if len(play.targets) != 1:
            raise ValueError("Quantum noise требует один кубит")
        undo_last_gate(state, play.targets[0])
        state.discard.append(play.card_id)
        return

    # ---------- Measurement ----------
    if card.kind == "MEASUREMENT":
        if len(play.targets) != 1:
            raise ValueError("Measurement требует один кубит")
        slot = play.targets[0]
        push_history(state, slot)

        side = owner_of_slot(slot)
        local = local_index(slot)

        state.protected[side][local] = True
        state.last_effect[slot] = "MEASUREMENT"
        return

    # ---------- Quantum lucky ----------
    if card.kind == "LUCKY":
        if len(play.targets) != 1:
            raise ValueError("Quantum lucky требует один кубит")

        slot = play.targets[0]
        push_history(state, slot)

        side = owner_of_slot(slot)
        local = local_index(slot)

        state.board[slot] = state.targets[side][local]
        state.last_effect[slot] = "QUANTUM_LUCKY"
        return

    # ---------- Gate ----------
    if card.kind in {
        "PAULI", "PAULI3", "PHASE", "ROTATE", "HADAMARD", "HADAMARD3"
    }:
        if len(play.targets) != card.target_count:
            raise ValueError(
                f"{card.name} требует {card.target_count} целевых кубитов"
            )

        #джля трёхкубитных карт соседство
        if card.kind in {"PAULI3", "HADAMARD3"}:
            if len(play.targets) != 3:
                raise ValueError("Трёхкубитная карта требует 3 кубита")
            xs = sorted(play.targets)
            if not (xs[1] == xs[0] + 1 and xs[2] == xs[1] + 1):
                raise ValueError("Три кубита должны быть соседними")

        for slot in play.targets:
            side = owner_of_slot(slot)
            local = local_index(slot)

            # Measurement защищает кубит от гейтов
            if state.protected[side][local]:
                continue

            push_history(state, slot)

            if card.kind == "PAULI3":
                gate = play.card_id.replace("3", "")
            elif card.kind == "HADAMARD3":
                gate = "H"
            else:
                gate = play.card_id

            state.board[slot] = transition(state.board[slot], gate)
            state.last_effect[slot] = play.card_id

        return

    raise ValueError(f"Неизвестный тип карты: {card.kind}")


def apply_action(state: GameState, action: Action, player: int) -> None:
    apply_card_play(state, action.first, player)

    # Identity может завершить ход
    if not state.skip_turns[player]:
        apply_card_play(state, action.second, player)
    else:
        apply_card_play(state, action.second, player)
    state.move_number += 1


def finish_turn(state: GameState, player: int, hand_size: int = 6) -> None:
    draw_to_hand(state, player, hand_size)

    opponent = 1 - player
    state.turn = opponent

    if state.skip_turns[opponent] > 0:
        state.skip_turns[opponent] -= 1
        state.turn = player

# REWARD

def evaluation(state: GameState) -> float:
    my_correct = correct_count(state, AI)
    opp_correct = correct_count(state, OPPONENT)

    if is_win(state, AI):
        return 100.0

    if is_win(state, OPPONENT):
        return -100.0

    return (
        3.0 * my_correct - 2.0 * opp_correct - 0.02 * state.move_number
    )


def immediate_favorability(before: GameState, after: GameState, player: int) -> int:
    """Благоприятность"""
    before_me = correct_count(before, player)
    after_me = correct_count(after, player)

    before_opp = correct_count(before, 1 - player)
    after_opp = correct_count(after, 1 - player)

    return (after_me - before_me) - (after_opp - before_opp)

# MCTS

@dataclass
class MCTSNode:
    state: GameState
    parent: Optional["MCTSNode"] = None
    action: Optional[Action] = None
    children: List["MCTSNode"] = field(default_factory=list)
    untried_actions: Optional[List[Action]] = None
    visits: int = 0
    value: float = 0.0

    @property
    def mean_value(self) -> float:
        return self.value / self.visits if self.visits else 0.0


class MCTSAgent:
    def __init__(
        self,
        iterations: int = 100000,
        exploration: float = 1.414,
        rollout_depth: int = 8,
        max_actions: int = 120,
        time_limit: float = 4.5,
        seed: int = 42,
    ):
        self.iterations = iterations
        self.exploration = exploration
        self.rollout_depth = rollout_depth
        self.max_actions = max_actions
        self.time_limit = time_limit
        self.rng = random.Random(seed)

    def opponent_policy(self, state: GameState) -> Optional[Action]:
        actions = generate_actions(state, OPPONENT, max_actions=self.max_actions)
        if not actions:
            return None
        scored = [
            (fast_action_value(state, action, OPPONENT), action)
            for action in actions
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        # случайность для разнообразия
        top = scored[:max(1, min(5, len(scored)))]
        return self.rng.choice(top)[1]

    def select(self, node: MCTSNode) -> MCTSNode:
        while (
            not terminal(node.state)
            and node.untried_actions is not None
            and not node.untried_actions
            and node.children
        ):
            log_parent = math.log(max(1, node.visits))

            def uct(child: MCTSNode) -> float:
                exploit = child.mean_value
                explore = self.exploration * math.sqrt(
                    log_parent / max(1, child.visits)
                )
                return exploit + explore

            node = max(node.children, key=uct)

        return node

    def expand(self, node: MCTSNode) -> MCTSNode:
        if node.untried_actions is None:
            node.untried_actions = generate_actions(
                node.state, AI, self.max_actions
            )

        if not node.untried_actions:
            return node

        action = node.untried_actions.pop(
            self.rng.randrange(len(node.untried_actions))
        )

        #полная копия только для выбранного продолжения
        child_state = node.state.clone()

        try:
            apply_action(child_state, action, AI)
            if not terminal(child_state):
                finish_turn(child_state, AI)

            child = MCTSNode(
                state=child_state,
                parent=node,
                action=action,
            )
            node.children.append(child)
            return child
        except Exception:
            return node

    def rollout(self, state: GameState) -> float:
        s = state.clone()

        for _ in range(self.rollout_depth):
            if terminal(s):
                break

            if s.turn == AI:
                actions = generate_actions(s, AI, max_actions=self.max_actions)
                if not actions:
                    break

                scored = [
                    (fast_action_value(s, action, AI), action)
                    for action in actions
                ]
                scored.sort(key=lambda x: x[0], reverse=True)

                pool = scored[:max(1, min(8, len(scored)))]
                action = self.rng.choice(pool)[1]

                try:
                    apply_action(s, action, AI)
                    if not terminal(s):
                        finish_turn(s, AI)
                except Exception:
                    break

            else:
                action = self.opponent_policy(s)
                if action is None:
                    break

                try:
                    apply_action(s, action, OPPONENT)
                    if not terminal(s):
                        finish_turn(s, OPPONENT)
                except Exception:
                    break

        return evaluation(s)

    def backpropagate(self, node: MCTSNode, value: float) -> None:
        while node is not None:
            node.visits += 1
            node.value += value
            node = node.parent

    def search(self, root_state: GameState) -> Tuple[Optional[Action], MCTSNode]:
        validate_state(root_state)

        root = MCTSNode(root_state.clone())
        root.untried_actions = generate_actions(
            root.state, AI, self.max_actions
        )

        if not root.untried_actions:
            return None, root
        deadline = time.perf_counter() + self.time_limit
        iterations_done = 0

        while (
            iterations_done < self.iterations
            and time.perf_counter() < deadline
        ):
            node = self.select(root)

            if not terminal(node.state):
                node = self.expand(node)

            value = self.rollout(node.state)
            self.backpropagate(node, value)
            iterations_done += 1

        root.iterations_done = iterations_done

        if not root.children:
            return None, root

        best_child = max(root.children, key=lambda child: child.visits)
        return best_child.action, root


# ЭВРИСТИКА

class HeuristicAgent:
    def __init__(self, max_actions: int = 120, seed: int = 42):
        self.max_actions = max_actions
        self.rng = random.Random(seed)

    def action_score(self, state: GameState, action: Action) -> float:
        #быстрая оценка действий
        return fast_action_value(state, action, AI)

    def choose_action(self, state: GameState) -> Optional[Action]:
        actions = generate_actions(state, AI, max_actions=self.max_actions)
        if not actions:
            return None
        scored = [(self.action_score(state, a), a) for a in actions]
        best_score = max(score for score, _ in scored)
        best = [a for score, a in scored if score == best_score]
        return self.rng.choice(best)


# ПРИЗНАКИ ДЛЯ НЕЙРОННОЙ СЕТИ

CARD_IDS = list(CARD_DB.keys())
CARD_TO_IDX = {card_id: i for i, card_id in enumerate(CARD_IDS)}

def one_hot(value: int, size: int) -> List[float]:
    result = [0.0] * size
    if 0 <= value < size:
        result[value] = 1.0
    return result

def action_features(state: GameState, action: Action) -> List[float]:
    features: List[float] = []
    for value in state.board:
        features.extend(one_hot(value, N_STATES))
    # 8 целевых значений 4 ИИ + 4 соперник
    for player in (AI, OPPONENT):
        for value in state.targets[player]:
            features.extend(one_hot(value, N_STATES))
    hand_set = set(state.hands[AI])
    features.extend([1.0 if card_id in hand_set else 0.0 for card_id in CARD_IDS])
    features.extend([1.0 if x else 0.0 for side in state.protected for x in side])
    for play in (action.first, action.second):
        card_vec = [0.0] * len(CARD_IDS)
        card_vec[CARD_TO_IDX[play.card_id]] = 1.0
        features.extend(card_vec)
        target_vec = [0.0] * N_TOTAL_QUBITS
        for slot in play.targets:
            target_vec[slot] = 1.0
        features.extend(target_vec)
    features.append(state.move_number / max(1, state.max_moves))
    return features

FEATURE_SIZE = 8 * N_STATES + 8 * N_STATES + len(CARD_IDS) + N_TOTAL_QUBITS + 2 * (len(CARD_IDS) + N_TOTAL_QUBITS) + 1
print('Размер входа нейросети:', FEATURE_SIZE)


#MLP

import numpy as np

class MLPActionValue:
    def __init__(self, input_size: int, hidden1: int = 128, hidden2: int = 64, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, np.sqrt(2 / input_size), (input_size, hidden1))
        self.b1 = np.zeros(hidden1)
        self.W2 = rng.normal(0, np.sqrt(2 / hidden1), (hidden1, hidden2))
        self.b2 = np.zeros(hidden2)
        self.W3 = rng.normal(0, np.sqrt(2 / hidden2), (hidden2, 1))
        self.b3 = np.zeros(1)

    @staticmethod
    def relu(x):
        return np.maximum(x, 0.0)

    def predict(self, X):
        X = np.asarray(X, dtype=np.float32)
        h1 = self.relu(X @ self.W1 + self.b1)
        h2 = self.relu(h1 @ self.W2 + self.b2)
        return (h2 @ self.W3 + self.b3).reshape(-1)

    def fit(self, X, y, epochs=120, lr=0.001, batch_size=64, seed=42):
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32).reshape(-1)
        rng = np.random.default_rng(seed)
        for _ in range(epochs):
            order = rng.permutation(len(X))
            for start in range(0, len(X), batch_size):
                idx = order[start:start+batch_size]
                xb, yb = X[idx], y[idx]
                z1 = xb @ self.W1 + self.b1
                h1 = self.relu(z1)
                z2 = h1 @ self.W2 + self.b2
                h2 = self.relu(z2)
                pred = (h2 @ self.W3 + self.b3).reshape(-1)
                d3 = (2.0 / len(xb)) * (pred - yb)
                dW3 = h2.T @ d3[:, None]
                db3 = d3.sum(keepdims=True)
                dh2 = d3[:, None] @ self.W3.T
                dz2 = dh2 * (z2 > 0)
                dW2 = h1.T @ dz2
                db2 = dz2.sum(axis=0)
                dh1 = dz2 @ self.W2.T
                dz1 = dh1 * (z1 > 0)
                dW1 = xb.T @ dz1
                db1 = dz1.sum(axis=0)
                self.W3 -= lr * dW3
                self.b3 -= lr * db3
                self.W2 -= lr * dW2
                self.b2 -= lr * db2
                self.W1 -= lr * dW1
                self.b1 -= lr * db1
        return self


# ОБУЧАЮЩИЕ ПРИМЕРЫ

def rank_normalize(items: List[Tuple[float, Action]]) -> Dict[Action, float]:
    if not items:
        return {}
    ordered = sorted(items, key=lambda x: x[0])
    n = len(ordered)
    if n == 1:
        return {ordered[0][1]: 1.0}
    return {action: i / (n - 1) for i, (_, action) in enumerate(ordered)}

def collect_teacher_dataset(states: List[GameState], mcts_time: float = 0.08, seed: int = 42):
    heuristic = HeuristicAgent(max_actions=120, seed=seed)
    X, y = [], []
    for idx, source_state in enumerate(states):
        state = source_state.clone()
        actions = generate_actions(state, AI, max_actions=120)
        if not actions:
            continue
        heuristic_scores = [(heuristic.action_score(state, a), a) for a in actions]
        h_rank = rank_normalize(heuristic_scores)
        teacher = MCTSAgent(iterations=5000, exploration=1.414, rollout_depth=6,
                            max_actions=80, time_limit=mcts_time, seed=seed + idx)
        _, root = teacher.search(state)
        mcts_scores = {child.action: child.mean_value for child in root.children if child.action is not None}
        m_rank = rank_normalize([(score, action) for action, score in mcts_scores.items()])
        for action in actions:
            if action in m_rank:
                target = 0.35 * h_rank[action] + 0.65 * m_rank[action]
            else:
                target = 0.35 * h_rank[action]
            X.append(action_features(state, action))
            y.append(target)
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32)

def make_training_states(n: int = 8, seed: int = 900):
    return [make_test_game(seed + i) for i in range(n)]


class NeuralAgent:
    def __init__(self, model: MLPActionValue, max_actions: int = 120):
        self.model = model
        self.max_actions = max_actions

    def choose_action(self, state: GameState) -> Optional[Action]:
        actions = generate_actions(state, AI, max_actions=self.max_actions)
        if not actions:
            return None
        X = np.asarray([action_features(state, a) for a in actions], dtype=np.float32)
        scores = self.model.predict(X)
        return actions[int(np.argmax(scores))]


def save_mlp(model, path: str) -> None:
    import numpy as _np
    _np.savez(
        path,
        W1=model.W1, b1=model.b1,
        W2=model.W2, b2=model.b2,
        W3=model.W3, b3=model.b3,
    )

def load_mlp(path: str) -> MLPActionValue:
    import os as _os
    import numpy as _np
    model = MLPActionValue(FEATURE_SIZE, hidden1=128, hidden2=64, seed=42)
    if not _os.path.exists(path):
        raise FileNotFoundError(path)
    data = _np.load(path)
    model.W1 = data["W1"]
    model.b1 = data["b1"]
    model.W2 = data["W2"]
    model.b2 = data["b2"]
    model.W3 = data["W3"]
    model.b3 = data["b3"]
    return model
