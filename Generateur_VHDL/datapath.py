from myhdl import block, Signal, intbv, ResetSignal
from additionneur import additionneur
from multiplicateur import multiplicateur
from registre_enable import registre_enable
from mux import mux2, mux4, mux8
from fsm import make_fsm
from parser_hls import parse_schedule_json
import json
import sys

class Operation:
    def __init__(self, op_type, operator_id, dest, src1, src2, cycle):
        self.op_type = op_type
        self.operator_id = operator_id
        self.dest = dest
        self.src1 = src1
        self.src2 = src2
        self.cycle = cycle

class ExternalInputs:
    def __init__(self, signal_names):
        for name in sorted(signal_names):
            setattr(self, name, Signal(intbv(0)[16:]))

class ExternalOutputs:
    def __init__(self, signal_names):
        for name in sorted(signal_names):
            setattr(self, name, Signal(intbv(0)[16:]))

class InternalSignals:
    def __init__(self, signal_names):
        for name in sorted(signal_names):
            setattr(self, name, Signal(intbv(0)[16:]))

def get_external_signals(ops):
    all_dests = {op.dest for op in ops}
    all_sources = {op.src1 for op in ops if op.src1} | {op.src2 for op in ops if op.src2}
    return all_sources - all_dests

def get_output_signals(ops):
    all_dests = {op.dest for op in ops}
    all_sources = {op.src1 for op in ops if op.src1} | {op.src2 for op in ops if op.src2}
    return all_dests - all_sources

def pick_mux(nb):
    if nb <= 2: return mux2
    if nb <= 4: return mux4
    return mux8

# ---------- PARSING ----------
schedule_file = sys.argv[1]
with open(schedule_file, "r") as f:
    data = json.load(f)

ops, add_ids, mul_ids, nb_iterations = parse_schedule_json(data)

print("Opérations chargées depuis schedule.json :")
for op in ops:
    print(f"  {op.op_type} [{op.operator_id}] {op.dest} = {op.src1}, {op.src2} (cycle {op.cycle})")
print()

add_ids_active = sorted(set(op.operator_id for op in ops if op.op_type == "ADD"))
mul_ids_active = sorted(set(op.operator_id for op in ops if op.op_type == "MUL"))
NB_ADD = len(add_ids_active)
NB_MUL = len(mul_ids_active)
print(f"Opérateurs ADD actifs : {add_ids_active} → NB_ADD={NB_ADD}")
print(f"Opérateurs MUL actifs : {mul_ids_active} → NB_MUL={NB_MUL}")
print(f"Nombre d'itérations   : {nb_iterations}")
print()

external_names = get_external_signals(ops)
output_names   = get_output_signals(ops)
internal_names = {op.dest for op in ops} - output_names

print(f"Signaux externes (in)  : {sorted(external_names)}")
print(f"Signaux externes (out) : {sorted(output_names)}")
print(f"Signaux internes       : {sorted(internal_names)}")

ext = ExternalInputs(external_names)
out = ExternalOutputs(output_names)

t_state, fsm_block, enable_gen, cycle_sel_gen, op_active_state, nb_cycles = make_fsm(ops, nb_iterations)

