from myhdl import block, always_seq, always_comb, Signal, enum, intbv
import importlib.util
import sys
import os

def make_fsm(ops, nb_iterations=1):
    cycles = sorted(set(op.cycle for op in ops))
    nb_cycles = len(cycles)
    has_loop = nb_iterations > 1

    state_names = tuple(f'STATE_{c}' for c in cycles)
    t_state = enum(*state_names, encoding='one_hot')

    op_active_state = [getattr(t_state, f'STATE_{op.cycle}') for op in ops]

    lines = []
    lines.append("from myhdl import block, always_seq, always_comb, Signal, enum, intbv")
    lines.append("")

    # FSM avec compteur d'itérations
    lines.append("def make_generated_fsm(t_state, nb_iterations):")
    lines.append("    @block")
    lines.append("    def fsm(clk, reset, state, iter_count, done):")
    lines.append("        @always_seq(clk.posedge, reset=reset)")
    lines.append("        def logic():")
    lines.append("            if done == 1:")
    lines.append("                pass")

    last_cycle = cycles[-1]
    for i, cycle in enumerate(cycles):
        next_cycle = cycles[(i + 1) % nb_cycles]
        keyword = "elif"
        lines.append(f"            {keyword} state == t_state.STATE_{cycle}:")
        if cycle == last_cycle:
            # Dernier état : incrémenter compteur ou terminer
            lines.append(f"                if iter_count == nb_iterations - 1:")
            lines.append(f"                    done.next = 1")
            lines.append(f"                else:")
            lines.append(f"                    iter_count.next = iter_count + 1")
            lines.append(f"                    state.next = t_state.STATE_{cycles[0]}")
        else:
            lines.append(f"                state.next = t_state.STATE_{next_cycle}")
    lines.append("        return logic")
    lines.append("    return fsm")
    lines.append("")

    # Enable gen
    lines.append("def make_generated_enable_gen():")
    lines.append("    @block")
    lines.append("    def enable_gen(state, target_state, enable, done):")
    lines.append("        @always_comb")
    lines.append("        def logic():")
    lines.append("            if done == 0 and state == target_state:")
    lines.append("                enable.next = 1")
    lines.append("            else:")
    lines.append("                enable.next = 0")
    lines.append("        return logic")
    lines.append("    return enable_gen")
    lines.append("")

    # Cycle sel gen
    lines.append("def make_generated_cycle_sel_gen(t_state):")
    lines.append("    @block")
    lines.append("    def cycle_sel_gen(state, cycle_sel):")
    lines.append("        @always_comb")
    lines.append("        def logic():")
    for i, cycle in enumerate(cycles):
        keyword = "if" if i == 0 else "elif"
        lines.append(f"            {keyword} state == t_state.STATE_{cycle}:")
        lines.append(f"                cycle_sel.next = {i}")
    lines.append("        return logic")
    lines.append("    return cycle_sel_gen")

    fsm_code = "\n".join(lines)
    print("=== FSM générée ===")
    print(fsm_code)
    print("===================\n")

    fsm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fsm_generated.py')
    with open(fsm_path, 'w') as f:
        f.write(fsm_code)

    if 'fsm_generated' in sys.modules:
        del sys.modules['fsm_generated']
    spec = importlib.util.spec_from_file_location('fsm_generated', fsm_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fsm_block        = mod.make_generated_fsm(t_state, nb_iterations)
    enable_gen       = mod.make_generated_enable_gen()
    cycle_sel_gen    = mod.make_generated_cycle_sel_gen(t_state)

    return t_state, fsm_block, enable_gen, cycle_sel_gen, op_active_state, nb_cycles