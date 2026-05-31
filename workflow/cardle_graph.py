import json
import time
from typing import TypedDict, List, Dict, Any, Callable
from langgraph.graph import StateGraph, END
import asyncio

# Import existing modules
from utils import logger
from client.nlu import request_nlu_async
from client.arbitration_client import request_arbitration_async
from client.nlg import request_nlg_async
from client.stream_chat import request_chat_async, process_chat_frames
from mcp_core.tool_dispatcher import dispatch_tool
from function_call.dm.factory import DMFactory, get_domain_by_intent
import prompts

class GraphState(TypedDict):
    query: str
    history: List[Dict[str, Any]]
    emit_callback: Callable
    trace_id: str
    begin_time: float
    
    nlu_result: Dict[str, Any]
    candidates: List[str]
    intent: str
    slots: Dict[str, Any]
    tool_response: str
    final_nlg: str
    error: str

def build_base_response(state: GraphState) -> dict:
    return {
        "query": state["query"],
        "trace_id": state["trace_id"],
        "cost": time.time() - state["begin_time"],
        "degraded_count": 0,
    }

async def node_local_nlu(state: GraphState):
    query = state["query"]
    history = state["history"]
    trace_id = state["trace_id"]
    
    logger.info(f"[Graph: Local NLU] starting local NLU for query='{query[:20]}'")
    nlu_response = await request_nlu_async(query, trace_id, history=history)
    
    domain = nlu_response.get("domain", "A")
    is_safe = nlu_response.get("is_safe", True)
    rewritten_query = nlu_response.get("rewritten_query", query)
    candidate_intents = nlu_response.get("candidate_intents", [])
    
    function = nlu_response.get("function", "Unknown")
    if not candidate_intents and function != "Unknown":
        candidate_intents = [{"intent": function, "slots": nlu_response.get("slots", {})}]
        
    nlu_result = {
        "domain": domain,
        "is_safe": is_safe,
        "rewritten_query": rewritten_query,
        "candidate_intents": candidate_intents
    }
    logger.info(f"[Graph: Local NLU] domain={domain} safe={is_safe} rewritten='{rewritten_query}'")
    return {"nlu_result": nlu_result}

async def node_reject(state: GraphState):
    logger.info("[Graph: Reject] Emitting reject response")
    response = build_base_response(state)
    response.update({
        "rewrite_query": state.get("nlu_result", {}).get("rewritten_query", state["query"]),
        "intent":    "拒识",
        "intent_id": "440",
        "func":      "REJECT",
        "frame":     prompts.DEFAULT_NLG,
        "seq":       1,
        "status":    -1,
        "branch":    "reject",
    })
    if "emit_callback" in state and callable(state["emit_callback"]):
        await state["emit_callback"](response)
    return {"final_nlg": prompts.DEFAULT_NLG, "intent": "拒识"}

async def node_chat(state: GraphState):
    logger.info("[Graph: Chat] Starting stream chat")
    rewritten_query = state.get("nlu_result", {}).get("rewritten_query", state["query"])
    emit = state.get("emit_callback")
    
    chat_ctx = await request_chat_async(rewritten_query)
    seq = 1
    full_answer = ""
    async for frame_content, status in process_chat_frames(chat_ctx):
        response = build_base_response(state)
        response.update({
            "rewrite_query": rewritten_query,
            "intent":    "闲聊百科",
            "intent_id": "439",
            "func":      "CHAT",
            "frame":     frame_content,
            "seq":       seq,
            "status":    status,
            "branch":    "chat",
        })
        if emit and callable(emit):
            await emit(response)
        if status == 1:
            full_answer += frame_content
            seq += 1
            
    logger.info(f"[Graph: Chat] Stream complete, answer length={len(full_answer)}")
    return {"final_nlg": full_answer, "intent": "闲聊百科"}

async def node_faq(state: GraphState):
    logger.info("[Graph: FAQ] Emitting FAQ response")
    rewritten_query = state.get("nlu_result", {}).get("rewritten_query", state["query"])
    response = build_base_response(state)
    response.update({
        "rewrite_query": rewritten_query,
        "intent":        "车辆功能问答",
        "intent_id":     "441",
        "func":          "FAQ",
        "function":      "FAQ",
        "slots":         {},
        "frame":         "关于车辆功能的解答，我们将通过 RAG 系统为您服务。",
        "seq":           1,
        "status":        0,
        "branch":        "faq",
    })
    if "emit_callback" in state and callable(state["emit_callback"]):
        await state["emit_callback"](response)
    return {"final_nlg": response["frame"], "intent": "车辆功能问答"}

