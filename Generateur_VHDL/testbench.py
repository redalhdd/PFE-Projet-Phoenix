import sys
import os

# Récupérer le chemin du JSON depuis les arguments
if len(sys.argv) < 2:
    print("Usage: python3 testbench.py <schedule.json>")
    sys.exit(1)

schedule_path = sys.argv[1]

# Passer le chemin à datapath via sys.argv avant l'import
sys.argv = [sys.argv[0], schedule_path]

from myhdl import block, Signal, intbv, ResetSignal, delay, instance, StopSimulation
from datapath import Datapath, ext, out

PERIOD = 10  # ns
NB_FSM_CYCLES  = 4
NB_ITERATIONS  = 4
NB_WAIT_CYCLES = NB_FSM_CYCLES * NB_ITERATIONS + 10

@block
def testbench():
    clk   = Signal(bool(0))
    reset = ResetSignal(0, active=1, isasync=False)

    dut = Datapath(clk, reset, ext, out)

    @instance
    def clk_gen():
        while True:
            clk.next = not clk
            yield delay(PERIOD // 2)

    @instance
    def stimulus():
        # Assigner les entrées AVANT le reset
        ext.phi_0_1.next          = intbv(1)[16:]
        ext.phi_01_0.next         = intbv(0)[16:]
        ext.const_i32_5_c_13.next = intbv(5)[16:]
        ext.const_i32_1_c_15.next = intbv(1)[16:]
        ext.const_i32_2_c_14.next = intbv(2)[16:]

        # Reset
        reset.next = 1
        yield delay(PERIOD * 2)
        reset.next = 0

        # Attendre la fin des itérations
        for _ in range(NB_WAIT_CYCLES):
            yield clk.posedge

        # Vérification
        print("=== Résultats (itération 0 : i=1, acc=0) ===")
        print(f"  out_arith_addi_0_1_8     = {int(out.arith_addi_0_1_8)} (attendu 2  → i+1)")
        print(f"  out_arith_muli_id4_id6_7 = {int(out.arith_muli_id4_id6_7)} (attendu 35 → acc après itération 1)")

        ok_add = int(out.arith_addi_0_1_8) == 2
        ok_mul = int(out.arith_muli_id4_id6_7) == 35

        if ok_add and ok_mul:
            print("\n✓ Tous les résultats sont corrects !")
        else:
            print("\n✗ Des erreurs ont été détectées.")

        raise StopSimulation

    return dut, clk_gen, stimulus

tb = testbench()
tb.config_sim(trace=True)
tb.run_sim()
tb.quit_sim()
print("Simulation terminée — fichier VCD généré : testbench.vcd")