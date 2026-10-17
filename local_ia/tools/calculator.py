"""Calculatrice arithmétique sûre pour les appels d'outils de l'agent."""

from __future__ import annotations

import ast
import math
import operator
import re


MAX_EXPRESSION_LENGTH = 256
MAX_AST_NODES = 64
MAX_EXPONENT = 1024
MAX_INTEGER_BITS = 4096

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "radians": math.radians,
    "degrees": math.degrees,
}


def _validate_result(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Le résultat doit être un nombre réel.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Le résultat est trop grand ou n'est pas un nombre fini.")
    if isinstance(value, int) and value.bit_length() > MAX_INTEGER_BITS:
        raise ValueError("Le résultat entier est trop grand.")
    return value


def _evaluate(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Seuls les nombres sont autorisés dans l'expression.")
        return _validate_result(node.value)

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT:
                raise ValueError(f"L'exposant ne peut pas dépasser {MAX_EXPONENT}.")
            if isinstance(left, int) and isinstance(right, int) and abs(left) > 1:
                if left.bit_length() * max(0, right) > MAX_INTEGER_BITS:
                    raise ValueError("Le résultat entier serait trop grand.")
        try:
            result = _BINARY_OPERATORS[type(node.op)](left, right)
        except (ArithmeticError, OverflowError, ValueError) as error:
            raise ValueError(f"Calcul impossible : {error}") from error
        return _validate_result(result)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _validate_result(_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand)))

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError("Cette fonction n'est pas autorisée.")
        arguments = [_evaluate(argument) for argument in node.args]
        try:
            return _validate_result(function(*arguments))
        except (ArithmeticError, OverflowError, TypeError, ValueError) as error:
            raise ValueError(f"Calcul impossible : {error}") from error

    raise ValueError("Expression non prise en charge. Utilise des nombres, opérateurs et fonctions autorisés.")


def calculate(expression: str):
    """Evaluate arithmetic without executing arbitrary Python code."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("L'expression de calcul est vide.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("L'expression de calcul est trop longue.")

    normalized = expression.strip()
    normalized = normalized.replace("×", "*").replace("÷", "/").replace("−", "-")
    normalized = re.sub(r"(?<=\d),(?=\d)", ".", normalized)
    normalized = re.sub(r"(?<!\*)\^(?!\*)", "**", normalized)
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise ValueError("Expression de calcul invalide.") from error
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("L'expression de calcul est trop complexe.")
    return _evaluate(tree.body)


def use(expression: str) -> dict:
    """Tool entry point used by ToolManager."""
    return {"expression": expression, "result": calculate(expression)}