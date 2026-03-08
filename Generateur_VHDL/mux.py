from myhdl import block, always_comb, Signal

@block
def mux2(z, a, b, sel):
    """ Multiplexer.
    z -- mux output
    a, b -- data inputs
    sel -- control input: select a if asserted, otherwise b
    """
    @always_comb
    def comb():
        if sel == 1:
            z.next = a
        else:
            z.next = b
    
    return comb

@block
def mux4(z, a0, a1, a2, a3, sel):
    """ 4-to-1 Multiplexer.
    z -- mux output
    a0, a1, a2, a3 -- data inputs
    sel -- control input: select one of the four data inputs
    """
    @always_comb
    def comb():
        if sel == 0:
            z.next = a0
        elif sel == 1:
            z.next = a1
        elif sel == 2:
            z.next = a2
        else:
            z.next = a3
    
    return comb

@block
def mux8(z, a0, a1, a2, a3, a4, a5, a6, a7, sel):
    """ 8-to-1 Multiplexer.
    z -- mux output
    a0, a1, a2, a3, a4, a5, a6, a7 -- data inputs
    sel -- control input: select one of the eight data inputs
    """
    @always_comb
    def comb():
        if sel == 0:
            z.next = a0
        elif sel == 1:
            z.next = a1
        elif sel == 2:
            z.next = a2
        elif sel == 3:
            z.next = a3
        elif sel == 4:
            z.next = a4
        elif sel == 5:
            z.next = a5
        elif sel == 6:
            z.next = a6
        else:
            z.next = a7
    
    return comb
    