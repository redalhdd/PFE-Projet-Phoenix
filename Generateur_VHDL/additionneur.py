from myhdl import block, always_comb

@block
def additionneur(a, b, s):

    @always_comb
    def comb():
        s.next = a+b  
    
    return comb