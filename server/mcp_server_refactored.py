"""
SearchAPI MCP 服务器 - 依照 FAST MCP 最佳实践重构。

本实现遵循生产级可用模式，主要包括：
- 基于 Pydantic 校验的配置管理
- 连接池与重试逻辑
- 带 TTL 的响应缓存
- 提升稳定性的熔断器模式
- 结构化的错误处理
- 指标采集与监控
- 健康检查
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import urllib.parse

from mcp.server.fastmcp import FastMCP
from config import load_config, get_transport, ServerConfig
from client import SearchAPIClient


# 配置日志：先使用默认级别，待配置加载完成后再更新
logging.basicConfig(
    level=logging.INFO,  # 在配置加载完成前使用默认级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# 加载配置
try:
    config = load_config()

    # 根据配置更新日志级别
    log_level = getattr(logging, config.log_level)
    logging.getLogger().setLevel(log_level)
    logger.setLevel(log_level)

    logger.info(f"Configuration loaded successfully (log_level: {config.log_level})")
except Exception as e:
    logger.error(f"Failed to load configuration: {e}")
    raise


# 初始化 FastMCP 服务器
server_config = ServerConfig()
mcp = FastMCP(server_config.name)


# 初始化 SearchAPI 客户端
api_client = SearchAPIClient(config)
logger.info("SearchAPI client initialized with connection pooling and caching")


# ============================================================================
# 健康检查与监控工具
# ============================================================================

@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """
    检查 SearchAPI 服务的健康状态。

    返回综合健康指标，包括：
    - 接口连通性状态
    - 响应延迟
    - 熔断器状态
    - 缓存统计信息
    - 请求指标

    可用此工具诊断连通性问题或监控服务健康状态。
    """
    health = await api_client.health_check()

    return {
        "api_status": health,
        "cache_stats": api_client.get_cache_stats(),
        "metrics": api_client.get_metrics(),
        "timestamp": datetime.now().isoformat()
    }


# ============================================================================
# 时间与日期工具
# ============================================================================

@mcp.tool()
async def get_current_time(
    format: str = "iso",
    days_offset: int = 0,
    return_future_dates: bool = False,
    future_days: int = 7
) -> Dict[str, Any]:
    """
    获取当前系统时间以及出行日期建议。

    对需要日期的出行预订工具（航班、酒店）尤为重要。
    提供多种格式的日期、出行建议以及酒店入住推荐。

    参数：
        format: 日期格式（"iso"、"slash"、"chinese"、"timestamp"、"full"）
        days_offset: 相对今天偏移的天数（可为负数）
        return_future_dates: 是否返回未来日期的数组
        future_days: 当 return_future_dates 为 True 时，返回的未来日期数量

    返回：
        包含以下内容的字典：
        - now: 当前日期/时间的多种格式
        - target_date: 根据 days_offset 计算得到的日期
        - travel_dates: 常用出行日期快捷项（今天、明天、下周等）
        - hotel_stay_suggestions: 推荐的入住/退房日期对
        - future_dates: 未来日期数组（按需返回）

    示例：
        - get_current_time(format="iso") → "2025-11-15"
        - get_current_time(days_offset=7) → 距今 7 天后的日期
        - get_current_time(return_future_dates=True, future_days=30) → 未来 30 天日期
    """
    now = datetime.now()
    target_date = now + timedelta(days=days_offset)

    result = {
        "now": {
            "iso": now.strftime("%Y-%m-%d"),
            "slash": now.strftime("%d/%m/%Y"),
            "chinese": now.strftime("%Y年%m月%d日"),
            "timestamp": int(now.timestamp()),
            "full": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "weekday_short": now.strftime("%a"),
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second
        },
        "target_date": {
            "iso": target_date.strftime("%Y-%m-%d"),
            "slash": target_date.strftime("%d/%m/%Y"),
            "chinese": target_date.strftime("%Y年%m月%d日"),
            "timestamp": int(target_date.timestamp()),
            "full": target_date.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": target_date.strftime("%A"),
            "weekday_short": target_date.strftime("%a"),
            "year": target_date.year,
            "month": target_date.month,
            "day": target_date.day
        },
        "travel_dates": {
            "today": now.strftime("%Y-%m-%d"),
            "tomorrow": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
            "next_week": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "next_month": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
            # 下个周五：0=周一, 1=周二, 2=周三, 3=周四, 4=周五, 5=周六, 6=周日
            # 距离周五的天数：(4 - 当天星期) % 7
            "weekend": (now + timedelta(days=(4 - now.weekday()) % 7)).strftime("%Y-%m-%d"),
            # 下个周日：距离周日的天数：(6 - 当天星期) % 7
            "weekend_end": (now + timedelta(days=(6 - now.weekday()) % 7)).strftime("%Y-%m-%d"),
        },
        "hotel_stay_suggestions": [
            {
                "check_in": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                "check_out": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
                "nights": 2,
                "description": "Weekend getaway"
            },
            {
                "check_in": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                "check_out": (now + timedelta(days=8)).strftime("%Y-%m-%d"),
                "nights": 7,
                "description": "Week-long vacation"
            },
            {
                "check_in": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
                "check_out": (now + timedelta(days=32)).strftime("%Y-%m-%d"),
                "nights": 2,
                "description": "Next month short trip"
            }
        ]
    }

    if return_future_dates:
        future_dates = []
        for i in range(future_days):
            future_date = now + timedelta(days=i)
            future_dates.append({
                "iso": future_date.strftime("%Y-%m-%d"),
                "slash": future_date.strftime("%d/%m/%Y"),
                "chinese": future_date.strftime("%Y年%m月%d日"),
                "weekday": future_date.strftime("%A"),
                "weekday_short": future_date.strftime("%a"),
                "days_from_now": i
            })
        result["future_dates"] = future_dates

    # 根据指定格式设置主日期字段
    format_map = {
        "iso": target_date.strftime("%Y-%m-%d"),
        "slash": target_date.strftime("%d/%m/%Y"),
        "chinese": target_date.strftime("%Y年%m月%d日"),
        "timestamp": int(target_date.timestamp()),
        "full": target_date.strftime("%Y-%m-%d %H:%M:%S")
    }
    result["date"] = format_map.get(format, target_date.strftime("%Y-%m-%d"))

    return result


# ============================================================================
# Google 搜索工具
# ============================================================================

@mcp.tool()
async def search_google(
    q: str,
    device: str = "desktop",
    location: Optional[str] = None,
    uule: Optional[str] = None,
    google_domain: str = "google.com",
    gl: str = "us",
    hl: str = "en",
    lr: Optional[str] = None,
    cr: Optional[str] = None,
    nfpr: str = "0",
    filter: str = "1",
    safe: str = "off",
    time_period: Optional[str] = None,
    time_period_min: Optional[str] = None,
    time_period_max: Optional[str] = None,
    num: str = "10",
    page: str = "1"
) -> Dict[str, Any]:
    """
    使用 Google 搜索网页结果、知识图谱、答案框以及相关问答。

    功能全面的 Google 搜索，支持：
    - 自然搜索（网页）结果
    - 知识图谱信息
    - 答案框与精选摘要
    - 相关问题（用户还问了什么）
    - 搜索建议
    - 广告（若存在）

    参数：
        q: 搜索关键词（必填）
        device: 设备类型（"desktop" 或 "mobile"）
        location: 用于本地化结果的地点名称（如 "New York, NY"）
        uule: Google 编码后的地理位置参数（若提供 location 则自动生成）
        google_domain: 使用的 Google 域名（默认 "google.com"）
        gl: 结果所属国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）
        lr: 语言限制
        cr: 国家限制
        nfpr: 个性化级别（"0" = 关闭，"1" = 开启）
        filter: 去重过滤（"0" = 关闭，"1" = 开启）
        safe: 安全搜索（"off"、"active"）
        time_period: 时间段过滤（如 "last_hour"、"last_day"、"last_week"）
        time_period_min: 自定义时间段起始（Unix 时间戳）
        time_period_max: 自定义时间段结束（Unix 时间戳）
        num: 每页结果数量（默认 "10"）
        page: 页码（默认 "1"）

    返回：
        搜索结果，包括自然搜索结果、知识图谱、答案框等。

    示例：
        - search_google(q="Python programming")
        - search_google(q="weather", location="San Francisco, CA")
        - search_google(q="news", time_period="last_day", num="20")
    """
    params = {
        "engine": "google",
        "q": q,
        "device": device,
        "google_domain": google_domain,
        "gl": gl,
        "hl": hl,
        "nfpr": nfpr,
        "filter": filter,
        "safe": safe,
        "num": num,
        "page": page
    }

    # 添加可选参数
    optional_params = {
        "location": location,
        "uule": uule,
        "lr": lr,
        "cr": cr,
        "time_period": time_period,
        "time_period_min": time_period_min,
        "time_period_max": time_period_max
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


@mcp.tool()
async def search_google_videos(
    q: str,
    device: str = "desktop",
    location: Optional[str] = None,
    uule: Optional[str] = None,
    google_domain: str = "google.com",
    gl: str = "us",
    hl: str = "en",
    lr: Optional[str] = None,
    cr: Optional[str] = None,
    nfpr: str = "0",
    filter: str = "1",
    safe: str = "off",
    time_period: Optional[str] = None,
    time_period_min: Optional[str] = None,
    time_period_max: Optional[str] = None,
    num: str = "10",
    page: str = "1"
) -> Dict[str, Any]:
    """
    使用 Google 视频搜索视频内容。

    返回的视频搜索结果包括：
    - 视频列表结果
    - 视频轮播（精选视频）
    - 短视频内容（Shorts）
    - 视频元数据（时长、来源、上传日期）

    参数：
        q: 搜索关键词（必填）
        device: 设备类型（"desktop" 或 "mobile"）——会影响结果格式
        location: 用于本地化结果的地点
        uule: Google 编码后的地理位置参数
        google_domain: Google 域名（默认 "google.com"）
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）
        lr: 语言限制
        cr: 国家限制
        nfpr: 个性化（"0" = 关闭，"1" = 开启）
        filter: 去重过滤（"0" = 关闭，"1" = 开启）
        safe: 安全搜索（"off"、"active"）
        time_period: 时间过滤（如 "last_hour"、"last_day"、"last_week"、"last_month"、"last_year"）
        time_period_min: 自定义起始时间戳
        time_period_max: 自定义结束时间戳
        num: 每页结果数量（默认 "10"）
        page: 页码（默认 "1"）

    返回：
        带元数据的视频搜索结果

    示例：
        - search_google_videos(q="Python tutorial")
        - search_google_videos(q="cooking recipes", time_period="last_week")
        - search_google_videos(q="news", device="mobile", num="20")
    """
    params = {
        "engine": "google_videos",
        "q": q,
        "device": device,
        "google_domain": google_domain,
        "gl": gl,
        "hl": hl,
        "nfpr": nfpr,
        "filter": filter,
        "safe": safe,
        "num": num,
        "page": page
    }

    optional_params = {
        "location": location,
        "uule": uule,
        "lr": lr,
        "cr": cr,
        "time_period": time_period,
        "time_period_min": time_period_min,
        "time_period_max": time_period_max
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


@mcp.tool()
async def search_google_ai_mode(
    q: Optional[str] = None,
    url: Optional[str] = None,
    location: Optional[str] = None,
    uule: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 Google 的 AI 概览模式进行搜索。

    除常规搜索结果外，还会返回 AI 生成的概览内容：
    - AI 生成的内容块（段落、列表、表格、代码）
    - 带引用链接、Markdown 格式的 AI 概览
    - AI 内容中引用的参考链接
    - 网页搜索结果
    - 本地结果（针对基于地点的搜索）
    - 内嵌购物结果

    参数：
        q: 搜索关键词（除非提供 url，否则必填）
        url: 要搜索的图片 URL（除非提供 q，否则必填）
        location: 用于本地化结果的地点（如 "New York, NY"）
        uule: Google 编码后的地理位置参数（若提供 location 则自动生成）

    返回：
        包含以下内容的字典：
        - text_blocks: 按类型（标题、段落、列表、表格、代码）组织的 AI 内容
        - markdown: 带引用链接的 Markdown 格式 AI 概览
        - reference_links: AI 内容中引用的来源链接数组
        - web_results: 传统网页搜索结果
        - local_results: 本地商家结果（如适用）
        - inline_shopping: 购物结果（如适用）
        - search_metadata: 请求元数据与耗时
        - search_parameters: 本次搜索使用的参数

    示例：
        - search_google_ai_mode(q="光合作用是如何进行的？")
        - search_google_ai_mode(q="最佳餐厅", location="San Francisco, CA")
        - search_google_ai_mode(url="https://example.com/image.jpg")

    说明：
        - 'q' 与 'url' 必须提供其中之一
        - AI 模式会提供带引用来源的综合答案
        - 结果包含多种格式的结构化数据（JSON、Markdown）
        - text_blocks 中的引用索引对应 reference_links 数组
    """
    if not q and not url:
        return {
            "error": "Either 'q' (search query) or 'url' (image URL) parameter must be provided",
            "type": "validation_error"
        }

    params = {
        "engine": "google_ai_mode"
    }

    # 添加必填参数
    if q:
        params["q"] = q
    if url:
        params["url"] = url

    # 添加可选参数
    if location:
        params["location"] = location
    if uule:
        params["uule"] = uule

    return await api_client.request(params)


