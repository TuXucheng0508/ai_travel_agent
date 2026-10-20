"""
配置管理模块，使用 Pydantic 进行参数校验。
遵循 FAST MCP 的最佳实践，将配置外部化（通过环境变量管理）。
"""
import os
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class APIConfig(BaseSettings):
    """SearchAPI 接口配置，包含各项参数的校验规则。"""

    # API 基础配置
    api_key: str = Field(
        ...,
        description="SearchAPI.io 的 API 密钥",
        validation_alias="SEARCHAPI_API_KEY"
    )
    api_url: str = Field(
        default="https://www.searchapi.io/api/v1/search",
        description="SearchAPI 的接口地址"
    )

    # HTTP 客户端配置
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="请求超时时间（秒）"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="最大重试次数"
    )
    retry_backoff: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="重试退避倍数（指数退避基数）"
    )

    # 缓存配置
    enable_cache: bool = Field(
        default=True,
        description="是否开启响应缓存"
    )
    cache_ttl: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="缓存存活时间（秒，默认 1 小时）"
    )
    cache_max_size: int = Field(
        default=1000,
        ge=10,
        le=10000,
        description="缓存条目的最大数量"
    )

    # 连接池配置
    pool_connections: int = Field(
        default=10,
        ge=1,
        le=100,
        description="连接池的实例数量"
    )
    pool_maxsize: int = Field(
        default=10,
        ge=1,
        le=100,
        description="连接池中最大的连接数"
    )

    # 监控配置
    enable_metrics: bool = Field(
        default=True,
        description="是否开启指标采集"
    )
    log_level: str = Field(
        default="INFO",
        description="日志输出级别"
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """校验 API 密钥不为空，也不是占位符。"""
        if not v:
            raise ValueError("SEARCHAPI_API_KEY 未设置，请在 .env 中配置。")
        # 拒绝 .env.example 中的占位符（大小写不敏感），避免静默带着假密钥运行
        placeholders = {"your_api_key_here", "your_searchapi_key_here", "your_doubao_key_here"}
        if v.strip().lower() in placeholders:
            raise ValueError(
                f"SEARCHAPI_API_KEY 仍是占位符（{v}），请在 .env 中填入真实的 SearchAPI.io 密钥。"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """校验日志级别是否合法。"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"日志级别必须是以下之一：{valid_levels}")
        return v_upper

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"  # 允许额外字段，便于测试使用
    )


class ServerConfig(BaseModel):
    """服务端运行时配置。"""

    name: str = Field(
        default="searchapi",
        description="MCP 服务器名称"
    )
    transport: str = Field(
        default="stdio",
        description="MCP 传输方式（stdio、sse 等）"
    )
    version: str = Field(
        default="1.0.0",
        description="服务器版本号"
    )


def load_config() -> APIConfig:
    """
    从环境变量中加载并校验配置。

    返回：
        APIConfig：已校验通过的配置对象

    异常：
        ValueError：当配置不合法时抛出
    """
    try:
        return APIConfig()
    except Exception as e:
        raise ValueError(f"加载配置失败：{e}")


def get_transport() -> str:
    """从环境变量中获取 MCP 的传输方式。"""
    return os.environ.get("MCP_TRANSPORT", "stdio")
