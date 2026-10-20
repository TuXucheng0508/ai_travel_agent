"""
AI 旅行管家核心：编排 MCP 真实数据 + 豆包生成攻略。

流程：
1. build_trip() 先通过 mcp_client 取真实机票(去程3/回程3)/酒店(好评5)。
2. get_plan() 生成攻略：
   - 目的地为「杭州」时直接读本地缓存 md，免豆包费用（测试用）；
   - 其他目的地把真实数据注入提示词，调用豆包 responses 接口生成 6 段攻略。
"""
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

from mcp_client import build_trip_data

DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
# 豆包缓存攻略（杭州三天），缓存文件与本脚本同目录（ai_travel_agent/）
BASE_DIR = Path(__file__).resolve().parent   # ai_travel_agent/
CACHE_MD_PATH = BASE_DIR / "缓存.md"

MODEL = "doubao-seed-2-0-pro-260215"
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"


# ---------- 数据格式化（供提示词 / UI 复用） ----------

def _format_flights(flights: List[Dict[str, Any]]) -> str:
    if not flights:
        return "（无数据）"
    lines = []
    for i, f in enumerate(flights, 1):
        lines.append(
            f"{i}. {f.get('airline', '—')} | 价格: {f.get('price', '—')} | "
            f"出发: {f.get('depart_time', '—')} 到达: {f.get('arrive_time', '—')} | "
            f"时长: {f.get('duration', '—')} | 经停: {f.get('stops', '—')}"
        )
    return "\n".join(lines)


def _format_hotels(hotels: List[Dict[str, Any]]) -> str:
    if not hotels:
        return "（无数据）"
    lines = []
    for i, h in enumerate(hotels, 1):
        lines.append(
            f"{i}. {h.get('name', '—')} | 评分: {h.get('rating', '—')} | 价格: {h.get('price', '—')}"
        )
    return "\n".join(lines)


# ---------- 攻略生成 ----------

def get_plan(
    dest: str,
    flights_out: List[Dict[str, Any]],
    flights_ret: List[Dict[str, Any]],
    hotels: List[Dict[str, Any]],
) -> str:
    """生成攻略：杭州走缓存，其他走豆包。"""
    # 测试阶段：杭州直接读缓存，不花豆包钱
    if dest.strip() == "杭州" and CACHE_MD_PATH.exists():
        return CACHE_MD_PATH.read_text(encoding="utf-8")

    prompt = f"""
    你是一名顶级的【私人旅行管家】，以下是针对《{dest}》的真实查询数据，请严格基于这些数据生成保姆级旅行攻略（景点/美食可基于常识补充，但机票/酒店信息必须与下方一致）：

    【去程低价机票 Top3】
    {_format_flights(flights_out)}

    【回程低价机票 Top3】
    {_format_flights(flights_ret)}

    【好评酒店 Top5】
    {_format_hotels(hotels)}

    请按以下6个结构化维度定制攻略：

    1. 极简行程表（唯一地点+精准时间）：
    - 每日行程仅规划1个核心景点；
    - 标注景点间交通方式（含预估时间）；
    - 明确景点门票信息；时间安排需覆盖景点浏览时长。

    2. 交通住宿最优解（行程匹配+数据支撑）：
    - 住宿地点需与每日行程起点/终点直接关联；
    - 交通方案标注“最优”依据（耗时最短/费用最低/换乘最少）。

    3. 避坑与防雷清单（分类+场景化提示）：
    - 按“景点/交通/消费/服务”分类；每项说明“坑点表现”+“避坑方法”。

    4. 本地人吃喝指南（分层推荐+真实属性）：
    - 分“必吃主食/特色小吃/隐藏小店”三层；标注店铺属性。

    5. 突发情况B计划（场景对应+可执行方案）：
    - 按“天气突变/景点关闭/交通延误”分类；每项给替代地点/调整方案。

    6. 旅行前物资一句话总结（核心必备+无冗余）：仅提炼10项以内核心物资。
    """
    return _call_doubao(prompt)


def _call_doubao(prompt: str) -> str:
    import requests

    if not DOUBAO_API_KEY or DOUBAO_API_KEY == "your_doubao_key_here":
        return "（未配置 DOUBAO_API_KEY，无法调用豆包。已跳过攻略生成。）"

    headers = {
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }
    resp = requests.post(DOUBAO_URL, headers=headers, json=data, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    texts = []
    for item in result.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    texts.append(c.get("text", ""))
    return "\n\n".join(texts)


# ---------- 顶层编排 ----------

def build_trip(origin: str, dest: str, outbound: str, return_: str) -> Dict[str, Any]:
    """对外入口：真实查机票/酒店 + 生成攻略。"""
    trip = build_trip_data(origin, dest, outbound, return_)
    plan = get_plan(dest, trip["flights_out"], trip["flights_ret"], trip["hotels"])
    return {
        "flights_out": trip["flights_out"],
        "flights_ret": trip["flights_ret"],
        "hotels": trip["hotels"],
        "plan": plan,
    }
