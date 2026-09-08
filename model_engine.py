from dataclasses import dataclass, field
from typing import Optional
import itertools, math, random, time, os
import numpy as np

DICE_STATES=("ZERO","ONE","PLUS","MINUS","I","I_MINUS")
CARD_TYPES=("HADAMARD","HADAMARD_3","PAULI_X","PAULI_X_3","PAULI_Y","PAULI_Y_3","PAULI_Z","PAULI_Z_3","PHASE_FORWARD","PHASE_BACKWARD","ROTATE_X","ROTATE_Y","ROTATE_Z","IDENTITY","MEASUREMENT","KRONECKER_MULTIPLICATION","QUANTUM_NOISE","SWAP","RESHUFFLE")
MOVE_TYPES=("PLAY_CARD","ROTATE_DICE","SWAP_DICES","DOUBLE_TAP","RESHUFFLE_CARD","SURRENDER")
TRANSITIONS={}
for gate,shift in {"PAULI_X":3,"PAULI_Y":3,"PAULI_Z":3,"PHASE_FORWARD":1,"PHASE_BACKWARD":-1,"ROTATE_X":1,"ROTATE_Y":1,"ROTATE_Z":1,"HADAMARD":1}.items(): TRANSITIONS[gate]={s:DICE_STATES[(i+shift)%6] for i,s in enumerate(DICE_STATES)}

@dataclass(frozen=True)
class Card: id:str; type:str
@dataclass(frozen=True)
class Target: player_id:str; slot_index:int
@dataclass(frozen=True)
class MoveAction:
    move_type:str; player_id:str; card_id:Optional[str]=None; target:Optional[Target]=None; new_state:Optional[str]=None; second_target:Optional[Target]=None; cards_to_change:tuple=()
@dataclass
class GameState:
    ai_player_id:str; opponent_player_id:str; dice:dict; targets:dict; ai_hand:list
    opponent_hand:list=field(default_factory=list); deck:list=field(default_factory=list); discard:list=field(default_factory=list)
    protected:dict=field(default_factory=dict); move_number:int=0; max_moves:int=80; remaining_moves:int=1; current_player_id:Optional[str]=None; finished:bool=False
    def clone(self): return GameState(self.ai_player_id,self.opponent_player_id,{p:list(v) for p,v in self.dice.items()},{p:list(v) for p,v in self.targets.items()},list(self.ai_hand),list(self.opponent_hand),list(self.deck),list(self.discard),{p:list(v) for p,v in self.protected.items()},self.move_number,self.max_moves,self.remaining_moves,self.current_player_id,self.finished)

def validate_state(s):
    if s.ai_player_id==s.opponent_player_id: raise ValueError("aiPlayerId и opponentPlayerId должны отличаться")
    for p in (s.ai_player_id,s.opponent_player_id):
        if len(s.dice.get(p,[]))!=4 or len(s.targets.get(p,[]))!=4: raise ValueError("У каждого игрока должно быть по 4 dice и 4 target state")
        if any(x not in DICE_STATES for x in s.dice[p]+s.targets[p]): raise ValueError("Неизвестный DiceType")
    for c in s.ai_hand+s.opponent_hand+s.deck+s.discard:
        if c.type not in CARD_TYPES: raise ValueError(f"Неизвестный CardType: {c.type}")

def correct_count(s,p): return sum(a==b for a,b in zip(s.dice[p],s.targets[p]))
def is_win(s,p): return correct_count(s,p)==4
def terminal(s): return s.finished or is_win(s,s.ai_player_id) or is_win(s,s.opponent_player_id) or s.move_number>=s.max_moves
def evaluation(s):
    if is_win(s,s.ai_player_id): return 100.0
    if is_win(s,s.opponent_player_id): return -100.0
    return 3*correct_count(s,s.ai_player_id)-2*correct_count(s,s.opponent_player_id)-.02*s.move_number
def favorability(a,b,p):
    o=b.opponent_player_id if p==b.ai_player_id else b.ai_player_id
    return (correct_count(b,p)-correct_count(a,p))-(correct_count(b,o)-correct_count(a,o))
def targets(s): return [Target(p,i) for p in (s.ai_player_id,s.opponent_player_id) for i in range(4)]

