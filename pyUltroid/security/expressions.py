"""A deliberately small arithmetic expression evaluator."""

import ast
import math
import operator
from typing import Any, Callable, Dict


class ExpressionError(ValueError):
    """Raised when an expression is invalid or exceeds safety limits."""


_BINARY: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: Dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def evaluate_arithmetic(
    expression: str,
    *,
    max_length: int = 256,
    max_nodes: int = 80,
    max_depth: int = 20,
    max_abs: float = 1e100,
    max_power: int = 1000,
) -> Any:
    """Evaluate numbers, parentheses, and ordinary arithmetic operators only."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("an arithmetic expression is required")
    if len(expression) > max_length:
        raise ExpressionError("expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ExpressionError("invalid arithmetic expression") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > max_nodes:
        raise ExpressionError("expression is too complex")

    def checked(value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ExpressionError("only real numbers are supported")
        if isinstance(value, int) and value.bit_length() > 1024:
            raise ExpressionError("integer result is too large")
        if isinstance(value, float) and not math.isfinite(value):
            raise ExpressionError("result is not finite")
        if abs(value) > max_abs:
            raise ExpressionError("result is too large")
        return value

    def visit(node: ast.AST, depth: int = 0) -> Any:
        if depth > max_depth:
            raise ExpressionError("expression is too deeply nested")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise ExpressionError("only real numbers are supported")
            return checked(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return checked(_UNARY[type(node.op)](visit(node.operand, depth + 1)))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left = visit(node.left, depth + 1)
            right = visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow):
                if abs(right) > max_power:
                    raise ExpressionError("exponent is too large")
                if left == 0 and right < 0:
                    raise ExpressionError("division by zero")
            try:
                return checked(_BINARY[type(node.op)](left, right))
            except (ArithmeticError, OverflowError) as exc:
                raise ExpressionError("arithmetic operation failed") from exc
        raise ExpressionError(
            "only numbers, parentheses, and + - * / // % ** are allowed"
        )

    return visit(tree)
