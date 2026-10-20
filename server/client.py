"""
HTTP 客户端，内置连接池、重试逻辑与熔断器。
遵循 FAST MCP 的最佳实践，实现高可用的接口通信。
"""
import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import httpx
from config import APIConfig


class CircuitBreaker:
    """
    熔断器模式实现，用于fail-safe（故障安全）设计。
    当外部接口不可用时，防止故障级联扩散。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # 状态：closed（关闭）、open（打开）、half_open（半开）
        self.half_open_calls = 0

    def call(self, func):
        """装饰器：用熔断逻辑包裹目标函数的调用。"""
        async def wrapper(*args, **kwargs):
            if self.state == "open":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half_open"
                    self.half_open_calls = 0
                else:
                    raise Exception("熔断器处于 OPEN 状态 - 服务不可用")

            try:
                result = await func(*args, **kwargs)

                # 成功调用：若在半开状态下则累加计数，满足条件后恢复关闭
                if self.state == "half_open":
                    self.half_open_calls += 1
                    if self.half_open_calls >= self.half_open_max_calls:
                        self.state = "closed"
                        self.failure_count = 0

                return result

            except Exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = "open"

                raise e

        return wrapper


class CacheManager:
    """
    简单的内存缓存，支持 TTL（存活时间）。
    实现了 FAST MCP 最佳实践中的多级缓存策略。
    """

    def __init__(self, ttl: int = 3600, max_size: int = 1000):
        self.ttl = ttl
        self.max_size = max_size
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.access_times: Dict[str, float] = {}

    def _generate_key(self, params: Dict[str, Any]) -> str:
        """根据请求参数生成缓存键。"""
        # 对参数排序，保证相同参数生成一致的键
        sorted_params = json.dumps(params, sort_keys=True)
        return hashlib.md5(sorted_params.encode()).hexdigest()

    def get(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """获取缓存响应；若不存在或已过期则返回 None。"""
        key = self._generate_key(params)

        if key not in self.cache:
            return None

        # 判断是否已过期
        if time.time() - self.access_times[key] > self.ttl:
            del self.cache[key]
            del self.access_times[key]
            return None

        return self.cache[key]

    def set(self, params: Dict[str, Any], response: Dict[str, Any]) -> None:
        """将响应写入缓存（带 TTL）。"""
        key = self._generate_key(params)

        # 仅在「缓存已满」且「写入的是新键」时才淘汰旧数据
        # 更新已存在的键时不触发淘汰
        if key not in self.cache and len(self.cache) >= self.max_size:
            # 缓存已满且为新键 —— 淘汰最久未访问的条目
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]

        # 写入缓存（新增或更新）
        self.cache[key] = response
        self.access_times[key] = time.time()

    def clear(self) -> None:
        """清空所有缓存条目。"""
        self.cache.clear()
        self.access_times.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存的统计信息。"""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl": self.ttl
        }


class MetricsCollector:
    """
    指标采集器，用于监控与可观测性。
    记录请求数、延迟、错误数等信息。
    """

    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.latencies = []
        self.errors_by_type = {}

    def record_request(self, latency: float, from_cache: bool = False):
        """记录一次成功请求。"""
        self.request_count += 1
        self.latencies.append(latency)

        # 仅保留最近 1000 条延迟记录
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]

        if from_cache:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def record_error(self, error_type: str):
        """记录一次错误发生。"""
        self.error_count += 1
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        """获取当前指标统计。"""
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        p95_latency = sorted(self.latencies)[int(len(self.latencies) * 0.95)] if self.latencies else 0
        p99_latency = sorted(self.latencies)[int(len(self.latencies) * 0.99)] if self.latencies else 0

        cache_hit_rate = (
            self.cache_hits / (self.cache_hits + self.cache_misses)
            if (self.cache_hits + self.cache_misses) > 0
            else 0
        )

        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / self.request_count if self.request_count > 0 else 0,
            "cache_hit_rate": cache_hit_rate,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "latency": {
                "avg": round(avg_latency, 3),
                "p95": round(p95_latency, 3),
                "p99": round(p99_latency, 3)
            },
            "errors_by_type": self.errors_by_type
        }