async def node_arbitration(state: GraphState):
    query = state.get("nlu_result", {}).get("rewritten_query", state["query"])
    history = state.get("history", [])
    candidates = state.get("nlu_result", {}).get("candidate_intents", [])
    
    logger.info(f"[Graph: Arbitration] query='{query}' candidates={len(candidates)}")
    
    arbitration_result = await request_arbitration_async(query, history, candidates)
    function = arbitration_result.get("intent", "Unknown")
    slots = arbitration_result.get("slots", {})
    
    return {"intent": function, "slots": slots}

async def node_execute_tool(state: GraphState):
    query = state.get("nlu_result", {}).get("rewritten_query", state["query"])
    function = state.get("intent", "Unknown")
    slots = state.get("slots", {})
    
    logger.info(f"[Graph: ExecuteTool] intent='{function}' slots={slots}")
    
    if function in ["Unknown", ""]:
        return {"tool_response": "Unknown", "error": "Arbitration failed to identify intent"}
        
    domain_name = get_domain_by_intent(function)
    dm_process = DMFactory.get(domain_name)
    
    if dm_process:
        # 委托给领域 DM 统一处理 (DM 内部可能会直接生成 NLG)
        raw_response, dm_nlg = await dm_process(function, query, slots)
        tool_response = json.dumps(raw_response, ensure_ascii=False)
        return {"tool_response": tool_response, "final_nlg": dm_nlg}
    else:
        # 兜底分发
        tool_resp = await dispatch_tool(function, slots)
        tool_response = tool_resp if tool_resp else "指令下发成功"
        return {"tool_response": tool_response}

async def node_nlg(state: GraphState):
    query = state.get("nlu_result", {}).get("rewritten_query", state["query"])
    function = state.get("intent", "Unknown")
    tool_response = state.get("tool_response", "")
    error = state.get("error", "")
    final_nlg = state.get("final_nlg", "")
    slots = state.get("slots", {})
    
    logger.info(f"[Graph: NLG] Generating NLG for intent='{function}'")
    
    if error or function in ["Unknown", ""]:
        # 降级处理
        logger.info("[Graph: NLG] Degraded to REJECT")
        response = build_base_response(state)
        response.update({
            "rewrite_query": query,
            "intent":        "拒识",
            "intent_id":     "440",
            "func":          "REJECT",
            "frame":         prompts.DEFAULT_NLG,
            "seq":           1,
            "status":        -1,
            "branch":        "reject",
        })
        if "emit_callback" in state and callable(state["emit_callback"]):
            await state["emit_callback"](response)
        return {"final_nlg": prompts.DEFAULT_NLG}
        
    if not final_nlg:
        final_nlg = await request_nlg_async(query, tool_response)
        
    # 构建正常任务分支返回
    response = build_base_response(state)
    response.update({
        "rewrite_query": query,
        "intent":        function,
        "intent_id":     "1",  # Mock ID
        "func":          "SKILL",
        "function":      function,
        "slots":         slots,
        "frame":         final_nlg,
        "seq":           1,
        "status":        0,
        "branch":        "task",
    })
    
    if "emit_callback" in state and callable(state["emit_callback"]):
        await state["emit_callback"](response)
        
    return {"final_nlg": final_nlg}

# 全局路由函数
def route_after_nlu(state: GraphState):
    nlu_result = state.get("nlu_result", {})
    domain = nlu_result.get("domain", "A")
    is_safe = nlu_result.get("is_safe", True)
    
    if domain in ["C", "D"]:
        if not is_safe:
            return "node_reject"
        return "node_chat"
    elif domain == "B":
        return "node_faq"
    else:
        return "node_arbitration"

def build_cardle_graph():
    workflow = StateGraph(GraphState)
    
    workflow.add_node("node_local_nlu", node_local_nlu)
    workflow.add_node("node_reject", node_reject)
    workflow.add_node("node_chat", node_chat)
    workflow.add_node("node_faq", node_faq)
    
    workflow.add_node("node_arbitration", node_arbitration)
    workflow.add_node("node_execute_tool", node_execute_tool)
    workflow.add_node("node_nlg", node_nlg)
    
    workflow.set_entry_point("node_local_nlu")
    
    workflow.add_conditional_edges(
        "node_local_nlu",
        route_after_nlu,
        {
            "node_reject": "node_reject",
            "node_chat": "node_chat",
            "node_faq": "node_faq",
            "node_arbitration": "node_arbitration"
        }
    )
    
    workflow.add_edge("node_reject", END)
    workflow.add_edge("node_chat", END)
    workflow.add_edge("node_faq", END)
    
    workflow.add_edge("node_arbitration", "node_execute_tool")
    workflow.add_edge("node_execute_tool", "node_nlg")
    workflow.add_edge("node_nlg", END)
    
    return workflow.compile()

cardle_app = build_cardle_graph()
