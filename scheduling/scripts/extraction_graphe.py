import sys
import re
import json
from llvmlite import binding

j_son_file_output = "dag_block_OptiBlock.json"


def parse_block_names(ir_code):
    block_order = []
    in_func     = False
    for raw in ir_code.splitlines():
        stripped = raw.strip()
        if re.match(r'define\b', stripped):
            in_func = True
            continue
        if not in_func: continue
        if stripped == '}':
            in_func = False
            continue
        if raw and raw[0] not in (' ', '\t'):
            m = re.match(r'^(\w+)\s*:', raw)
            if m:
                block_order.append(m.group(1))
    return block_order


def extract_val(token):
    parts = token.strip().split()
    return parts[-1] if parts else token


def analyze_llvm(ir_code):
    block_order = parse_block_names(ir_code)
    #print(f"Blocs détectés : {block_order}")

    try:
        module = binding.parse_assembly(ir_code)
    except Exception as e:
        print(f"Erreur llvmlite : {e}"); return

    # PRE-PASS : attribuer un ID à chaque instruction réelle (hors alloca, br)
    id_op       = 0
    instr_to_id = {}
    for func in module.functions:
        if func.is_declaration: continue
        for block in func.blocks:
            for instr in block.instructions:
                if instr.opcode not in ["alloca", "br"]:
                    instr_to_id[instr] = id_op
                    id_op += 1

    # Mapper blocs llvmlite -> noms textuels
    block_name_map = {}
    for func in module.functions:
        if func.is_declaration: continue
        ll_blocks = list(func.blocks)
        block_name_map[ll_blocks[0]] = None
        for i, block in enumerate(ll_blocks[1:]):
            block_name_map[block] = block_order[i] if i < len(block_order) else f"b{i}"

    # min_id par bloc
    block_min_id = {}
    for func in module.functions:
        if func.is_declaration: continue
        for block in func.blocks:
            b = block_name_map.get(block)
            if b is None: continue
            ids = [instr_to_id[i] for i in block.instructions if i in instr_to_id]
            if ids:
                block_min_id[b] = min(ids)

    nodes        = []
    control_flow = []
    seen_const   = {}

    def get_const(val, bloc):
        nonlocal id_op
        key = (bloc, val)
        if key not in seen_const:
            const_id = f"c_{id_op}"
            seen_const[key] = const_id
            nodes.append({"id": const_id,
                        "mnemonic": f"const:i32 {val}",
                        "preds": [], "block": bloc})
            id_op += 1
        return seen_const[key]

    for func in module.functions:
        if func.is_declaration: continue

        for block in func.blocks:
            b_name = block_name_map.get(block)
            if b_name is None:
                continue

            current_min = block_min_id.get(b_name, 0)

            for instr in block.instructions:
                opcode       = instr.opcode
                predecessors = []
                loop_preds   = []

                # ── ARITHMETIQUE & ICMP ────────────────────────────────────
                if opcode in ["add", "mul", "sub", "icmp"]:
                    sym = {'add': '+', 'sub': '-',
                        'mul': '*', 'icmp': '<'}.get(opcode, opcode)
                    op_labels = []

                    for op in instr.operands:
                        if op in instr_to_id:
                            node_id = instr_to_id[op]
                            # ← CORRECTION : préfixer "id" pour distinguer
                            #   les références de nœuds des valeurs constantes
                            label = op.name if op.name else str(node_id)
                            # Si le label est purement numérique, préfixer "id"
                            # pour éviter la confusion avec une constante littérale
                            if re.fullmatch(r'\d+', label):
                                label = f"id{label}"
                            op_labels.append(label)
                            predecessors.append(node_id)
                        else:
                            val = extract_val(str(op))
                            op_labels.append(val)
                            predecessors.append(get_const(val, b_name))

                    op_type  = "icmpi" if opcode == "icmp" else f"{opcode}i"
                    mnemonic = f"arith.{op_type} ({op_labels[0]} {sym} {op_labels[1]})"
                    nodes.append({"id": instr_to_id[instr],
                                "mnemonic": mnemonic,
                                "preds": predecessors,
                                "block": b_name})

                # ── PHI ────────────────────────────────────────────────────
                elif opcode == "phi":
                    phi_name = instr.name

                    for op in instr.operands:
                        if op in instr_to_id:
                            val_id = instr_to_id[op]
                            if val_id > current_min:
                                loop_preds.append(val_id)
                            else:
                                predecessors.append(val_id)
                        elif "i32" in str(op) and not str(op).startswith('%'):
                            val      = extract_val(str(op))
                            const_id = get_const(val + "_phi_" + phi_name, "0")
                            for n in nodes:
                                if n['id'] == const_id:
                                    n['mnemonic'] = f"const:i32 {val}"
                            if const_id not in predecessors:
                                predecessors.append(const_id)

                    phi_node = {"id": instr_to_id[instr],
                                "mnemonic": f"phi:{phi_name}",
                                "preds": predecessors,
                                "block": b_name}
                    if loop_preds:
                        phi_node["loop_preds"] = loop_preds
                    nodes.append(phi_node)

                # ── BRANCHEMENT ────────────────────────────────────────────
                elif opcode == "br":
                    clean = re.sub(r',?\s*![\w.]+\s*![0-9]+', '', str(instr)).strip()

                    # Trouver les IDs de toutes les instrs du bloc
                    bloc_ids = set()
                    for prev_instr in block.instructions:
                        if prev_instr is instr:
                            break
                        if prev_instr in instr_to_id:
                            bloc_ids.add(instr_to_id[prev_instr])

                    # Trouver ceux qui sont référencés comme prédécesseurs par d'autres du même bloc
                    referenced = set()
                    for prev_instr in block.instructions:
                        if prev_instr is instr:
                            break
                        if prev_instr in instr_to_id:
                            for op in prev_instr.operands:
                                if op in instr_to_id and instr_to_id[op] in bloc_ids:
                                    referenced.add(instr_to_id[op])

                    # Les feuilles = ids du bloc qui ne sont pas référencés par d'autres
                    # On exclut les constantes (ids de type string commençant par "c_")
                    leaves = [i for i in (bloc_ids - referenced)
                            if not str(i).startswith('c_')]

                    m = re.search(
                        r'br i1\s+%\S+,\s*label\s+%(\S+),\s*label\s+%(\S+)', clean)
                    if m:
                        control_flow.append({"from": b_name,
                                            "to": m.group(1).rstrip(','),
                                            "label": "True"})
                        control_flow.append({"from": b_name,
                                            "to": m.group(2).rstrip(','),
                                            "label": "False"})
                    else:
                        m = re.search(r'br\s+label\s+%(\S+)', clean)
                        if m:
                            target = m.group(1).rstrip(',')
                            tmin   = block_min_id.get(target, float('inf'))
                            label  = "loop_back" if tmin < current_min else "seq"

                            br_id = f"br_{b_name}"
                            nodes.append({"id": br_id,
                                        "mnemonic": f"br.{label}",
                                        "preds": leaves,
                                        "block": b_name})

                            control_flow.append({"from": b_name,
                                                "to": target,
                                                "label": label})

                # ── RETURN ─────────────────────────────────────────────────
                elif opcode == "ret":
                    ops = list(instr.operands)
                    if ops and ops[0] in instr_to_id:
                        predecessors.append(instr_to_id[ops[0]])
                    nodes.append({"id": instr_to_id[instr],
                                "mnemonic": "func.return",
                                "preds": predecessors,
                                "block": b_name})

    # with open(j_son_file_output, 'w') as f:
    #     json.dump({"nodes": nodes, "edges": control_flow}, f, indent=2)
    #     print(f"JSON écrit dans {j_son_file_output}")
    json.dump({"nodes": nodes, "edges": control_flow}, sys.stdout, indent=2)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            analyze_llvm(f.read())