class SearchAPIClient:
    """
    面向 SearchAPI.io 的高可用 HTTP 客户端，
    内置连接池、重试逻辑、缓存与熔断器模式。
    """

    def __init__(self, config: APIConfig):
        self.config = config

        # 初始化带连接池的 HTTP 客户端
        limits = httpx.Limits(
            max_connections=config.pool_connections,
            max_keepalive_connections=config.pool_maxsize
        )

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout),
            limits=limits,
            follow_redirects=True
        )

        # 若开启缓存则初始化缓存管理器
        self.cache = (
            CacheManager(ttl=config.cache_ttl, max_size=config.cache_max_size)
            if config.enable_cache
            else None
        )

        # 初始化熔断器
        self.circuit_breaker = CircuitBreaker()

        # 初始化指标采集器
        self.metrics = MetricsCollector() if config.enable_metrics else None

    async def request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        发起接口请求，整合重试、缓存与错误处理。

        参数：
            params: 请求参数（不含 api_key，会在内部自动补充）

        返回：
            接口响应的字典对象

        异常：
            Exception: 当重试全部失败后抛出
        """
        # 在补充 API 密钥前先查缓存（避免密钥轮换导致缓存失效）
        if self.cache:
            cached = self.cache.get(params)
            if cached:
                if self.metrics:
                    self.metrics.record_request(latency=0, from_cache=True)
                return cached

        # 为实际请求补充 API 密钥
        params_with_key = {**params, "api_key": self.config.api_key}

        # 发起请求：重试逻辑包裹在熔断器中
        start_time = time.time()

        try:
            # 将熔断器接入请求链路
            response = await self._request_with_circuit_breaker(params_with_key)
            latency = time.time() - start_time

            # 缓存成功的响应（使用不含密钥的原始参数作为键）
            if self.cache and "error" not in response:
                self.cache.set(params, response)

            # 记录指标
            if self.metrics:
                self.metrics.record_request(latency=latency, from_cache=False)

            return response

        except Exception as e:
            if self.metrics:
                self.metrics.record_error(type(e).__name__)
            raise

    async def _request_with_circuit_breaker(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        在熔断器保护下发起请求。

        参数：
            params: 包含 API 密钥的请求参数

        返回：
            接口响应的字典对象

        异常：
            Exception: 当熔断器打开或请求失败时抛出
        """
        if self.circuit_breaker.state == "open":
            if time.time() - self.circuit_breaker.last_failure_time > self.circuit_breaker.recovery_timeout:
                self.circuit_breaker.state = "half_open"
                self.circuit_breaker.half_open_calls = 0
            else:
                raise Exception("熔断器处于 OPEN 状态 - 服务不可用")

        try:
            result = await self._request_with_retry(params)

            # 检查返回结果是否为错误响应（并非抛异常）
            # 用于应对 4xx 错误以及重试耗尽后返回的错误字典
            if isinstance(result, dict) and "error" in result:
                # 将错误响应也视为失败，计入熔断器
                self.circuit_breaker.failure_count += 1
                self.circuit_breaker.last_failure_time = time.time()

                if self.circuit_breaker.failure_count >= self.circuit_breaker.failure_threshold:
                    self.circuit_breaker.state = "open"

                return result  # 仍把错误返回给调用方

            # 成功 —— 重置失败计数并更新状态
            if self.circuit_breaker.state == "half_open":
                self.circuit_breaker.half_open_calls += 1
                if self.circuit_breaker.half_open_calls >= self.circuit_breaker.half_open_max_calls:
                    self.circuit_breaker.state = "closed"
                    self.circuit_breaker.failure_count = 0
            elif self.circuit_breaker.state == "closed":
                # 关键点：成功时重置失败计数，避免失败数持续累积
                self.circuit_breaker.failure_count = 0

            return result

        except Exception as e:
            # 处理异常（网络错误、超时等）
            self.circuit_breaker.failure_count += 1
            self.circuit_breaker.last_failure_time = time.time()

            if self.circuit_breaker.failure_count >= self.circuit_breaker.failure_threshold:
                self.circuit_breaker.state = "open"

            raise e

    async def _request_with_retry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """发起 HTTP 请求，使用指数退避进行重试。"""
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self.client.get(
                    self.config.api_url,
                    params=params
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                # 4xx 客户端错误不重试
                if 400 <= e.response.status_code < 500:
                    return self._format_error_response(e)

                last_exception = e

            except httpx.HTTPError as e:
                last_exception = e

            except Exception as e:
                last_exception = e

            # 重试前按指数退避等待
            if attempt < self.config.max_retries:
                backoff = self.config.retry_backoff * (2 ** attempt)
                await asyncio.sleep(backoff)

        # 所有重试均失败
        return self._format_error_response(last_exception)

    def _format_error_response(self, error: Exception) -> Dict[str, Any]:
        """将异常格式化为结构化的错误响应。"""
        error_detail = None

        if isinstance(error, httpx.HTTPStatusError):
            try:
                error_detail = error.response.json()
            except ValueError:
                error_detail = error.response.text

            return {
                "error": f"HTTP {error.response.status_code}: {error.response.reason_phrase}",
                "details": error_detail,
                "type": "http_error",
                "status_code": error.response.status_code
            }

        return {
            "error": str(error),
            "type": type(error).__name__,
            "details": None
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        对 SearchAPI 执行健康检查。

        返回：
            健康检查状态
        """
        try:
            # 发起一次最小化的测试请求
            params = {
                "engine": "google",
                "q": "test",
                "num": "1"
            }
            start_time = time.time()
            response = await self.request(params)
            latency = time.time() - start_time

            if "error" in response:
                return {
                    "status": "unhealthy",
                    "latency_ms": round(latency * 1000, 2),
                    "error": response["error"]
                }

            return {
                "status": "healthy",
                "latency_ms": round(latency * 1000, 2),
                "circuit_breaker": self.circuit_breaker.state
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "circuit_breaker": self.circuit_breaker.state
            }

    def get_metrics(self) -> Optional[Dict[str, Any]]:
        """获取当前指标数据。"""
        if not self.metrics:
            return None
        return self.metrics.get_stats()

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """获取缓存统计信息。"""
        if not self.cache:
            return None
        return self.cache.get_stats()

    async def close(self):
        """关闭 HTTP 客户端并释放资源。"""
        await self.client.aclose()