def generate_actions(s,p,max_actions=120):
    hand=s.ai_hand if p==s.ai_player_id else s.opponent_hand; out=[]
    for c in hand:
        if c.type=="SWAP": out += [MoveAction("SWAP_DICES",p,c.id,a,second_target=b) for a,b in itertools.combinations(targets(s),2)]
        elif c.type=="RESHUFFLE": out.append(MoveAction("RESHUFFLE_CARD",p,c.id,cards_to_change=tuple(x.id for x in s.deck[:4])))
        elif c.type in ("ROTATE_X","ROTATE_Y","ROTATE_Z"): out += [MoveAction("ROTATE_DICE",p,c.id,t,new_state=ns) for t in targets(s) for ns in DICE_STATES]
        else: out += [MoveAction("PLAY_CARD",p,c.id,t) for t in targets(s)]
        if len(out)>=max_actions: return out[:max_actions]
    return out

def _remove(hand,cid):
    for i,c in enumerate(hand):
        if c.id==cid: return hand.pop(i)
    raise ValueError(f"Карта {cid} отсутствует на руке")

def apply_move(s,m):
    if m.move_type=="SURRENDER": s.finished=True; s.move_number+=1; return
    if not m.card_id: raise ValueError("cardId обязателен")
    card=_remove(s.ai_hand if m.player_id==s.ai_player_id else s.opponent_hand,m.card_id)
    if m.move_type=="PLAY_CARD":
        if not m.target: raise ValueError("PLAY_CARD требует target")
        p,i=m.target.player_id,m.target.slot_index
        if card.type in TRANSITIONS: s.dice[p][i]=TRANSITIONS[card.type][s.dice[p][i]]
        elif card.type=="QUANTUM_NOISE": s.dice[p][i]=random.choice(DICE_STATES)
        elif card.type=="MEASUREMENT": s.protected.setdefault(p,[False]*4)[i]=True
        elif card.type in ("IDENTITY","KRONECKER_MULTIPLICATION"): pass
        else: raise ValueError(f"Нет локального симулятора для {card.type}")
    elif m.move_type=="ROTATE_DICE":
        if not m.target or m.new_state not in DICE_STATES: raise ValueError("ROTATE_DICE требует target и newState")
        s.dice[m.target.player_id][m.target.slot_index]=m.new_state
    elif m.move_type=="SWAP_DICES":
        if not m.target or not m.second_target: raise ValueError("SWAP_DICES требует две цели")
        a,b=m.target,m.second_target; s.dice[a.player_id][a.slot_index],s.dice[b.player_id][b.slot_index]=s.dice[b.player_id][b.slot_index],s.dice[a.player_id][a.slot_index]
    elif m.move_type=="RESHUFFLE_CARD": pass
    elif m.move_type=="DOUBLE_TAP": pass
    else: raise ValueError(f"Неизвестный move type: {m.move_type}")
    s.discard.append(card); s.move_number+=1; s.remaining_moves=max(0,s.remaining_moves-1)

def move_to_dto(m):
    if m.move_type=="PLAY_CARD": return {"type":"PLAY_CARD","playerId":m.player_id,"cardId":m.card_id,"targetSlotIndex":m.target.slot_index,"targetPlayerId":m.target.player_id}
    if m.move_type=="ROTATE_DICE": return {"type":"ROTATE_DICE","playerId":m.player_id,"cardId":m.card_id,"targetSlotIndex":m.target.slot_index,"newState":m.new_state,"targetPlayerId":m.target.player_id}
    if m.move_type=="SWAP_DICES": return {"type":"SWAP_DICES","playerId":m.player_id,"cardId":m.card_id,"firstSlotIndex":m.target.slot_index,"secondSlotIndex":m.second_target.slot_index,"firstSlotOwner":m.target.player_id,"secondSlotOwner":m.second_target.player_id}
    if m.move_type=="RESHUFFLE_CARD": return {"type":"RESHUFFLE_CARD","playerId":m.player_id,"cardId":m.card_id,"cardsToChange":list(m.cards_to_change)}
    if m.move_type=="DOUBLE_TAP": return {"type":"DOUBLE_TAP","playerId":m.player_id,"cardId":m.card_id}
    if m.move_type=="SURRENDER": return {"type":"SURRENDER","playerId":m.player_id}
    raise ValueError(m.move_type)

class HeuristicAgent:
    def choose_action(self,s):
        best=None; score=-1e18
        for a in generate_actions(s,s.ai_player_id):
            t=s.clone()
            try: apply_move(t,a); v=favorability(s,t,s.ai_player_id)+.15*evaluation(t)
            except Exception: continue
            if v>score: score,best=v,a
        return best

@dataclass
class Node:
    state:GameState; parent:Optional['Node']=None; action:Optional[MoveAction]=None; children:list=field(default_factory=list); untried:list=field(default_factory=list); visits:int=0; value:float=0
    @property
    def mean(self): return self.value/self.visits if self.visits else 0