# ============================================================================
# Google 地图工具
# ============================================================================

@mcp.tool()
async def search_google_maps(
    query: str,
    location_ll: Optional[str] = None
) -> Dict[str, Any]:
    """
    在 Google 地图中搜索地点、商家与服务。

    查找位置、商家、餐厅、酒店以及兴趣点。
    返回包含评分、评论和坐标在内的详细地点信息。

    参数：
        query: 搜索关键词（如 "coffee shops"、"hotels in Manhattan"、"Eiffel Tower"）
        location_ll: 用于定位搜索中心点的经纬度（格式："@lat,lng,zoom"）
                     示例："@40.7128,-74.0060,12z"（纽约市）

    返回：
        包含以下内容的字典：
        - local_results: 地点数组，含名称、评分、地址等详情
        - place_results: 特定地点的详细信息
        - search_metadata: 请求元数据
        - search_information: 搜索上下文与参数

    示例：
        - search_google_maps(query="中央公园附近的咖啡店")
        - search_google_maps(query="restaurants", location_ll="@40.7128,-74.0060,12z")
        - search_google_maps(query="Statue of Liberty")
    """
    params = {
        "engine": "google_maps",
        "q": query
    }

    if location_ll:
        params["ll"] = location_ll

    return await api_client.request(params)


