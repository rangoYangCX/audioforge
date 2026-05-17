"""源绑定令牌编解码器。

纯工具函数，从 widgets/event_tree.py 提取至 utils 层，
解除 Controller → Widget 的跨层耦合。
"""

from __future__ import annotations

SOURCE_BINDING_TOKEN_SEPARATOR = "\t"


def encode_source_binding_token(event_id: str, clip_id: str) -> str:
    """将 event_id + clip_id 编码为拖拽传输令牌。"""
    return f"{event_id}{SOURCE_BINDING_TOKEN_SEPARATOR}{clip_id}"


def decode_source_binding_token(token: str) -> tuple[str, str]:
    """将拖拽传输令牌解码为 (event_id, clip_id)。"""
    normalized = str(token)
    if SOURCE_BINDING_TOKEN_SEPARATOR not in normalized:
        return "", normalized
    return tuple(normalized.split(SOURCE_BINDING_TOKEN_SEPARATOR, 1))  # type: ignore[return-value]