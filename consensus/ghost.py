# consensus/ghost.py
"""
Pure GHOST fork choice
No votes inside — only tree + weights

Hot path prefers abs_native kernels (ghost_select_head / ghost_cumulative_weight)
with a Python reference fallback for byte-aligned behavior.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from crypto import native

logger = logging.getLogger("abs.ghost")


def _native_required() -> bool:
    return bool(native.native_crypto_status(required=False).get("required"))


def _native_fb(op: str, exc: BaseException) -> None:
    logger.warning("native %s failed; Python path: %s", op, exc)
    if _native_required():
        raise exc


def _tree_json(tree: Dict) -> str:
    return json.dumps(tree, separators=(",", ":"), ensure_ascii=False)


def _weights_json(weights: Dict[str, int]) -> str:
    return json.dumps(
        {str(k): int(v) for k, v in weights.items()},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _cumulative_weight_py(block_hash: str, tree: Dict, weights: Dict[str, int]) -> int:
    memo: Dict[str, int] = {}
    stack: List[tuple] = [(block_hash, False)]

    while stack:
        node, expanded = stack.pop()
        if expanded:
            total = weights.get(node, 0)
            for child in tree.get(node, {}).get("children", []):
                total += memo.get(child, 0)
            memo[node] = total
        else:
            stack.append((node, True))
            for child in reversed(tree.get(node, {}).get("children", [])):
                if child not in memo:
                    stack.append((child, False))

    return memo.get(block_hash, weights.get(block_hash, 0))


def get_cumulative_weight(block_hash: str, tree: Dict, weights: Dict[str, int]) -> int:
    """Cumulative weight of block and descendants (iterative — safe on long chains)."""
    if native.native_available() and hasattr(native, "ghost_cumulative_weight"):
        try:
            return int(
                native.ghost_cumulative_weight(
                    str(block_hash), _tree_json(tree), _weights_json(weights)
                )
            )
        except Exception as exc:
            _native_fb("ghost_cumulative_weight", exc)

    return _cumulative_weight_py(block_hash, tree, weights)


def _forest_roots(tree: Dict) -> List[str]:
    return [h for h, data in tree.items() if data.get("parent") is None]


def _pick_genesis(tree: Dict, weights: Dict[str, int]) -> Optional[str]:
    """Among parent=None roots, pick the heaviest subtree (stable forest GHOST)."""
    roots = _forest_roots(tree)
    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    best: Optional[str] = None
    best_w = -1
    for root in roots:
        cum = _cumulative_weight_py(root, tree, weights)
        if cum > best_w or (cum == best_w and (best is None or root < best)):
            best_w = cum
            best = root
    return best


def _select_head_python(tree: Dict, weights: Dict[str, int]) -> Optional[str]:
    if not tree:
        return None

    genesis = _pick_genesis(tree, weights)
    if genesis is None:
        return None

    current = genesis
    visited = set()

    while current not in visited:
        visited.add(current)
        children = tree.get(current, {}).get("children", [])

        if not children:
            return current

        best_child = None
        best_weight = -1

        for child in children:
            cum_weight = get_cumulative_weight(child, tree, weights)
            if cum_weight > best_weight:
                best_weight = cum_weight
                best_child = child
            elif cum_weight == best_weight and best_child is not None:
                # Tie-break: higher block number wins
                child_num = tree.get(child, {}).get("number", 0)
                best_num = tree.get(best_child, {}).get("number", 0)
                if child_num > best_num:
                    best_child = child
                elif child_num == best_num and child < best_child:
                    best_child = child

        if best_child is None:
            return current
        current = best_child

    return current


def select_head(tree: Dict, weights: Dict[str, int]) -> Optional[str]:
    """
    Pure GHOST: start from genesis, always pick child with highest cumulative weight.

    Multi-root forests (parent stubs) must not use native HashMap genesis pick —
    iteration order is non-deterministic and can strand the head on an orphan root.
    """
    if not tree:
        return None

    roots = _forest_roots(tree)
    use_native = (
        len(roots) <= 1
        and native.native_available()
        and hasattr(native, "ghost_select_head")
    )
    if use_native:
        try:
            head = native.ghost_select_head(_tree_json(tree), _weights_json(weights))
            return str(head) if head else None
        except Exception as exc:
            _native_fb("ghost_select_head", exc)

    return _select_head_python(tree, weights)


def get_chain_from_head(tree: Dict, weights: Dict[str, int]) -> List[str]:
    """Get full chain from genesis to head"""
    if native.native_available() and hasattr(native, "ghost_chain_from_head"):
        try:
            chain = native.ghost_chain_from_head(_tree_json(tree), _weights_json(weights))
            return [str(h) for h in chain]
        except Exception as exc:
            _native_fb("ghost_chain_from_head", exc)

    head = select_head(tree, weights)
    if not head:
        return []

    chain = []
    current = head
    while current:
        chain.append(current)
        current = tree.get(current, {}).get("parent")
    return list(reversed(chain))
