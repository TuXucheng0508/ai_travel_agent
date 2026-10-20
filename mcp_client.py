"""
MCP 客户端：通过 stdio 启动 searchAPI-mcp 服务，并封装机票/酒店查询。

设计要点：
- 使用官方 `mcp` SDK 的 stdio transport 拉起远端 server（标准 MCP 接入方式）。
- 一次会话内完成 去程/回程/酒店 三次工具调用，避免重复拉起子进程。
- cwd 必须指向 searchAPI-mcp 根目录，否则 server 里的 `from config import` 会失败。
- env 需合并 os.environ（保留 PATH），并透传 SEARCHAPI_API_KEY、设 PYTHONIOENCODING。
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()  # 确保 .env 中的 SEARCHAPI_API_KEY 进入环境

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# server 目录（mcp_server_refactored.py / config.py / client.py 同目录，可被 import）
BASE_DIR = Path(__file__).resolve().parent            # ai_travel_agent/
REPO_ROOT = BASE_DIR.parent                            # 仓库根
MCP_SERVER_DIR = str(REPO_ROOT / "server")
MCP_SERVER_SCRIPT = "mcp_server_refactored.py"


def _server_params() -> StdioServerParameters:
    env = {
        **os.environ,  # 保留 PATH 等，否则子进程找不到 python
        "SEARCHAPI_API_KEY": os.getenv("SEARCHAPI_API_KEY", ""),
        "PYTHONIOENCODING": "utf-8",  # Windows 中文输出防乱码
    }
    return StdioServerParameters(
        command=sys.executable,  # 复用当前解释器，确保 fastmcp 等依赖可用
        args=[MCP_SERVER_SCRIPT],
        cwd=MCP_SERVER_DIR,
        env=env,
    )


def _extract_text(result) -> str:
    """从 CallToolResult 中提取文本片段。"""
    parts: List[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _to_json(result) -> Dict[str, Any]:
    text = _extract_text(result)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _pick_cheap_flights(data: Any, top: int = 3) -> List[Dict[str, Any]]:
    """从航班结果里挑出价格最低的 top 个（去程/回程通用）。"""
    if not isinstance(data, dict):
        return []
    options: List[Dict[str, Any]] = []
    for key in ("best_flights", "other_flights"):
        for opt in data.get(key, []) or []:
            if not isinstance(opt, dict):
                continue
            legs = opt.get("flights", []) or []
            first = legs[0] if legs else {}
            last = legs[-1] if legs else {}
            dep = first.get("departure_airport", {}) or {}
            arr = last.get("arrival_airport", {}) or {}
            options.append({
                "price": opt.get("price"),
                "airline": first.get("airline", "—"),
                "depart_time": dep.get("time", "—"),
                "arrive_time": arr.get("time", "—"),
                "duration": opt.get("total_duration") or last.get("duration") or "—",
                "stops": opt.get("stops", max(len(legs) - 1, 0)),
            })

    def price_key(o):
        p = o.get("price")
        return p if isinstance(p, (int, float)) else float("inf")

    options.sort(key=price_key)
    return options[:top]


def _pick_top_hotels(data: Any, top: int = 5) -> List[Dict[str, Any]]:
    """从酒店结果里挑评分最高的 top 个（好评优先）。"""
    if not isinstance(data, dict):
        return []
    props = data.get("properties", []) or []
    out: List[Dict[str, Any]] = []
    for p in props:
        if not isinstance(p, dict):
            continue
        rating = p.get("overall_rating") or p.get("rating")
        if rating is None and isinstance(p.get("rates"), dict):
            rating = p.get("rates", {}).get("overall")
        price = p.get("price_per_night") or p.get("price") or p.get("rates")
        if isinstance(price, dict):
            # SearchAPI google_hotels 中 price_per_night 形如
            # {"price": "$107", "extracted_price": 107}
            price = (
                price.get("extracted_price")
                or price.get("price")
                or price.get("rate")      # 兼容旧假设
                or price.get("lowest")    # 兼容旧假设
            )
        out.append({
            "name": p.get("name", "—"),
            "rating": rating,
            "price": price,
            "link": p.get("link", ""),
        })

    def rkey(o):
        r = o.get("rating")
        return r if isinstance(r, (int, float)) else -1

    out.sort(key=rkey, reverse=True)
    return out[:top]


# 中文/常见城市 → IATA 机场代码（location_search 不支持中文，故内置映射）
CITY_CODE_MAP = {
    "北京": "PEK", "上海": "SHA", "广州": "CAN", "深圳": "SZX", "杭州": "HGH",
    "成都": "CTU", "重庆": "CKG", "西安": "XIY", "武汉": "WUH", "南京": "NKG",
    "天津": "TSN", "厦门": "XMN", "青岛": "TAO", "昆明": "KMG", "长沙": "CSX",
    "三亚": "SYX", "海口": "HAK", "郑州": "CGO", "沈阳": "SHE", "大连": "DLC",
    "哈尔滨": "HRB", "乌鲁木齐": "URC", "贵阳": "KWE", "福州": "FOC", "南宁": "NNG",
    "济南": "TNA", "南昌": "KHN", "合肥": "HFE", "太原": "TYN", "长春": "CGQ",
    "兰州": "LHW", "香港": "HKG", "台北": "TPE", "澳门": "MFM", "高雄": "KHH",
    "东京": "HND", "大阪": "KIX", "名古屋": "NGO", "首尔": "ICN", "釜山": "PUS",
    "曼谷": "BKK", "新加坡": "SIN", "吉隆坡": "KUL", "纽约": "JFK", "洛杉矶": "LAX",
    "伦敦": "LHR", "巴黎": "CDG", "悉尼": "SYD", "旧金山": "SFO", "芝加哥": "ORD",
    "温哥华": "YVR", "多伦多": "YYZ", "法兰克福": "FRA", "罗马": "FCO", "迪拜": "DXB",
    "普吉": "HKT", "巴厘岛": "DPS",
}


async def _resolve_airport(session, query: str) -> str:
    """把城市名/机场名解析为 IATA 代码（支持中文城市、英文、3位代码）。"""
    q = (query or "").strip()
    if not q:
        return q
    # 已经是 3 位机场代码
    if re.fullmatch(r"[A-Za-z]{3}", q):
        return q.upper()
    # 中文 / 已知城市直接映射
    if q in CITY_CODE_MAP:
        return CITY_CODE_MAP[q]
    # 英文 / 拼音：走 location_search
    try:
        raw = await session.call_tool("search_google_flights_location_search", {"q": q})
        data = _to_json(raw)
        for loc in data.get("locations", []) or []:
            if not isinstance(loc, dict):
                continue
            for ap in loc.get("airports", []) or []:
                code = ap.get("airport_code")
                if code:
                    return str(code)
    except Exception:
        pass
    return q


async def _fetch_all(
    origin: str,
    dest: str,
    outbound: str,
    return_: str,
    top_flights: int = 3,
    top_hotels: int = 5,
):
    """在一个 MCP 会话内完成全部查询，返回 (去程3, 回程3, 酒店5)。"""
    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 把出发地/目的地解析成机场代码（支持直接输城市名）
            origin_code = await _resolve_airport(session, origin)
            dest_code = await _resolve_airport(session, dest)

            out_raw = await session.call_tool("search_google_flights", {
                "departure_id": origin_code,
                "arrival_id": dest_code,
                "outbound_date": outbound,
                "flight_type": "one_way",
            })
            ret_raw = await session.call_tool("search_google_flights", {
                "departure_id": dest_code,
                "arrival_id": origin_code,
                "outbound_date": return_,
                "flight_type": "one_way",
            })
            hotel_raw = await session.call_tool("search_google_hotels", {
                "q": dest,
                "check_in_date": outbound,
                "check_out_date": return_,
            })

            flights_out_data = _pick_cheap_flights(_to_json(out_raw), top_flights)
            flights_ret_data = _pick_cheap_flights(_to_json(ret_raw), top_flights)
            hotels_data = _pick_top_hotels(_to_json(hotel_raw), top_hotels)

            # 方案 a：为去程/回程分别生成 Google Flights 可点击链接
            try:
                out_link = _to_json(await session.call_tool("build_google_flights_link", {
                    "departure_id": origin_code,
                    "arrival_id": dest_code,
                    "outbound_date": outbound,
                    "flight_type": "one_way",
                })).get("url", "")
            except Exception:
                out_link = ""
            try:
                ret_link = _to_json(await session.call_tool("build_google_flights_link", {
                    "departure_id": dest_code,
                    "arrival_id": origin_code,
                    "outbound_date": return_,
                    "flight_type": "one_way",
                })).get("url", "")
            except Exception:
                ret_link = ""

            for f in flights_out_data:
                f["link"] = out_link
            for f in flights_ret_data:
                f["link"] = ret_link

            return flights_out_data, flights_ret_data, hotels_data


def _run(coro):
    """兼容「已有运行事件循环」的场景（如 Streamlit 主线程）。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(asyncio.run, coro).result()


def build_trip_data(
    origin: str,
    dest: str,
    outbound: str,
    return_: str,
) -> Dict[str, Any]:
    """同步入口：查机票/酒店真实数据（搜索 API 始终真实调用）。"""
    _key = (os.getenv("SEARCHAPI_API_KEY") or "").strip()
    if not _key or _key.lower() in {"your_api_key_here", "your_searchapi_key_here"}:
        raise RuntimeError(
            "未检测到有效的 SEARCHAPI_API_KEY（为空或仍是占位符 your_searchapi_key_here）。"
            "请在 ai_travel_agent/.env 中填入真实的 SearchAPI.io 密钥，MCP 子进程需要它。"
        )
    flights_out, flights_ret, hotels = _run(
        _fetch_all(origin, dest, outbound, return_)
    )
    return {
        "flights_out": flights_out,
        "flights_ret": flights_ret,
        "hotels": hotels,
    }
