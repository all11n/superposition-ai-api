# -*- coding: utf-8 -*-
"""
FastAPI HTTP API for Superposition AI.

POST /choose-action
GET  /health
GET  /models
"""
from pathlib import Path
import time
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from model_engine import (
    GameState, HeuristicAgent, MCTSAgent, NeuralAgent,
    load_mlp, validate_state, correct_count, immediate_favorability,
    AI, OPPONENT, CARD_DB, TEST_DECK,
)

BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_FILE = BASE_DIR / "neural_model_demo.npz"

app = FastAPI(
    title="Superposition AI API",
    version="0.1.0",
    description="API для уровней LOW / MCTS / HIGH игры «Суперпозиция»",
)

class Hands(BaseModel):
    ai: List[str] = Field(..., min_length=2)
    opponent: List[str] = Field(default_factory=list)

class GameRequest(BaseModel):
    model: Literal["low", "mcts", "high"] = "mcts"
    board: List[int] = Field(..., min_length=8, max_length=8)
    targets: List[List[int]] = Field(..., min_length=2, max_length=2)
    hands: Hands
    deck: List[str] = Field(default_factory=list)
    discard: List[str] = Field(default_factory=list)
    move_number: int = Field(default=0, ge=0)
    max_moves: int = Field(default=80, ge=1)
    protected: List[List[bool]] = Field(
        default_factory=lambda: [[False]*4, [False]*4]
    )
    time_limit: Optional[float] = Field(default=None, gt=0, le=4.5)

class CardPlayResponse(BaseModel):
    card_id: str
    targets: List[int]

class ActionResponse(BaseModel):
    first: CardPlayResponse
    second: CardPlayResponse

class ChooseActionResponse(BaseModel):
    model: str
    action: ActionResponse
    thinking_time_ms: float
    ai_correct_before: int
    opponent_correct_before: int
    favorability: Optional[int] = None
    iterations: Optional[int] = None

def build_state(req: GameRequest) -> GameState:
    # для протокола API deck/discard можно передавать пустыми
    # для MCTS желательно передавать реальную колоду и сброс
    state = GameState(
        board=req.board.copy(),
        targets=[row.copy() for row in req.targets],
        hands=[req.hands.ai.copy(), req.hands.opponent.copy()],
        deck=req.deck.copy(),
        discard=req.discard.copy(),
        move_number=req.move_number,
        max_moves=req.max_moves,
        protected=[row.copy() for row in req.protected],
    )
    try:
        validate_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return state

def serialize_action(action):
    if action is None:
        return None
    return ActionResponse(
        first=CardPlayResponse(
            card_id=action.first.card_id,
            targets=list(action.first.targets),
        ),
        second=CardPlayResponse(
            card_id=action.second.card_id,
            targets=list(action.second.targets),
        ),
    )

# модель загружается единожды
try:
    neural_model = load_mlp(str(WEIGHTS_FILE))
    neural_agent = NeuralAgent(neural_model, max_actions=120)
    neural_status = "loaded"
except Exception as exc:
    neural_agent = None
    neural_status = f"error: {exc}"

@app.get("/health")
def health():
    return {
        "status": "ok",
        "neural_model": neural_status,
        "models": ["low", "mcts", "high"],
    }

@app.get("/models")
def models():
    return {
        "models": [
            {
                "id": "low",
                "name": "Heuristic",
                "description": "Эвристическая модель",
            },
            {
                "id": "mcts",
                "name": "MCTS",
                "description": "Поисковая модель с построением дерева",
                "default_time_limit_sec": 4.5,
            },
            {
                "id": "high",
                "name": "Neural",
                "description": "MLP, обученная на демонстрационных данных MCTS и эвристики",
            },
        ]
    }

@app.post("/choose-action", response_model=ChooseActionResponse)
def choose_action(req: GameRequest):
    state = build_state(req)

    # MCTS необходимы карты оппонента для более качественных симуляций
    if req.model == "mcts" and len(req.hands.opponent) < 2:
        raise HTTPException(
            status_code=422,
            detail="Для модели mcts необходимо передать hands.opponent минимум с двумя картами.",
        )

    before = state.clone()
    ai_correct = correct_count(state, AI)
    opp_correct = correct_count(state, OPPONENT)

    start = time.perf_counter()

    if req.model == "low":
        agent = HeuristicAgent(max_actions=120, seed=42)
        action = agent.choose_action(state)
        iterations = None
    elif req.model == "mcts":
        agent = MCTSAgent(
            iterations=100000,
            exploration=1.414,
            rollout_depth=8,
            max_actions=120,
            time_limit=req.time_limit or 4.5,
            seed=42,
        )
        action, root = agent.search(state)
        iterations = getattr(root, "iterations_done", root.visits)
    else:
        if neural_agent is None:
            raise HTTPException(
                status_code=503,
                detail="Нейросетевая модель не загрузилась",
            )
        action = neural_agent.choose_action(state)
        iterations = None

    elapsed = time.perf_counter() - start

    if action is None:
        raise HTTPException(status_code=422, detail="Нет допустимого действия")

    after = before.clone()
    try:
        from model_engine import apply_action
        apply_action(after, action, AI)
        fav = immediate_favorability(before, after, AI)
    except Exception:
        fav = None

    return ChooseActionResponse(
        model=req.model,
        action=serialize_action(action),
        thinking_time_ms=round(elapsed * 1000, 2),
        ai_correct_before=ai_correct,
        opponent_correct_before=opp_correct,
        favorability=fav,
        iterations=iterations,
    )
