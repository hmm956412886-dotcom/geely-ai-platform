"""Semantic Kernel adapter for the AI Gateway REST Tool Registry."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from .access_control import authorization_headers
from .model_client import ModelConfig, load_model_config


def run_agent_query(
    question: str,
    context: dict[str, Any],
    *,
    host_session_id: str | None = None,
    gateway_base_url: str | None = None,
) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise ValueError("question is required")
    base_url = (gateway_base_url or os.getenv("AI_GATEWAY_INTERNAL_BASE_URL") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("AI_GATEWAY_INTERNAL_BASE_URL is not configured")

    tools = _read_tools(base_url, host_session_id)
    config = load_model_config()
    if config.is_configured and os.getenv("AI_AGENT_MODE", "semantic-kernel") != "deterministic":
        try:
            return asyncio.run(
                _run_semantic_kernel(question, context, tools, base_url, host_session_id, config)
            )
        except Exception as exc:
            fallback = _run_deterministic(question, context, tools, base_url, host_session_id)
            fallback["warnings"].append(f"Semantic Kernel fallback: {exc}")
            return fallback
    return _run_deterministic(question, context, tools, base_url, host_session_id)


def build_openapi_spec(tools: list[dict[str, Any]], base_url: str) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for tool in tools:
        if tool.get("side_effect") != "read_only":
            continue
        operation: dict[str, Any] = {
            "operationId": tool["name"],
            "description": tool["description"],
            "responses": {
                "200": {
                    "description": "Successful Gateway response",
                    "content": {
                        "application/json": {"schema": tool["output_schema"]},
                    },
                }
            },
        }
        if tool["method"] != "GET":
            operation["requestBody"] = {
                "required": False,
                "content": {"application/json": {"schema": tool["input_schema"]}},
            }
        paths.setdefault(tool["path"], {})[tool["method"].lower()] = operation
    return {
        "openapi": "3.0.3",
        "info": {"title": "Geely AI Gateway Tools", "version": "1.0.0"},
        "servers": [{"url": base_url.rstrip("/")}],
        "paths": paths,
    }


def _read_tools(base_url: str, host_session_id: str | None) -> list[dict[str, Any]]:
    payload = _request_json(base_url, "GET", "/api/v1/tools", None, host_session_id)
    tools = payload.get("result", {}).get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("Gateway Tool Registry returned an unsupported response")
    return [tool for tool in tools if isinstance(tool, dict)]


def _run_deterministic(
    question: str,
    context: dict[str, Any],
    tools: list[dict[str, Any]],
    base_url: str,
    host_session_id: str | None,
) -> dict[str, Any]:
    tool_name = _select_tool(question)
    tool = next(
        (
            item
            for item in tools
            if item.get("name") == tool_name and item.get("side_effect") == "read_only"
        ),
        None,
    )
    if tool is None:
        raise RuntimeError(f"Gateway Tool Registry does not expose {tool_name}")
    arguments = _tool_arguments(tool_name, question, context)
    result = _request_json(
        base_url,
        str(tool["method"]),
        str(tool["path"]),
        arguments,
        host_session_id,
    )
    return _agent_response(
        answer=_deterministic_answer(tool_name, result),
        tool_results=[(tool_name, str(tool["path"]), result)],
        framework="gateway",
        mode="deterministic",
    )


async def _run_semantic_kernel(
    question: str,
    context: dict[str, Any],
    tools: list[dict[str, Any]],
    base_url: str,
    host_session_id: str | None,
    config: ModelConfig,
) -> dict[str, Any]:
    import httpx
    from openai import AsyncOpenAI
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
    from semantic_kernel.connectors.ai.open_ai import (
        OpenAIChatCompletion,
        OpenAIChatPromptExecutionSettings,
    )
    from semantic_kernel.connectors.openapi_plugin import OpenAPIFunctionExecutionParameters
    from semantic_kernel.functions import KernelArguments

    tool_results: list[tuple[str, str, dict[str, Any]]] = []
    tools_by_path = {
        str(tool["path"]): str(tool["name"])
        for tool in tools
        if tool.get("side_effect") == "read_only"
    }

    async def capture_response(response: httpx.Response) -> None:
        await response.aread()
        path = response.request.url.path
        if path not in tools_by_path:
            return
        try:
            payload = response.json()
        except ValueError:
            return
        if isinstance(payload, dict):
            tool_results.append((tools_by_path[path], path, payload))

    params = {"host_session_id": host_session_id} if host_session_id else None
    async with httpx.AsyncClient(
        params=params,
        headers=authorization_headers(),
        event_hooks={"response": [capture_response]},
        timeout=config.timeout_seconds,
    ) as tool_client:
        model_client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=_openai_base_url(config.base_url or ""),
            timeout=config.timeout_seconds,
            max_retries=0,
        )
        try:
            service = OpenAIChatCompletion(ai_model_id=config.model, async_client=model_client)
            kernel = Kernel(services=[service])
            kernel.add_plugin_from_openapi(
                plugin_name="gateway",
                openapi_parsed_spec=build_openapi_spec(tools, base_url),
                execution_settings=OpenAPIFunctionExecutionParameters(
                    http_client=tool_client,
                    server_url_override=base_url,
                    allow_private_network_access=True,
                    server_url_validation_allowed_base_urls=[base_url],
                    timeout=config.timeout_seconds,
                ),
                description="Read-only tools exposed by the Geely AI Gateway REST API.",
            )
            settings = OpenAIChatPromptExecutionSettings(
                service_id=service.service_id,
                temperature=0.1,
                function_choice_behavior=FunctionChoiceBehavior.Auto(
                    auto_invoke=True,
                    filters={"included_plugins": ["gateway"]},
                ),
            )
            result = await kernel.invoke_prompt(
                _agent_prompt(question, context),
                arguments=KernelArguments(settings=settings),
            )
        finally:
            await model_client.close()

    if not tool_results:
        raise RuntimeError("Semantic Kernel did not invoke a Gateway REST tool")
    return _agent_response(
        answer=str(result or "").strip() or _deterministic_answer(tool_results[-1][0], tool_results[-1][2]),
        tool_results=tool_results,
        framework="semantic-kernel",
        mode="model",
        model=config.model,
    )


def _select_tool(question: str) -> str:
    normalized = question.lower()
    if any(word in normalized for word in ("比较", "对比", "compare")):
        return "compare_test_runs"
    if any(word in normalized for word in ("规范", "标准", "知识", "文档", "飞书", "knowledge")):
        return "query_knowledge"
    if any(word in normalized for word in ("洞察", "分布", "统计", "insight")):
        return "analyze_test_data_insights"
    return "analyze_test_run"


def _tool_arguments(name: str, question: str, context: dict[str, Any]) -> dict[str, Any]:
    source = _first_present(context, "source_asset_id", "source_file")
    target = _first_present(context, "target_asset_id", "target_file")
    if name == "query_knowledge":
        return {"query": question}
    if name == "compare_test_runs":
        arguments: dict[str, Any] = {}
        _assign_source(arguments, "baseline", source)
        _assign_source(arguments, "target", target)
        return arguments
    if name == "analyze_test_data_insights":
        arguments = {}
        _assign_source(arguments, "source", source)
        return arguments
    arguments = {"question": question}
    _assign_source(arguments, "source", source)
    return arguments


def _first_present(context: dict[str, Any], asset_key: str, file_key: str) -> tuple[str, str] | None:
    if context.get(asset_key):
        return ("asset_id", str(context[asset_key]))
    if context.get(file_key):
        return ("file", str(context[file_key]))
    return None


def _assign_source(
    arguments: dict[str, Any], prefix: str, source: tuple[str, str] | None
) -> None:
    if source is None:
        return
    kind, value = source
    arguments[f"{prefix}_{kind}"] = value


def _deterministic_answer(name: str, payload: dict[str, Any]) -> str:
    if name in {"analyze_test_run", "query_knowledge"}:
        return str(payload.get("answer") or "Gateway 已完成查询。")
    result = payload.get("result") or {}
    if name == "compare_test_runs":
        return str(result.get("summary") or "Gateway 已完成测试结果对比。")
    statuses = "、".join(
        f"{item.get('status')} {item.get('count')} 个"
        for item in result.get("status_counts", [])
    )
    reasons = "、".join(
        f"{item.get('reason')}（{item.get('count')} 次）"
        for item in result.get("failure_reasons", [])
    )
    answer = f"状态分布：{statuses or '暂无数据'}。"
    if reasons:
        answer += f" 主要失败原因：{reasons}。"
    return answer


def _agent_response(
    *,
    answer: str,
    tool_results: list[tuple[str, str, dict[str, Any]]],
    framework: str,
    mode: str,
    model: str | None = None,
) -> dict[str, Any]:
    last_payload = tool_results[-1][2]
    warnings: list[str] = []
    citations: list[dict[str, Any]] = []
    for _, _, payload in tool_results:
        warnings.extend(str(item) for item in payload.get("warnings", []) if item)
        citations.extend(item for item in payload.get("citations", []) if isinstance(item, dict))
    return {
        "request_id": f"req_{uuid4().hex}",
        "answer": answer,
        "data": last_payload.get("data") or last_payload.get("result") or {},
        "citations": citations,
        "warnings": warnings,
        "tool_calls": [
            {"name": name, "path": path, "request_id": payload.get("request_id")}
            for name, path, payload in tool_results
        ],
        "orchestrator": {"framework": framework, "mode": mode, "model": model},
    }


def _agent_prompt(question: str, context: dict[str, Any]) -> str:
    return (
        "你是汽车测试软件中的只读 Copilot。必须先选择并调用一个最合适的 Gateway 工具，"
        "然后只基于工具结果用中文回答；不要编造数据，不要调用写入类工具。\n"
        f"宿主上下文：{json.dumps(context, ensure_ascii=False)}\n"
        f"用户问题：{question}"
    )


def _openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    suffix = "/chat/completions"
    return normalized[: -len(suffix)] if normalized.endswith(suffix) else normalized


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    host_session_id: str | None,
) -> dict[str, Any]:
    url = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    if host_session_id:
        parsed = urlsplit(url)
        query = urlencode({"host_session_id": host_session_id})
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
    data = None
    headers = authorization_headers()
    if method.upper() != "GET":
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = json.loads(exc.read().decode("utf-8"))
        raise ValueError((detail.get("error") or {}).get("message") or str(exc)) from exc
    except URLError as exc:
        raise RuntimeError(f"Gateway REST request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Gateway REST response must be a JSON object")
    return result
