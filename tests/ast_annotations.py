"""What a source sweep passes as an annotation, shared by the sweeps of
src/'s spawns (`test_headless.py`, `test_subprocess_sweep.py`), which
must agree on it."""
import ast


def annotation_names(tree: ast.AST) -> set[int]:
    """The ids of the names that spell `tree`'s annotations (`->
    subprocess.Popen[bytes]`), which a sweep of spawns passes.
    Evaluating one names a type and starts nothing, since a spawn needs
    a call: the set follows an annotation only through what spells a
    type (attributes, subscripts, `|`, the lists `Callable` takes),
    never into a call, so a call in an annotation, which runs when its
    function is defined, is read as it would be anywhere else."""
    pending: list[ast.AST | None] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pending.append(node.returns)
        elif isinstance(node, (ast.arg, ast.AnnAssign)):
            pending.append(node.annotation)
    named: set[int] = set()
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Attribute, ast.Name)):
            named.add(id(node))
        if isinstance(node, (ast.Attribute, ast.Subscript, ast.Tuple, ast.List)) or (
                isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
        ):
            pending.extend(ast.iter_child_nodes(node))
    return named
