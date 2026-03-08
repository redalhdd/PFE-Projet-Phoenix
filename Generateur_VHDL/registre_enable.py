from myhdl import block, always_seq, Signal, intbv, ResetSignal

@block
def registre_enable(clk, rst, sortie, entree, enable):
    """
    Registre avec enable et reset synchrone.
    clk    : signal d'horloge
    rst    : ResetSignal
    sortie : signal de sortie
    entree : signal d'entrée
    enable : signal d'activation (écrit uniquement si enable=1)
    """
    @always_seq(clk.posedge, reset=rst)
    def logic():
        if enable:
            sortie.next = entree

    return logic
