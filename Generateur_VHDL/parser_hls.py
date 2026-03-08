import json
import re

class Operation:
    def __init__(self, op_type, operator_id, dest, src1, src2, cycle):
        self.op_type = op_type
        self.operator_id = operator_id
        self.dest = dest
        self.src1 = src1
        self.src2 = src2
        self.cycle = cycle

def sanitize_name(name):
    if name is None:
        return None
    name = name.replace('.', '_').replace('-', '_')
    # Supprimer les doubles underscores
    while '__' in name:
        name = name.replace('__', '_')
    return name

# Opérateurs à ignorer
IGNORED_OPERATORS = {"no_resource", "add_f_0", "mul_f_0"}

# Types d'opérations à ignorer
IGNORED_OP_TYPES = {"func.return", "const:i32", "const:f32"}

def parse_schedule_json(json_data):
    ops_list = []
    all_operator_ids = set()
    max_iteration = 0
    has_iterations = False

    # Première passe : collecter toutes les ops avec leur iteration
    all_ops_raw = []

    for cycle_str, operators in json_data.items():
        cycle_match = re.search(r'\d+', cycle_str)
        if not cycle_match:
            continue
        cycle_num = int(cycle_match.group())

        for operator_id, details in operators.items():
            if operator_id.lower() in IGNORED_OPERATORS:
                continue

            all_operator_ids.add(operator_id)

            if not details:
                continue

            operation_field = details.get("operation", "")
            if any(op in operation_field for op in IGNORED_OP_TYPES):
                continue

            op_type = "ADD" if "add" in operator_id.lower() else "MUL"
            formatted_operator_id = operator_id.upper()

            output_list = details.get("output", details.get("outputs", [None]))
            dest = sanitize_name(output_list[0] if output_list else None)

            inputs = details.get("inputs", [])
            src1 = sanitize_name(inputs[0] if len(inputs) > 0 else None)
            src2 = sanitize_name(inputs[1] if len(inputs) > 1 else None)

            if dest is None:
                continue

            iteration = details.get("iteration", 0)
            if iteration > 0:
                has_iterations = True
            max_iteration = max(max_iteration, iteration)

            all_ops_raw.append({
                "op_type": op_type,
                "operator_id": formatted_operator_id,
                "dest": dest,
                "src1": src1,
                "src2": src2,
                "cycle": cycle_num,
                "iteration": iteration
            })

    nb_iterations = max_iteration + 1 if has_iterations else 1

    if has_iterations:
        # Garder uniquement les ops de l'iteration 0
        # Remap les cycles : cycle_within_iteration = cycle % cycles_per_iteration
        iter0_ops = [op for op in all_ops_raw if op["iteration"] == 0]
        cycles_iter0 = sorted(set(op["cycle"] for op in iter0_ops))
        cycles_per_iteration = len(cycles_iter0)

        # Remap cycle → index dans l'iteration
        cycle_to_idx = {c: i for i, c in enumerate(cycles_iter0)}

        for op in iter0_ops:
            op_obj = Operation(
                op["op_type"], op["operator_id"], op["dest"],
                op["src1"], op["src2"], cycle_to_idx[op["cycle"]]
            )
            ops_list.append(op_obj)
    else:
        cycles_per_iteration = len(set(op["cycle"] for op in all_ops_raw))
        for op in all_ops_raw:
            op_obj = Operation(
                op["op_type"], op["operator_id"], op["dest"],
                op["src1"], op["src2"], op["cycle"]
            )
            ops_list.append(op_obj)

    add_ids = sorted(set(op_id for op_id in all_operator_ids if "add" in op_id.lower()))
    mul_ids = sorted(set(op_id for op_id in all_operator_ids if "mul" in op_id.lower()))

    return ops_list, add_ids, mul_ids, nb_iterations