@mcp.tool()
async def search_google_maps_place(
    place_id: Optional[str] = None,
    data_id: Optional[str] = None,
    google_domain: str = "google.com",
    hl: str = "en"
) -> Dict[str, Any]:
    """
    获取某个具体 Google 地图地点的详细信息。

    可检索全面的地点数据，包括：
    - 基础信息（名称、地址、电话、网站）
    - 评分与评论摘要
    - 照片与图片
    - 营业时间
    - 设施与服务
    - 热门时段
    - 用户问答
    - 附近地点

    参数：
        place_id: Google 地图地点 ID（若未提供 data_id 则为必填）
        data_id: 备选地点标识（若未提供 place_id 则为必填）
        google_domain: 使用的 Google 域名（默认 "google.com"）
        hl: 结果的语言代码（默认 "en"）

    返回：
        包含以下内容的字典：
        - place_info: 完整地点详情
        - ratings: 评分统计与分布直方图
        - photos: 图片集
        - hours: 营业时间与热门时段
        - amenities: 设施与服务
        - reviews_link: 完整评论链接

    示例：
        - search_google_maps_place(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")
        - search_google_maps_place(data_id="0x89c259a9b3117469:0xd134e199a405a163")

    说明：
        - place_id 与 data_id 必须提供其中之一
        - place_id 可从 search_google_maps 的返回结果中获取
    """
    if not place_id and not data_id:
        return {
            "error": "Either 'place_id' or 'data_id' must be provided",
            "type": "validation_error"
        }

    params = {
        "engine": "google_maps_place",
        "google_domain": google_domain,
        "hl": hl
    }

    if place_id:
        params["place_id"] = place_id
    elif data_id:
        params["data_id"] = data_id

    return await api_client.request(params)


