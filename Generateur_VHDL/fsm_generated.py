from myhdl import block, always_seq, always_comb, Signal, enum, intbv

def make_generated_fsm(t_state, nb_iterations):
    @block
    def fsm(clk, reset, state, iter_count, done):
        @always_seq(clk.posedge, reset=reset)
        def logic():
            if done == 1:
                pass
            elif state == t_state.STATE_0:
                state.next = t_state.STATE_1
            elif state == t_state.STATE_1:
                state.next = t_state.STATE_2
            elif state == t_state.STATE_2:
                state.next = t_state.STATE_3
            elif state == t_state.STATE_3:
                if iter_count == nb_iterations - 1:
                    done.next = 1
                else:
                    iter_count.next = iter_count + 1
                    state.next = t_state.STATE_0
        return logic
    return fsm

def make_generated_enable_gen():
    @block
    def enable_gen(state, target_state, enable, done):
        @always_comb
        def logic():
            if done == 0 and state == target_state:
                enable.next = 1
            else:
                enable.next = 0
        return logic
    return enable_gen

def make_generated_cycle_sel_gen(t_state):
    @block
    def cycle_sel_gen(state, cycle_sel):
        @always_comb
        def logic():
            if state == t_state.STATE_0:
                cycle_sel.next = 0
            elif state == t_state.STATE_1:
                cycle_sel.next = 1
            elif state == t_state.STATE_2:
                cycle_sel.next = 2
            elif state == t_state.STATE_3:
                cycle_sel.next = 3
        return logic
    return cycle_sel_gen