class MCTSAgent:
    def __init__(self,time_limit=4.5,iterations=100000,rollout_depth=8,max_actions=120): self.time_limit=time_limit; self.iterations=iterations; self.rollout_depth=rollout_depth; self.max_actions=max_actions; self.rng=random.Random(42)
    def search(self,s):
        root=Node(s.clone(),untried=generate_actions(s,s.ai_player_id,self.max_actions)); deadline=time.perf_counter()+self.time_limit; n=0
        while n<self.iterations and time.perf_counter()<deadline:
            x=root
            while not x.untried and x.children and not terminal(x.state): x=max(x.children,key=lambda c:c.mean+1.414*math.sqrt(math.log(max(1,x.visits))/max(1,c.visits)))
            if x.untried:
                a=x.untried.pop(self.rng.randrange(len(x.untried))); cs=x.state.clone()
                try: apply_move(cs,a)
                except Exception: n+=1; continue
                x.children.append(Node(cs,x,a,untried=generate_actions(cs,cs.ai_player_id,self.max_actions))); x=x.children[-1]
            rs=x.state.clone()
            for _ in range(self.rollout_depth):
                if terminal(rs): break
                acts=generate_actions(rs,rs.current_player_id or rs.ai_player_id,24)
                if not acts: break
                try: apply_move(rs,self.rng.choice(acts))
                except Exception: break
            v=evaluation(rs)
            while x: x.visits+=1; x.value+=v; x=x.parent
            n+=1
        root.iterations_done=n
        return (max(root.children,key=lambda c:c.visits).action if root.children else None),root

def action_features(s,a):
    def oh(v,vals): return [float(x==v) for x in vals]
    f=[]
    for p in (s.ai_player_id,s.opponent_player_id):
        for x in s.dice[p]: f+=oh(x,DICE_STATES)
        for x in s.targets[p]: f+=oh(x,DICE_STATES)
    f += [float(any(c.type==t for c in s.ai_hand)) for t in CARD_TYPES]
    f += [float(x) for p in (s.ai_player_id,s.opponent_player_id) for x in s.protected.get(p,[False]*4)]
    f += oh(a.move_type,MOVE_TYPES)
    ctype=next((c.type for c in s.ai_hand if c.id==a.card_id),""); f += oh(ctype,CARD_TYPES)
    if a.target: f += [float(a.target.player_id==p) for p in (s.ai_player_id,s.opponent_player_id)]+oh(a.target.slot_index,range(4))
    else: f += [0.0]*6
    f.append(s.move_number/max(1,s.max_moves)); return np.asarray(f,dtype=np.float32)

class NeuralAgent:
    def __init__(self,path,max_actions=120):
        self.loaded=False; self.max_actions=max_actions
        try:
            d=np.load(path); self.W1,self.b1,self.W2,self.b2,self.W3,self.b3=[d[k] for k in ('W1','b1','W2','b2','W3','b3')]
            self.loaded=self.W1.shape[0]==155
        except Exception: self.loaded=False
    def choose_action(self,s):
        acts=generate_actions(s,s.ai_player_id,self.max_actions)
        if not acts or not self.loaded: return None
        X=np.stack([action_features(s,a) for a in acts]); h=np.maximum(X@self.W1+self.b1,0); h=np.maximum(h@self.W2+self.b2,0); y=(h@self.W3+self.b3).ravel(); return acts[int(np.argmax(y))]

def state_from_request(d):
    cards=lambda xs:[Card(str(x['id']),x['type']) for x in xs]
    s=GameState(d['aiPlayerId'],d['opponentPlayerId'],d['dice'],d['targets'],cards(d.get('aiHand',[])),cards(d.get('opponentHand',[])),cards(d.get('deck',[])),cards(d.get('discard',[])),d.get('protected',{}),d.get('moveNumber',0),d.get('maxMoves',80),d.get('remainingMoves',1),d.get('currentPlayerId',d['aiPlayerId']),d.get('finished',False)); validate_state(s); return s

class ModelEngine:
    def __init__(self):
        self.heuristic=HeuristicAgent(); self.mcts=MCTSAgent(float(os.getenv('MCTS_TIME_LIMIT','4.5'))); self.neural=NeuralAgent(os.getenv('NEURAL_MODEL_PATH',os.path.join(os.path.dirname(__file__),'neural_model_demo.npz')))
    def choose(self,model,s):
        if model=='mcts': a,r=self.mcts.search(s); return a,{'iterations':r.iterations_done,'rootChildren':len(r.children)}
        if model=='high' and self.neural.loaded: return self.neural.choose_action(s),{'neuralModel':'loaded'}
        return self.heuristic.choose_action(s),{'neuralModel':'fallback' if model=='high' else None}