@mcp.tool()
async def search_google_maps_reviews(
    place_id: Optional[str] = None,
    data_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    next_page_token: Optional[str] = None,
    sort_by: Optional[str] = None,
    rating: Optional[str] = None,
    hl: Optional[str] = None,
    gl: Optional[str] = None,
    reviews_limit: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取某个 Google 地图地点的用户评论。

    检索特定地点的用户评论、评分与反馈。
    支持过滤、排序与分页。

    参数：
        place_id: Google 地图地点 ID（若未提供 data_id 则为必填）
        data_id: 备选地点标识（若未提供 place_id 则为必填）
        topic_id: 按主题过滤评论
        next_page_token: 分页令牌
        sort_by: 排序方式（"most_relevant"、"newest"、"highest_rating"、"lowest_rating"）
        rating: 按评分过滤（"1"、"2"、"3"、"4"、"5"）
        hl: 评论的语言代码（默认 "en"）
        gl: 国家代码（默认 "us"）
        reviews_limit: 返回评论的最大数量

    返回：
        包含以下内容的字典：
        - reviews: 评论对象数组，含文本、评分、日期、用户信息
        - place_info: 基础地点信息
        - pagination: 若还有更多评论则返回下一页令牌

    示例：
        - search_google_maps_reviews(place_id="ChIJN1t_tDeuEmsRUsoyG83frY4")
        - search_google_maps_reviews(place_id="...", sort_by="newest", rating="5")
        - search_google_maps_reviews(data_id="0x...")

    说明：
        - place_id 与 data_id 必须提供其中之一
        - place_id 可从 search_google_maps 的返回结果中获取
    """
    if not place_id and not data_id:
        return {
            "error": "Either 'place_id' or 'data_id' must be provided",
            "type": "validation_error"
        }

    params = {
        "engine": "google_maps_reviews"
    }

    if place_id:
        params["place_id"] = place_id
    elif data_id:
        params["data_id"] = data_id

    optional_params = {
        "topic_id": topic_id,
        "next_page_token": next_page_token,
        "sort_by": sort_by,
        "rating": rating,
        "hl": hl,
        "gl": gl,
        "reviews_limit": reviews_limit
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


# ============================================================================
# Google 活动（事件）工具
# ============================================================================

@mcp.tool()
async def search_google_events(
    q: str,
    location: Optional[str] = None,
    uule: Optional[str] = None,
    google_domain: str = "google.com",
    gl: str = "us",
    hl: str = "en",
    chips: Optional[str] = None,
    page: str = "1"
) -> Dict[str, Any]:
    """
    在 Google 活动中搜索演唱会、会议、节日与各类活动。

    可查找本地及全球活动，包括：
    - 演唱会及音乐活动
    - 会议与聚会
    - 体育赛事
    - 节日与庆典
    - 线上（虚拟）活动
    - 展览与演出

    参数：
        q: 搜索关键词（如 "今晚的演唱会"、"旧金山的技术大会"）——必填
        location: 用于本地化结果的地点名称（如 "New York, NY"）
        uule: Google 编码后的地理位置参数
        google_domain: 使用的 Google 域名（默认 "google.com"）
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）
        chips: 活动过滤器 - 日期（"today"、"tomorrow"、"week"、"weekend"、"month"）
               或类型（如 "Virtual-Event"）
        page: 分页页码（默认 "1"）

    返回：
        包含以下内容的字典：
        - events: 含详情的活动对象数组
        - search_metadata: 请求元数据
        - search_parameters: 本次使用的参数

    活动对象包含：
        - title: 活动名称
        - date: 活动日期/时间信息
        - duration: 活动时长
        - address: 活动地点地址
        - location_name: 场馆名称
        - description: 活动描述
        - thumbnail: 活动图片
        - link: 活动详情链接
        - venue: 含评分与评论的场馆详情
        - offers: 购票选项

    示例：
        - search_google_events(q="纽约的演唱会")
        - search_google_events(q="技术大会", location="San Francisco, CA")
        - search_google_events(q="音乐节", chips="weekend")
        - search_google_events(q="线上活动", chips="Virtual-Event")

    说明：
        - 使用 chips 参数可按日期或活动类型过滤
        - 结果同时包含线下与线上活动
        - 场馆信息包含评分与评论数量
    """
    params = {
        "engine": "google_events",
        "q": q,
        "google_domain": google_domain,
        "gl": gl,
        "hl": hl,
        "page": page
    }

    optional_params = {
        "location": location,
        "uule": uule,
        "chips": chips
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


# ============================================================================
# Google 航班工具
# ============================================================================

@mcp.tool()
async def search_google_flights(
    departure_id: Optional[str] = None,
    arrival_id: Optional[str] = None,
    outbound_date: Optional[str] = None,
    flight_type: str = "round_trip",
    return_date: Optional[str] = None,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
    currency: Optional[str] = None,
    travel_class: Optional[str] = None,
    stops: Optional[str] = None,
    sort_by: Optional[str] = None,
    adults: Optional[str] = None,
    children: Optional[str] = None,
    multi_city_json: Optional[str] = None,
    show_cheapest_flights: Optional[str] = None,
    show_hidden_flights: Optional[str] = None,
    max_price: Optional[str] = None,
    carry_on_bags: Optional[str] = None,
    checked_bags: Optional[str] = None,
    included_airlines: Optional[str] = None,
    excluded_airlines: Optional[str] = None,
    outbound_times: Optional[str] = None,
    return_times: Optional[str] = None,
    emissions: Optional[str] = None,
    included_connecting_airports: Optional[str] = None,
    excluded_connecting_airports: Optional[str] = None,
    layover_duration_min: Optional[str] = None,
    layover_duration_max: Optional[str] = None,
    max_flight_duration: Optional[str] = None,
    separate_tickets: Optional[str] = None,
    infants_in_seat: Optional[str] = None,
    infants_on_lap: Optional[str] = None,
    departure_token: Optional[str] = None,
    booking_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    在 Google 航班中搜索航班选项与价格。

    提供全面的筛选条件来查找航班，包括：
    - 单程、往返与多程（多城市）行程
    - 航司偏好与排除
    - 行李要求
    - 时间与时长过滤
    - 价格上限
    - 乘客数量

    参数：
        departure_id: 出发机场代码（如 "JFK"、"LAX"）——单程/往返时必填
        arrival_id: 到达机场代码——单程/往返时必填
        outbound_date: 出发日期，格式 YYYY-MM-DD——单程/往返时必填
        flight_type: 行程类型（"one_way"、"round_trip"、"multi_city"）
        return_date: 返程日期，格式 YYYY-MM-DD——往返时必填
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）
        currency: 货币代码（如 "USD"、"EUR"）
        travel_class: 舱位等级（"economy"、"premium_economy"、"business"、"first"）
        stops: 经停次数（"0" = 直飞，"1" = 1 次经停，"2" = 2 次及以上经停）
        sort_by: 排序方式（"best"、"price"、"duration"、"departure_time"、"arrival_time"）
        adults: 成人数（默认 "1"）
        children: 儿童数
        multi_city_json: 多程行程的 JSON 字符串（当 flight_type="multi_city" 时必填）
        show_cheapest_flights: 显示最便宜的替代日期（"true"、"false"）
        show_hidden_flights: 显示隐藏/廉价航司（"true"、"false"）
        max_price: 最高价格过滤
        carry_on_bags: 随身行李件数
        checked_bags: 托运行李件数
        included_airlines: 以逗号分隔、需要包含的航司代码
        excluded_airlines: 以逗号分隔、需要排除的航司代码
        outbound_times: 出发时段过滤（如 "1" = 上午）
        return_times: 返程时段过滤
        emissions: 碳排放过滤（"low"、"medium"、"high"）
        included_connecting_airports: 允许的转机机场
        excluded_connecting_airports: 排除的转机机场
        layover_duration_min: 最短中转时长（分钟）
        layover_duration_max: 最长中转时长（分钟）
        max_flight_duration: 最长总飞行时长（分钟）
        separate_tickets: 允许分开出票（"true"、"false"）
        infants_in_seat: 占座婴儿数
        infants_on_lap: 抱坐婴儿数
        departure_token: 指定出发航班的令牌
        booking_token: 预订令牌

    返回：
        包含以下内容的字典：
        - best_flights: 推荐航班
        - other_flights: 其他航班选项
        - price_insights: 价格趋势与预测
        - airports: 机场信息
        - search_metadata: 请求元数据

    示例：
        - search_google_flights(departure_id="JFK", arrival_id="LAX", outbound_date="2025-12-01", flight_type="one_way")
        - search_google_flights(departure_id="SFO", arrival_id="NYC", outbound_date="2025-12-15", return_date="2025-12-22", travel_class="business", stops="0")
        - search_google_flights(multi_city_json='[{"departure_id":"JFK","arrival_id":"LAX","date":"2025-12-01"},{"departure_id":"LAX","arrival_id":"SFO","date":"2025-12-05"}]', flight_type="multi_city")

    说明：
        - 可使用 get_current_time() 工具获取格式正确的日期
        - 多程行程只需提供 multi_city_json
        - 日期必须使用 YYYY-MM-DD 格式
    """
    params = {
        "engine": "google_flights",
        "flight_type": flight_type
    }

    # 根据行程类型校验并添加必填参数
    if flight_type == "multi_city":
        if not multi_city_json:
            return {
                "error": "multi_city_json parameter is required for multi-city flights",
                "type": "validation_error"
            }
        params["multi_city_json"] = multi_city_json
    else:
        if not all([departure_id, arrival_id, outbound_date]):
            return {
                "error": "departure_id, arrival_id, and outbound_date are required for one-way/round-trip flights",
                "type": "validation_error"
            }
        params["departure_id"] = departure_id
        params["arrival_id"] = arrival_id
        params["outbound_date"] = outbound_date

        if flight_type == "round_trip":
            if not return_date:
                return {
                    "error": "return_date is required for round-trip flights",
                    "type": "validation_error"
                }
            params["return_date"] = return_date

    # 添加全部可选参数
    optional_params = {
        "gl": gl, "hl": hl, "currency": currency, "travel_class": travel_class,
        "stops": stops, "sort_by": sort_by, "adults": adults, "children": children,
        "show_cheapest_flights": show_cheapest_flights, "show_hidden_flights": show_hidden_flights,
        "max_price": max_price, "carry_on_bags": carry_on_bags, "checked_bags": checked_bags,
        "included_airlines": included_airlines, "excluded_airlines": excluded_airlines,
        "outbound_times": outbound_times, "return_times": return_times, "emissions": emissions,
        "included_connecting_airports": included_connecting_airports,
        "excluded_connecting_airports": excluded_connecting_airports,
        "layover_duration_min": layover_duration_min, "layover_duration_max": layover_duration_max,
        "max_flight_duration": max_flight_duration, "separate_tickets": separate_tickets,
        "infants_in_seat": infants_in_seat, "infants_on_lap": infants_on_lap,
        "departure_token": departure_token, "booking_token": booking_token
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


@mcp.tool()
async def build_google_flights_link(
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    flight_type: str = "one_way",
    return_date: Optional[str] = None,
    travel_class: Optional[str] = None,
    adults: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建可直接在浏览器中打开的 Google 航班链接（不消耗 API 额度）。

    根据出发地、目的地与日期生成 Google Flights 的深层链接，
    用户点击后可在 Google 官网上查看实时航班与价格，适合在无法调用
    SearchAPI 或希望直接跳转官网比价的场景使用。

    参数：
        departure_id: 出发机场/城市代码（如 "JFK"、"PEK"）——必填
        arrival_id: 到达机场/城市代码——必填
        outbound_date: 出发日期，格式 YYYY-MM-DD——必填
        flight_type: 行程类型（"one_way"、"round_trip"）
        return_date: 返程日期，格式 YYYY-MM-DD——往返时必填
        travel_class: 舱位等级（"economy"、"premium_economy"、"business"、"first"）
        adults: 成人数（默认 "1"）

    返回：
        包含以下内容的字典：
        - url: 可直接打开的 Google Flights 深层链接（#flt= 形式）
        - query_url: 人类可读的搜索链接（?q= 形式，便于分享）
        - departure_id / arrival_id / outbound_date / return_date / flight_type: 回显参数

    示例：
        - build_google_flights_link(departure_id="JFK", arrival_id="LAX", outbound_date="2025-12-15")
        - build_google_flights_link(departure_id="PEK", arrival_id="JFK", outbound_date="2025-12-01", return_date="2025-12-10", flight_type="round_trip")

    说明：
        - 与 search_google_flights 不同，本工具不进行任何网络请求
        - 多程（multi_city）行程请自行拼接各航段后使用 ?q= 链接
    """
    if not all([departure_id, arrival_id, outbound_date]):
        return {
            "error": "departure_id, arrival_id, and outbound_date are required",
            "type": "validation_error"
        }

    base = "https://www.google.com/travel/flights"

    if flight_type == "round_trip":
        if not return_date:
            return {
                "error": "return_date is required for round-trip flights",
                "type": "validation_error"
            }
        flt = f"{departure_id}.{arrival_id}.{outbound_date};{arrival_id}.{departure_id}.{return_date}"
    else:
        flt = f"{departure_id}.{arrival_id}.{outbound_date}"

    url = f"{base}#flt={flt}"

    # 人类可读的 ?q= 形式链接，便于分享与调试
    trip_label = "往返" if flight_type == "round_trip" else "单程"
    q = f"{trip_label}机票 {departure_id} 到 {arrival_id} {outbound_date}"
    if flight_type == "round_trip" and return_date:
        q += f" 返回 {return_date}"
    if travel_class:
        q += f" {travel_class}"
    if adults:
        q += f" {adults}人"
    query_url = f"{base}?q={urllib.parse.quote(q)}"

    return {
        "url": url,
        "query_url": query_url,
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "flight_type": flight_type,
    }


@mcp.tool()
async def search_google_flights_calendar(
    flight_type: str,
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    return_date: Optional[str] = None,
    outbound_date_start: Optional[str] = None,
    outbound_date_end: Optional[str] = None,
    return_date_start: Optional[str] = None,
    return_date_end: Optional[str] = None,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
    currency: Optional[str] = None,
    adults: Optional[str] = None,
    children: Optional[str] = None,
    travel_class: Optional[str] = None,
    stops: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取 Google 航班价格日历，展示不同日期的票价。

    通过可视化一段时间内的航班价格，找出最便宜的出行日期。
    适合行程灵活的出行规划。

    参数：
        flight_type: 行程类型（"one_way" 或 "round_trip"）
        departure_id: 出发机场代码（必填）
        arrival_id: 到达机场代码（必填）
        outbound_date: 参考出发日期，格式 YYYY-MM-DD（必填）
        return_date: 参考返程日期（往返时必填）
        outbound_date_start: 去程日历起始日期
        outbound_date_end: 去程日历结束日期
        return_date_start: 返程日历起始日期
        return_date_end: 返程日历结束日期
        gl: 国家代码
        hl: 语言代码
        currency: 货币代码
        adults: 成人数
        children: 儿童数
        travel_class: 舱位等级
        stops: 经停次数过滤

    返回：
        包含以下内容的字典：
        - price_grid: 按日期组合的价目矩阵
        - best_prices: 找到的最低价选项
        - search_metadata: 请求元数据

    示例：
        - search_google_flights_calendar(flight_type="one_way", departure_id="JFK", arrival_id="LAX", outbound_date="2025-12-01")
        - search_google_flights_calendar(flight_type="round_trip", departure_id="SFO", arrival_id="NYC", outbound_date="2025-12-15", return_date="2025-12-22")
    """
    params = {
        "engine": "google_flights_calendar",
        "flight_type": flight_type,
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date
    }

    if flight_type == "round_trip":
        if not return_date:
            return {
                "error": "return_date is required for round-trip flights",
                "type": "validation_error"
            }
        params["return_date"] = return_date

    optional_params = {
        "outbound_date_start": outbound_date_start,
        "outbound_date_end": outbound_date_end,
        "return_date_start": return_date_start,
        "return_date_end": return_date_end,
        "gl": gl, "hl": hl, "currency": currency,
        "adults": adults, "children": children,
        "travel_class": travel_class, "stops": stops
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


@mcp.tool()
async def search_google_flights_location_search(
    q: str,
    gl: str = "us",
    hl: str = "en"
) -> Dict[str, Any]:
    """
    搜索用于机票预订的机场代码与地点。

    根据部分输入提供机场与城市的自动补全建议。
    在搜索航班前，可用来查找正确的机场代码。

    参数：
        q: 搜索关键词 - 部分机场名、城市名或机场代码（必填）
           示例："New York"、"JFK"、"Los Angeles International"
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）

    返回：
        包含以下内容的字典：
        - results: 地点建议数组
        - search_metadata: 请求元数据

    结果对象包含：
        - airport_code: IATA 机场代码（如 "JFK"）
        - title: 机场与城市名称
        - context: 地理上下文（州、国家）
        - kgmid: 用于精准定位的知识图谱 ID

    示例：
        - search_google_flights_location_search(q="New York")
        - search_google_flights_location_search(q="JFK")
        - search_google_flights_location_search(q="Tokyo")
        - search_google_flights_location_search(q="Heathrow")

    说明：
        - 会返回多个匹配的机场/城市
        - 可将 airport_code 用于 search_google_flights
        - 可将 kgmid 用于精准定位
    """
    params = {
        "engine": "google_flights_location_search",
        "q": q,
        "gl": gl,
        "hl": hl
    }

    return await api_client.request(params)


@mcp.tool()
async def search_google_travel_explore(
    departure_id: str,
    arrival_id: Optional[str] = None,
    time_period: Optional[str] = None,
    gl: str = "us",
    hl: str = "en-US",
    currency: str = "USD",
    travel_mode: str = "all",
    travel_class: Optional[str] = None,
    interests: Optional[str] = None,
    stops: Optional[str] = None,
    max_price: Optional[str] = None,
    max_flight_duration: Optional[str] = None,
    carry_on_bags: Optional[str] = None,
    included_airlines: Optional[str] = None,
    adults: str = "1",
    children: Optional[str] = None,
    infants_in_seat: Optional[str] = None,
    infants_on_lap: Optional[str] = None
) -> Dict[str, Any]:
    """
    探索出行目的地并获取旅行灵感。

    无需指定精确路线或日期即可发现出行选项。
    非常适合行程规划与目的地探索。

    参数：
        departure_id: 出发机场代码或地点标识符（如 "JFK" 或 "/m/02_286"）——必填
        arrival_id: 目的地标识符或边界框坐标
                   默认 "/m/02j71"（地球上任意地点）
                   也可使用边界框："[[min_lon,min_lat],[max_lon,max_lat]]"
        time_period: 出行时段 - 往返选项：
                    - "one_week_trip_in_the_next_six_months"
                    - "two_week_trip_in_december"（或其他月份）
                    - "weekend_trip_in_january"
                    - 自定义日期："YYYY-MM-DD"
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en-US"）
        currency: 货币代码（默认 "USD"）
        travel_mode: "all"（默认）或 "flights_only"
        travel_class: "economy"、"premium_economy"、"business"、"first_class"
        interests: 目的地兴趣 - "popular"、"outdoors"、"beaches"、"museums"、"history"、"skiing"
        stops: 航班经停过滤 - "any"、"nonstop"、"one_stop_or_fewer"、"two_stops_or_fewer"
        max_price: 最高票价
        max_flight_duration: 最长飞行时长（分钟）
        carry_on_bags: 随身行李件数
        included_airlines: 航空联盟 - "ONEWORLD"、"SKYTEAM"、"STAR_ALLIANCE"
        adults: 成人数（默认 "1"，乘客总数最多 9）
        children: 儿童数
        infants_in_seat: 占座婴儿数
        infants_on_lap: 抱坐婴儿数

    返回：
        包含以下内容的字典：
        - destinations: 目的地建议数组
        - search_metadata: 请求元数据

    目的地对象包含：
        - name: 目的地名称
        - kgmid: 地点标识符
        - primary_airport: 机场代码
        - country: 国家名称
        - coordinates: [纬度, 经度]
        - distance: 距出发地的距离
        - avg_cost_per_night: 住宿费用估算
        - outbound_date: 建议出发日期
        - return_date: 建议返程日期
        - image: 目的地照片
        - flight: 含价格、经停、时长、航司的航班详情

    示例：
        - search_google_travel_explore(departure_id="JFK")
        - search_google_travel_explore(departure_id="JFK", interests="beaches")
        - search_google_travel_explore(departure_id="/m/02_286", time_period="two_week_trip_in_december")
        - search_google_travel_explore(departure_id="LAX", arrival_id="[[89.81,-11.38],[133.94,16.77]]")

    说明：
        - 非常适合发现新目的地
        - 提供机票与酒店的费用估算
        - 可按兴趣与出行偏好过滤
        - 使用地点标识符（kgmid）可进行精准定位
    """
    params = {
        "engine": "google_travel_explore",
        "departure_id": departure_id,
        "gl": gl,
        "hl": hl,
        "currency": currency,
        "travel_mode": travel_mode,
        "adults": adults
    }

    # 若未提供目的地，则使用默认值
    if arrival_id:
        params["arrival_id"] = arrival_id
    else:
        params["arrival_id"] = "/m/02j71"  # 地球（任意地点）

    optional_params = {
        "time_period": time_period,
        "travel_class": travel_class,
        "interests": interests,
        "stops": stops,
        "max_price": max_price,
        "max_flight_duration": max_flight_duration,
        "carry_on_bags": carry_on_bags,
        "included_airlines": included_airlines,
        "children": children,
        "infants_in_seat": infants_in_seat,
        "infants_on_lap": infants_on_lap
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


# ============================================================================
# Google 酒店工具
# ============================================================================

@mcp.tool()
async def search_google_hotels(
    q: str,
    check_in_date: str,
    check_out_date: str,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
    currency: Optional[str] = None,
    property_type: Optional[str] = None,
    sort_by: Optional[str] = None,
    price_min: Optional[str] = None,
    price_max: Optional[str] = None,
    property_types: Optional[str] = None,
    amenities: Optional[str] = None,
    rating: Optional[str] = None,
    free_cancellation: Optional[str] = None,
    special_offers: Optional[str] = None,
    for_displaced_individuals: Optional[str] = None,
    eco_certified: Optional[str] = None,
    hotel_class: Optional[str] = None,
    brands: Optional[str] = None,
    bedrooms: Optional[str] = None,
    bathrooms: Optional[str] = None,
    adults: Optional[str] = None,
    children_ages: Optional[str] = None,
    next_page_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    在 Google 酒店中搜索住宿选项。

    支持大量筛选条件，查找酒店、度假租赁及其他房源：
    - 价格区间与房源类型
    - 设施与服务
    - 评分与评论
    - 特惠与取消政策

    参数：
        q: 地点查询（如 "hotels in Paris"、"Manhattan hotels"）——必填
        check_in_date: 入住日期，格式 YYYY-MM-DD——必填
        check_out_date: 退房日期，格式 YYYY-MM-DD——必填
        gl: 国家代码（默认 "us"）
        hl: 语言代码（默认 "en"）
        currency: 货币代码（如 "USD"、"EUR"）
        property_type: 类型过滤（"hotel"、"vacation_rental"、"apartment" 等）
        sort_by: 排序方式（"price_low"、"price_high"、"rating"、"distance"）
        price_min: 每晚最低价
        price_max: 每晚最高价
        property_types: 以逗号分隔的类型
        amenities: 按设施过滤（如 "pool,wifi,parking"）
        rating: 最低评分（"3"、"4"、"5"）
        free_cancellation: 要求可免费取消（"true"、"false"）
        special_offers: 仅显示特惠（"true"、"false"）
        for_displaced_individuals: 流离失所者住房（"true"、"false"）
        eco_certified: 仅限环保认证房源（"true"、"false"）
        hotel_class: 星级（"2"、"3"、"4"、"5"）
        brands: 按酒店品牌过滤（逗号分隔）
        bedrooms: 最少卧室数
        bathrooms: 最少卫生间数
        adults: 成人数（默认 "2"）
        children_ages: 儿童年龄（逗号分隔，如 "5,12"）
        next_page_token: 下一页的分页令牌

    返回：
        包含以下内容的字典：
        - properties: 含价格、评分、设施的酒店列表数组
        - filters: 可用的过滤选项
        - search_metadata: 请求元数据
        - pagination: 若可用则返回下一页令牌

    示例：
        - search_google_hotels(q="New York City", check_in_date="2025-12-01", check_out_date="2025-12-05")
        - search_google_hotels(q="Paris hotels", check_in_date="2025-12-15", check_out_date="2025-12-20", rating="4", amenities="pool,wifi", price_max="200")
        - search_google_hotels(q="Tokyo", check_in_date="2026-01-10", check_out_date="2026-01-15", hotel_class="5", free_cancellation="true")

    说明：
        - 可使用 get_current_time() 获取格式正确的日期
        - 日期必须使用 YYYY-MM-DD 格式
        - 退房日期必须晚于入住日期
    """
    params = {
        "engine": "google_hotels",
        "q": q,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date
    }

    optional_params = {
        "gl": gl, "hl": hl, "currency": currency, "property_type": property_type,
        "sort_by": sort_by, "price_min": price_min, "price_max": price_max,
        "property_types": property_types, "amenities": amenities, "rating": rating,
        "free_cancellation": free_cancellation, "special_offers": special_offers,
        "for_displaced_individuals": for_displaced_individuals, "eco_certified": eco_certified,
        "hotel_class": hotel_class, "brands": brands, "bedrooms": bedrooms,
        "bathrooms": bathrooms, "adults": adults, "children_ages": children_ages,
        "next_page_token": next_page_token
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


@mcp.tool()
async def search_google_hotels_property(
    property_token: str,
    check_in_date: str,
    check_out_date: str,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
    currency: Optional[str] = None,
    adults: Optional[str] = None,
    children: Optional[str] = None,
    children_ages: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取某个具体酒店房源的详细信息。

    可检索酒店的全面详情，包括：
    - 所有可用房型与价格
    - 详细的设施与服务
    - 房源照片与描述
    - 来自不同供应商的预订选项
    - 评论与评分

    参数：
        property_token: 搜索结果中返回的唯一房源标识——必填
        check_in_date: 入住日期，格式 YYYY-MM-DD——必填
        check_out_date: 退房日期，格式 YYYY-MM-DD——必填
        gl: 国家代码
        hl: 语言代码
        currency: 货币代码
        adults: 成人数（默认 "2"）
        children: 儿童数
        children_ages: 儿童年龄（逗号分隔）

    返回：
        包含以下内容的字典：
        - property_info: 详细酒店信息
        - rooms: 可用房型与价格
        - amenities: 完整设施列表
        - reviews: 住客评论与评分
        - booking_options: 预订供应商与价格

    示例：
        - search_google_hotels_property(property_token="ChIJd...", check_in_date="2025-12-01", check_out_date="2025-12-05")
        - search_google_hotels_property(property_token="...", check_in_date="2025-12-15", check_out_date="2025-12-20", adults="2", children="1", children_ages="10")

    说明：
        - property_token 可从 search_google_hotels 的返回结果中获取
        - 可用于查看所有房型与预订选项
    """
    params = {
        "engine": "google_hotels_property",
        "property_token": property_token,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date
    }

    optional_params = {
        "gl": gl, "hl": hl, "currency": currency,
        "adults": adults, "children": children, "children_ages": children_ages
    }

    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    return await api_client.request(params)


# ============================================================================
# 服务器生命周期
# ============================================================================

def cleanup_client():
    """
    安全地清理 HTTP 客户端。

    处理事件循环可能正在运行、也可能未运行的棘手情况。
    这是必要的，因为 mcp.run() 可能会遗留一个仍在运行的事件循环。
    """
    import asyncio

    try:
        # 尝试获取当前事件循环
        loop = asyncio.get_event_loop()

        # 检查事件循环是否正在运行
        if loop.is_running():
            # 循环正在运行 - 在 finally 块中不应发生这种情况
            # mcp.run() 应在返回前已停止循环
            # 这表明 mcp.run() 的关闭流程未完成
            logger.warning(
                "Event loop still running during cleanup - this indicates "
                "incomplete shutdown by mcp.run(). Cannot perform async cleanup "
                "from synchronous context while loop is running."
            )

            # 不能在正在运行的循环上调用 run_until_complete()
            # 否则会抛出：RuntimeError: This event loop is already running
            #
            # 可选方案有限：
            # 1. 调度清理任务（即发即弃）- 不可靠
            # 2. 尝试停止循环 - 有风险，可能破坏 mcp.run()
            # 3. 接受清理不会发生 - 最佳方案
            #
            # 我们选择方案 3，并记录明确的日志
            logger.warning(
                "Skipping async cleanup because event loop is running. "
                "Resources may not be fully released. This is a limitation of "
                "the MCP framework's event loop management."
            )

            # 注意：可以尝试 loop.stop()，但这很危险：
            # - 可能破坏 mcp.run() 的关闭流程
            # - 无法保证清理能完成
            # - 可能引发其他问题

        else:
            # 循环存在但未运行 - 执行清理
            loop.run_until_complete(api_client.close())
            logger.info("Client closed using existing event loop")
    except RuntimeError:
        # 不存在事件循环，或循环已关闭
        # 新建一个事件循环专门用于清理
        try:
            asyncio.run(api_client.close())
            logger.info("Client closed using new event loop")
        except RuntimeError as e:
            # 若连这一步也失败，说明处于异常状态
            # 记录日志并继续 - 清理过程中不要崩溃
            logger.warning(f"Could not close client cleanly: {e}")
    except Exception as e:
        # 捕获其他清理错误，避免关闭时崩溃
        logger.error(f"Error during client cleanup: {e}", exc_info=True)


def main():
    """MCP 服务器的主入口。"""
    try:
        transport = get_transport()
        logger.info(f"Starting SearchAPI MCP Server with transport: {transport}")
        logger.info(f"Cache enabled: {config.enable_cache}")
        logger.info(f"Metrics enabled: {config.enable_metrics}")

        mcp.run(transport=transport)

    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        # 清理 - 使用能妥善处理事件循环状态的安全清理函数
        cleanup_client()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
