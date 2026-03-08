from myhdl import block, always_comb

@block
def multiplicateur(a, b, s):

    @always_comb
    def comb():
        s.next = a*b  
    
    return comb