@block
def Datapath(clk, reset, ext, out):

    internal  = InternalSignals(internal_names)

    def resolve_src(name):
        if hasattr(internal, name):
            return getattr(internal, name)
        if hasattr(ext, name):
            return getattr(ext, name)
        return None

    def resolve_dest(name):
        if hasattr(out, name):
            return getattr(out, name)
        return getattr(internal, name)

    add_in1 = [Signal(intbv(0)[16:]) for _ in add_ids_active]
    add_in2 = [Signal(intbv(0)[16:]) for _ in add_ids_active]
    add_out = [Signal(intbv(0)[16:]) for _ in add_ids_active]
    mul_in1 = [Signal(intbv(0)[16:]) for _ in mul_ids_active]
    mul_in2 = [Signal(intbv(0)[16:]) for _ in mul_ids_active]
    mul_out = [Signal(intbv(0)[16:]) for _ in mul_ids_active]
    zero    = Signal(intbv(0)[16:])

    state      = Signal(t_state.STATE_0)
    cycle_sel  = Signal(intbv(0, min=0, max=nb_cycles))
    iter_count = Signal(intbv(0, min=0, max=nb_iterations))
    done       = Signal(bool(0))
    enables    = [Signal(bool(0)) for _ in ops]

    insts = []

    # FSM avec compteur d'itérations
    insts.append(fsm_block(clk, reset, state, iter_count, done))

    # Cycle sel
    insts.append(cycle_sel_gen(state, cycle_sel))

    # Enables
    for i, op in enumerate(ops):
        insts.append(enable_gen(state, op_active_state[i], enables[i], done))

    # Pour chaque opérateur ADD actif
    for i, op_id in enumerate(add_ids_active):
        assigned = sorted([op for op in ops if op.operator_id == op_id], key=lambda o: o.cycle)
        # Indexer par cycle (0..nb_cycles-1), zero si opérateur inactif ce cycle
        cycle_to_op = {op.cycle: op for op in assigned}
        s1 = [resolve_src(cycle_to_op[c].src1) if c in cycle_to_op else zero for c in range(nb_cycles)]
        s2 = [resolve_src(cycle_to_op[c].src2) if c in cycle_to_op else zero for c in range(nb_cycles)]
        mux_fn = pick_mux(nb_cycles)

        insts.append(additionneur(add_in1[i], add_in2[i], add_out[i]))

        if nb_cycles == 1:
            from myhdl import always_comb
            s1_sig = s1[0]
            s2_sig = s2[0]
            @block
            def connect_add(in1, in2, src1, src2):
                @always_comb
                def logic():
                    in1.next = src1
                    in2.next = src2
                return logic
            insts.append(connect_add(add_in1[i], add_in2[i], s1_sig, s2_sig))
        elif nb_cycles == 2:
            insts.append(mux_fn(add_in1[i], s1[0], s1[1], cycle_sel))
            insts.append(mux_fn(add_in2[i], s2[0], s2[1], cycle_sel))
        elif nb_cycles == 3:
            insts.append(mux_fn(add_in1[i], s1[0], s1[1], s1[2], zero, cycle_sel))
            insts.append(mux_fn(add_in2[i], s2[0], s2[1], s2[2], zero, cycle_sel))
        elif nb_cycles == 4:
            insts.append(mux_fn(add_in1[i], s1[0], s1[1], s1[2], s1[3], cycle_sel))
            insts.append(mux_fn(add_in2[i], s2[0], s2[1], s2[2], s2[3], cycle_sel))

        for op in assigned:
            op_idx = ops.index(op)
            insts.append(registre_enable(clk, reset, resolve_dest(op.dest), add_out[i], enables[op_idx]))

    # Pour chaque opérateur MUL actif
    for i, op_id in enumerate(mul_ids_active):
        assigned = sorted([op for op in ops if op.operator_id == op_id], key=lambda o: o.cycle)
        # Indexer par cycle (0..nb_cycles-1), zero si opérateur inactif ce cycle
        cycle_to_op = {op.cycle: op for op in assigned}
        s1 = [resolve_src(cycle_to_op[c].src1) if c in cycle_to_op else zero for c in range(nb_cycles)]
        s2 = [resolve_src(cycle_to_op[c].src2) if c in cycle_to_op else zero for c in range(nb_cycles)]
        mux_fn = pick_mux(nb_cycles)

        insts.append(multiplicateur(mul_in1[i], mul_in2[i], mul_out[i]))

        if nb_cycles == 1:
            from myhdl import always_comb
            s1_sig = s1[0]
            s2_sig = s2[0]
            @block
            def connect_mul(in1, in2, src1, src2):
                @always_comb
                def logic():
                    in1.next = src1
                    in2.next = src2
                return logic
            insts.append(connect_mul(mul_in1[i], mul_in2[i], s1_sig, s2_sig))
        elif nb_cycles == 2:
            insts.append(mux_fn(mul_in1[i], s1[0], s1[1], cycle_sel))
            insts.append(mux_fn(mul_in2[i], s2[0], s2[1], cycle_sel))
        elif nb_cycles == 3:
            insts.append(mux_fn(mul_in1[i], s1[0], s1[1], s1[2], zero, cycle_sel))
            insts.append(mux_fn(mul_in2[i], s2[0], s2[1], s2[2], zero, cycle_sel))
        elif nb_cycles == 4:
            insts.append(mux_fn(mul_in1[i], s1[0], s1[1], s1[2], s1[3], cycle_sel))
            insts.append(mux_fn(mul_in2[i], s2[0], s2[1], s2[2], s2[3], cycle_sel))

        for op in assigned:
            op_idx = ops.index(op)
            insts.append(registre_enable(clk, reset, resolve_dest(op.dest), mul_out[i], enables[op_idx]))

    return tuple(insts)


clk = Signal(bool(0))
reset = ResetSignal(0, active=1, isasync=False)
top_level = Datapath(clk, reset, ext, out)

top_level.convert(hdl='VHDL')
print("Conversion terminée avec succès !")