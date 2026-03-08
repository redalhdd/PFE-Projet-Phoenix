from myhdl import block, always_comb

@block
def soustracteur(s, a, b):

    @always_comb
    def comb():
        s.next = a - b  
    
    return comb