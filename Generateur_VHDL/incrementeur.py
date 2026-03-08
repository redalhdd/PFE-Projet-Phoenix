from myhdl import block, always_comb, Signal, always_seq

@block
def incrementeur(s, clk, reset):
    @always_seq(clk.posedge, reset=reset)
    def seq():
        s.next = s + 1  
    return seq