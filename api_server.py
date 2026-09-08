import time
from typing import Dict
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field
from model_engine import ModelEngine,state_from_request,move_to_dto
app=FastAPI(title='Superposition AI API',version='3.0.0'); engine=ModelEngine()
class ChooseActionRequest(BaseModel):
    model:str=Field('mcts',pattern='^(low|mcts|high)$'); aiPlayerId:str; opponentPlayerId:str; dice:Dict[str,list[str]]; targets:Dict[str,list[str]]; aiHand:list[Dict[str,str]]; opponentHand:list[Dict[str,str]]=Field(default_factory=list); deck:list[Dict[str,str]]=Field(default_factory=list); discard:list[Dict[str,str]]=Field(default_factory=list); protected:Dict[str,list[bool]]=Field(default_factory=dict); moveNumber:int=0; maxMoves:int=80; remainingMoves:int=1; currentPlayerId:str|None=None; finished:bool=False
@app.get('/health')
def health(): return {'status':'ok','models':['low','mcts','high'],'neural_model':'loaded' if engine.neural.loaded else 'not_loaded'}
@app.get('/models')
def models(): return {'models':['low','mcts','high'],'mctsTimeLimitSec':engine.mcts.time_limit,'neuralLoaded':engine.neural.loaded}
@app.post('/choose-action')
def choose(req:ChooseActionRequest):
    started=time.perf_counter()
    try:
        s=state_from_request(req.model_dump())
        if s.current_player_id and s.current_player_id!=s.ai_player_id: raise ValueError('currentPlayerId должен совпадать с aiPlayerId для запроса AI')
        a,meta=engine.choose(req.model,s)
        if a is None: raise ValueError('Нет допустимого действия для AI')
        return {'model':req.model,'action':move_to_dto(a),'thinkingTimeMs':round((time.perf_counter()-started)*1000,2),**meta}
    except ValueError as e: raise HTTPException(422,str(e))
    except Exception as e: raise HTTPException(500,f'AI error: {e}')
