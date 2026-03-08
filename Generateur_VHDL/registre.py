# registre.py
from myhdl import block, always_seq, Signal, intbv, ResetSignal

@block
def registre(clk, rst, sortie, entree):
    """
    Registre simple avec reset
    clk: Signal d'horloge
    rst: ResetSignal (IMPORTANT!)
    sortie: Signal de sortie
    entree: Signal d'entrée
    """
    @always_seq(clk.posedge, reset=rst)
    def logic():
        sortie.next = entree
    
    return logic