from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple
import sys, json, math, re, os

# ═════════════════════════════════════════════════════════════════════════════
# Structures de données
# ═════════════════════════════════════════════════════════════════════════════

class Node:
    def __init__(self, idx: str, mnemonic: str,
                 preds: List[str], loop_preds: List[str], block: str):
        self.idx       = idx
        self.mnemonic  = mnemonic
        self.preds     = preds        # dépendances intra-itération
        self.loop_preds = loop_preds  # dépendances inter-itération (back-edges)
        self.block     = block

    def __repr__(self):
        return f"Node({self.idx}, {self.mnemonic!r})"


class TimingInfo:
    def __init__(self, t_su: float, L: int, t_co: float):
        self.t_su = t_su   # setup time
        self.L    = L      # latency (cycles)
        self.t_co = t_co   # clock-to-output

    def as_tuple(self) -> Tuple[float, int, float]:
        return (self.t_su, self.L, self.t_co)


class ScheduleEntry:
    """Un cycle dans le ScheduleTable."""
    def __init__(self, cycle: int):
        self.cycle = cycle
        # (op_label, cycle, offset_ns, TimingInfo, operator_key | None, iteration)
        self.entry: List[Tuple] = []

    def add_op(self, op: str, offset: float, duration: TimingInfo,
               operator: Optional[str], iteration: int):
        self.entry.append((op, self.cycle, offset, duration, operator, iteration))


class ScheduleTable:
    def __init__(self, t_clk: float):
        self.t_clk = t_clk
        self.table: List[ScheduleEntry] = []

    def _ensure(self, cycle: int):
        while len(self.table) <= cycle:
            self.table.append(ScheduleEntry(len(self.table)))

    def schedule_at(self, op: str, cycle: int, offset: float,
                    duration: TimingInfo, operator: Optional[str],
                    iteration: int = -1):
        self._ensure(cycle)
        self.table[cycle].add_op(op, offset, duration, operator, iteration)

    def print_table(self):
        print("=== Schedule complet ===")
        for ce in self.table:
            if not ce.entry:
                continue
            print(f"  Cycle {ce.cycle}:")
            for op, _, off, dur, inst, it in ce.entry:
                it_str = f"iter={it}" if it >= 0 else "static"
                print(f"    {op:50s}  {it_str}  inst={inst}  off={off:.1f}  lat={dur.L}")


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def op_base(mnemonic: str) -> str:
    return mnemonic.split('(')[0].strip()

def is_trivial(node: Node) -> bool:
    b = op_base(node.mnemonic).lower()
    return any(k in b for k in ("const", "phi", "icmp", "br"))

def is_return(node: Node) -> bool:
    return "return" in node.mnemonic.lower()

def get_timing(node: Node, timings: Dict[str, TimingInfo]) -> TimingInfo:
    if is_trivial(node):
        return TimingInfo(0, 0, 0)
    base = op_base(node.mnemonic)
    if base in timings:
        return timings[base]
    for k, v in timings.items():
        if k in base:
            return v
    return TimingInfo(0, 0, 0)

def get_resource(node: Node, op_to_resource: Dict[str, str]) -> Optional[str]:
    if is_trivial(node):
        return None
    base = op_base(node.mnemonic)
    if base in op_to_resource:
        return op_to_resource[base]
    for k, v in op_to_resource.items():
        if k in base:
            return v
    return None


# ═════════════════════════════════════════════════════════════════════════════
# I/O
# ═════════════════════════════════════════════════════════════════════════════

def read_dag(filename: str) -> Tuple[List[Node], List[dict], int]:
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)
    nodes = [
        Node(
            idx      = str(item["id"]),
            mnemonic = item["mnemonic"],
            preds    = [str(p) for p in item.get("preds", [])],
            loop_preds = [str(p) for p in item.get("loop_preds", [])],
            block    = str(item.get("block", "?")),
        )
        for item in data.get("nodes", [])
    ]
    trip_count = int(data.get("trip_count", 0))  # 0 = non spécifié dans le JSON
    return nodes, data.get("edges", []), trip_count


def read_timings(filename: str) -> Dict[str, TimingInfo]:
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)
    return {k: TimingInfo(v["t_su"], v["latency"], v["t_co"]) for k, v in data.items()}


def read_constraints(filename: str) -> Tuple[Dict[str, int], Dict[str, str]]:
    with open(filename, encoding="utf-8") as f:
        data = json.load(f)
    return (
        {k: int(v) for k, v in data["resource_limits"].items()},
        dict(data["op_to_resource"]),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Inférence automatique du trip count depuis le DAG
# ═════════════════════════════════════════════════════════════════════════════

def infer_trip_count(nodes: List[Node]) -> Optional[int]:
    """
    Tente de déduire le nombre d'itérations de la boucle en analysant
    le nœud de comparaison (icmpi) et les phi d'induction.

    Stratégie :
      1. Trouver le nœud icmpi  → extrait la borne supérieure B et l'opérateur (<, <=, …)
      2. Identifier le phi d'induction utilisé dans la comparaison
      3. Trouver sa valeur initiale (const prédécesseur hors boucle)
      4. Trouver le pas : nœud addi/subi dans loop_preds du phi, avec une const prédécesseur
      5. trip_count = ceil((B - init) / step)   pour "<"
                    = ceil((B - init + 1) / step) pour "<="

    Retourne None si l'analyse échoue (boucle non statique).
    """
    import re

    def last_int(s: str) -> Optional[int]:
        """Extrait le dernier entier d'une chaîne, ex: 'const:i32 7' → 7."""
        matches = re.findall(r'-?\d+', s)
        return int(matches[-1]) if matches else None

    node_map = {n.idx: n for n in nodes}

    # ── 1. Trouver le nœud icmpi ──────────────────────────────────────────
    icmp_node = next(
        (n for n in nodes if "icmp" in n.mnemonic.lower()),
        None
    )
    if icmp_node is None:
        print("  [trip_count] Aucun icmpi trouvé → N non inférable")
        return None

    mnem = icmp_node.mnemonic  # ex : "arith.icmpi (.0 < 7)"

    # Extraire l'opérateur de comparaison et la borne (dernier entier après l'opérateur)
    m = re.search(r'\(\s*\S+\s*(<=|>=|<|>|==|!=)\s*(-?\d+)\s*\)', mnem)
    if not m:
        print(f"  [trip_count] Format icmpi non reconnu : {mnem!r}")
        return None

    cmp_op = m.group(1)      # "<", "<=", ">", ">=", "==", "!="
    bound  = int(m.group(2)) # borne numérique (déjà le bon groupe ici)

    # ── 2. Identifier le phi d'induction parmi les prédécesseurs du icmpi ─
    phi_id = next(
        (p for p in icmp_node.preds
         if node_map.get(p) and "phi" in node_map[p].mnemonic.lower()),
        None
    )
    if phi_id is None:
        print("  [trip_count] Phi d'induction introuvable parmi les preds de icmpi")
        return None

    phi_node = node_map[phi_id]

    # ── 3. Valeur initiale du phi (const prédécesseur hors boucle) ────────
    init_val = None
    for p_id in phi_node.preds:
        p = node_map.get(p_id)
        if p and "const" in p.mnemonic.lower():
            init_val = last_int(p.mnemonic)
            break

    if init_val is None:
        print("  [trip_count] Valeur initiale du phi introuvable")
        return None

    # ── 4. Pas d'induction (nœud addi/subi dans loop_preds du phi) ────────
    step = None
    for lp_id in phi_node.loop_preds:
        lp = node_map.get(str(lp_id))
        if lp is None:
            continue
        mn = lp.mnemonic.lower()
        if "addi" in mn or "subi" in mn:
            for pp_id in lp.preds:
                pp = node_map.get(pp_id)
                if pp and "const" in pp.mnemonic.lower():
                    s = last_int(pp.mnemonic)
                    if s is not None:
                        step = -s if "subi" in mn else s
                        break
        if step is not None:
            break

    if step is None or step == 0:
        #print("  [trip_count] Pas d'induction introuvable ou nul → step=1 par défaut")
        step = 1

    # ── 5. Calcul du trip count ───────────────────────────────────────────
    if cmp_op == "<":
        N = math.ceil((bound - init_val) / step)
    elif cmp_op == "<=":
        N = math.ceil((bound - init_val + 1) / step)
    elif cmp_op == ">":
        N = math.ceil((init_val - bound) / step)
    elif cmp_op == ">=":
        N = math.ceil((init_val - bound + 1) / step)
    else:
        #print(f"  [trip_count] Opérateur {cmp_op!r} non géré → N non inférable")
        return None

    if N <= 0:
        #print(f"  [trip_count] Trip count calculé ≤ 0 ({N}), boucle jamais exécutée ?")
        return max(N, 0)

    #print(f"  [trip_count] init={init_val}  borne={bound}  op={cmp_op!r}  step={step}"
    #      f"  → N={N} itérations")
    return N


# ═════════════════════════════════════════════════════════════════════════════
# Calcul de MII
# ═════════════════════════════════════════════════════════════════════════════

def compute_mii(real_nodes: List[Node],
                resource_limits: Dict[str, int],
                op_to_resource: Dict[str, str],
                timings: Dict[str, TimingInfo]) -> int:
    # ResMII : max( ceil(usage[r] / limit[r]) )
    usage: Dict[str, int] = {}
    for n in real_nodes:
        r = get_resource(n, op_to_resource)
        if r:
            usage[r] = usage.get(r, 0) + 1
    res_mii = max(
        (math.ceil(c / resource_limits.get(r, 1)) for r, c in usage.items()),
        default=1
    )

    # RecMII : latence maximale sur les chemins de dépendance portés par la boucle
    node_map = {n.idx: n for n in real_nodes}
    rec_mii = 1
    for n in real_nodes:
        for lp in n.loop_preds:
            prod = node_map.get(lp)
            if prod:
                rec_mii = max(rec_mii, get_timing(prod, timings).L)

    II = max(res_mii, rec_mii)
    #print(f"  ResMII={res_mii}  RecMII={rec_mii}  → II={II}")
    return II


# ═════════════════════════════════════════════════════════════════════════════
# List scheduling (acyclique — une seule itération ou acyclique pur)
# ═════════════════════════════════════════════════════════════════════════════

def list_schedule_acyclic(
        nodes: List[Node],
        resource_limits: Dict[str, int],
        op_to_resource: Dict[str, str],
        timings: Dict[str, TimingInfo],
        t_clk: float,
        external_ready: Dict[str, int],   # cycle de disponibilité connu a priori
        already_done: Set[str],            # noeuds à NE PAS re-placer dans le table
) -> Tuple[ScheduleTable, Dict[str, int]]:
    """
    Place chaque noeud de `nodes` dès que ses prédécesseurs sont disponibles.
    Retourne (ScheduleTable, ready_time).
    """
    sched      = ScheduleTable(t_clk)
    ready_time = dict(external_ready)                         # {id -> cycle_fin}
    scheduled  = set(already_done) & {n.idx for n in nodes}  # déjà placés

    max_cycles = len(nodes) * 10 + 20

    for current_cycle in range(max_cycles):
        if len(scheduled) >= len(nodes):
            break

        # Capacité disponible sur ce cycle (instances × temps libre)
        res_free: Dict[str, Dict[int, float]] = {
            r: {i: 0.0 for i in range(lim)}
            for r, lim in resource_limits.items()
        }

        progress = True
        while progress:
            progress = False
            for n in nodes:
                if n.idx in scheduled:
                    continue

                # Calculer le cycle au plus tôt depuis les preds intra-itération
                earliest = 0
                ok = True
                for p_id in n.preds:
                    if p_id not in ready_time:
                        ok = False
                        break
                    earliest = max(earliest, ready_time[p_id])
                if not ok:
                    continue

                # loop_preds : dépendances inter-itération (valeur fournie externellement)
                for lp_id in n.loop_preds:
                    if lp_id in ready_time:
                        earliest = max(earliest, ready_time[lp_id])
                    # première itération : pas de contrainte

                if earliest > current_cycle:
                    continue

                timing = get_timing(n, timings)
                res    = get_resource(n, op_to_resource)

                if res is None:
                    # Noeud sans ressource (trivial non filtré, return…)
                    sched.schedule_at(f"{n.mnemonic}_{n.idx}", current_cycle,
                                      0.0, timing, None)
                    ready_time[n.idx] = current_cycle + timing.L
                    scheduled.add(n.idx)
                    progress = True
                    continue

                # Chercher une instance disponible
                inst = None; off = 0.0
                for i, free_off in res_free.get(res, {}).items():
                    if free_off + timing.t_su <= t_clk:
                        inst = i
                        off  = free_off
                        break

                if inst is not None:
                    sched.schedule_at(f"{n.mnemonic}_{n.idx}", current_cycle,
                                      off, timing, f"{res}#{inst}")
                    res_free[res][inst] = off + timing.t_su
                    ready_time[n.idx]  = current_cycle + timing.L
                    scheduled.add(n.idx)
                    progress = True

    unscheduled = [n.idx for n in nodes if n.idx not in scheduled]
    #if unscheduled:
        #print(f"  WARN noeuds non schedulés: {unscheduled}")
    return sched, ready_time


# ═════════════════════════════════════════════════════════════════════════════
# Kernel modulaire : placement avec vérification de conflit ressource mod II
# ═════════════════════════════════════════════════════════════════════════════

def modulo_schedule_kernel(
        real_nodes: List[Node],
        resource_limits: Dict[str, int],
        op_to_resource: Dict[str, str],
        timings: Dict[str, TimingInfo],
        t_clk: float,
        external_ready: Dict[str, int],  # triviaux + back-edges résolus (contraintes temporelles)
        already_placed: Set[str],         # IDs déjà placés pour de vrai (triviaux uniquement)
        II: int,
) -> Tuple[Dict[str, int], Dict[str, Tuple[int, float, str]]]:
    """
    Place les noeuds réels du corps de boucle en respectant l'II (modulo scheduling).

    Distinction critique :
      - external_ready  : contraintes temporelles (disponibilité des valeurs),
                          inclut triviaux ET back-edges. Alimente ready_time.
      - already_placed  : noeuds réellement déjà schedulés (triviaux seulement).
                          Les back-edges NE sont PAS dans already_placed : ils
                          doivent être placés dans le kernel.

    Retourne :
        ready_time  : {node_id -> cycle de fin}
        kernel_ops  : {node_id -> (slot, offset_ns, operator_key)}
    """
    # Table de réservation modulaire : res -> slot -> instance -> temps_libre_ns
    modulo_table: Dict[str, Dict[int, Dict[int, float]]] = {
        r: {s: {i: 0.0 for i in range(lim)} for s in range(II)}
        for r, lim in resource_limits.items()
    }

    ready_time  = dict(external_ready)        # contraintes temporelles connues
    kernel_ops: Dict[str, Tuple[int, float, str]] = {}
    # scheduled = noeuds réellement placés (triviaux pré-marqués, réels ajoutés au fur et à mesure)
    scheduled: Set[str] = set(already_placed)

    real_ids = {n.idx for n in real_nodes}
    max_iter = len(real_nodes) * (II + 5) + 20

    for attempt in range(max_iter):
        if all(n.idx in scheduled for n in real_nodes):
            break

        progress = True
        while progress:
            progress = False
            for n in real_nodes:
                if n.idx in scheduled:
                    continue

                # Earliest cycle absolu : attendre tous les preds intra-itération
                earliest = 0
                ok = True
                for p_id in n.preds:
                    if p_id not in ready_time:
                        ok = False; break
                    earliest = max(earliest, ready_time[p_id])
                if not ok:
                    continue

                # loop_preds : valeur de l'itération précédente (contrainte back-edge)
                for lp_id in n.loop_preds:
                    if lp_id in ready_time:
                        earliest = max(earliest, ready_time[lp_id])

                timing = get_timing(n, timings)
                res    = get_resource(n, op_to_resource)

                placed = False
                for try_cycle in range(earliest, earliest + II + 1):
                    slot = try_cycle % II

                    # ── Vérification des dépendances intra-kernel ────────────
                    # Règle : pour tout prédécesseur p déjà placé dans le kernel,
                    # le nœud consommateur doit démarrer après que p ait terminé
                    # dans la même itération :
                    #   slot_p + latency_p <= slot_n   (même itération)
                    # Si cette contrainte n'est pas satisfaite, le consommateur
                    # devra attendre l'itération suivante (slot_n + II ≥ slot_p + lat_p),
                    # ce qui est géré par le mécanisme de back-edge — mais le placement
                    # dans le kernel doit quand même respecter ce slot relatif.
                    dep_ok = True
                    for p_id in n.preds:
                        if p_id in kernel_ops:
                            p_slot = kernel_ops[p_id][0]
                            p_node = next((nd for nd in real_nodes if nd.idx == p_id), None)
                            if p_node:
                                p_lat = get_timing(p_node, timings).L
                                # Dans le kernel, slot_p + p_lat doit être ≤ slot_n
                                if p_slot + p_lat > slot:
                                    dep_ok = False
                                    break
                    if not dep_ok:
                        continue
                    # ─────────────────────────────────────────────────────────
                    slot = try_cycle % II

                    if res is None:
                        ready_time[n.idx] = try_cycle + timing.L
                        kernel_ops[n.idx] = (slot, 0.0, "no_resource")
                        scheduled.add(n.idx)
                        placed = True; progress = True
                        break

                    for inst_id, free_off in modulo_table[res][slot].items():
                        if free_off + timing.t_su <= t_clk:
                            modulo_table[res][slot][inst_id] = free_off + timing.t_su
                            ready_time[n.idx] = try_cycle + timing.L
                            op_key = f"{res}#{inst_id}"
                            kernel_ops[n.idx] = (slot, free_off, op_key)
                            scheduled.add(n.idx)
                            placed = True; progress = True
                            break
                    if placed:
                        break

    unscheduled = [n.idx for n in real_nodes if n.idx not in scheduled]
    # if unscheduled:
    #     print(f"  WARN kernel — noeuds non placés: {unscheduled}")

    return ready_time, kernel_ops


# ═════════════════════════════════════════════════════════════════════════════
# Dépliage : prologue + N × kernel + épilogue
# ═════════════════════════════════════════════════════════════════════════════

def expand_schedule(
        all_nodes: List[Node],
        trivial_nodes: List[Node],
        real_nodes: List[Node],
        return_nodes: List[Node],
        kernel_ops: Dict[str, Tuple[int, float, str]],  # {id -> (slot, off, op_key)}
        ready_time_kernel: Dict[str, int],               # ready_time après kernel (iter 0)
        timings: Dict[str, TimingInfo],
        resource_limits: Dict[str, int],
        op_to_resource: Dict[str, str],
        t_clk: float,
        II: int,
        N: int,                                          # nombre d'itérations
) -> ScheduleTable:
    """
    Construit le ScheduleTable complet en dupliquant le kernel N fois,
    chaque copie décalée de k*II cycles.

    Structure temporelle :
        Prologue  : cycles 0 .. (premier slot occupé)
        Kernel    : itérations 0..N-1, itération k débute à cycle k*II
        Épilogue  : après la dernière itération (return)
    """
    sched = ScheduleTable(t_clk)

    node_map = {n.idx: n for n in all_nodes}

    # ── 1. Triviaux : cycle 0, pas de ressource ───────────────────────────
    for n in trivial_nodes:
        t = get_timing(n, timings)
        sched.schedule_at(f"{n.mnemonic}_{n.idx}", 0, 0.0, t, None, iteration=-1)

    # ── 2. Kernel × N itérations ──────────────────────────────────────────
    # Pour chaque noeud réel, son slot dans le kernel est kernel_ops[id][0].
    # L'itération k est placée au cycle absolu : k * II + slot
    for k in range(N):
        for n in real_nodes:
            if n.idx not in kernel_ops:
                continue
            slot, off, op_key = kernel_ops[n.idx]
            abs_cycle = k * II + slot
            t = get_timing(n, timings)
            label = f"{n.mnemonic}_{n.idx}"
            operator = op_key if op_key != "no_resource" else None
            sched.schedule_at(label, abs_cycle, off, t, operator, iteration=k)

    # ── 3. Épilogue : return(s) après la dernière itération ──────────────
    # La dernière valeur produite par les noeuds réels est disponible à :
    #   (N-1)*II + slot + latency
    # On cherche le cycle de fin maximal de tous les producteurs du return.
    last_real_done = 0
    for n in real_nodes:
        if n.idx in kernel_ops:
            slot, _, _ = kernel_ops[n.idx]
            t = get_timing(n, timings)
            last_real_done = max(last_real_done, (N - 1) * II + slot + t.L)

    for n in return_nodes:
        # Calculer earliest : max(ready des preds, en tenant compte des loop_preds finaux)
        earliest = 0
        for p_id in n.preds:
            p = node_map.get(p_id)
            if p is None:
                continue
            if p.loop_preds:
                # Le phi prend la valeur de son loop_pred à la dernière itération
                for lp_id in p.loop_preds:
                    lp = node_map.get(lp_id)
                    if lp and lp_id in kernel_ops:
                        slot, _, _ = kernel_ops[lp_id]
                        t = get_timing(lp, timings)
                        earliest = max(earliest, (N - 1) * II + slot + t.L)
                    elif lp_id in ready_time_kernel:
                        earliest = max(earliest, ready_time_kernel[lp_id]
                                       + (N - 1) * II)
            elif p_id in kernel_ops:
                slot, _, _ = kernel_ops[p_id]
                t = get_timing(p, timings)
                earliest = max(earliest, (N - 1) * II + slot + t.L)
        earliest = max(earliest, last_real_done)

        t_ret = get_timing(n, timings)
        res   = get_resource(n, op_to_resource)  # peut être "add_i", "add_f", etc.

        if res is None:
            # Pas de ressource associée au return → placement simple
            sched.schedule_at(f"{n.mnemonic}_{n.idx}", earliest, 0.0, t_ret,
                              None, iteration=N)
        else:
            # Chercher une instance libre sur le cycle `earliest`
            # (et les suivants si nécessaire, épilogue n'a pas de contrainte II)
            placed = False
            for try_cycle in range(earliest, earliest + 10):
                # Reconstruction de la capacité disponible sur ce cycle
                # depuis le schedule déjà construit
                used_offsets: Dict[int, float] = {i: 0.0
                                                   for i in range(resource_limits.get(res, 1))}
                for ce in sched.table:
                    if ce.cycle != try_cycle:
                        continue
                    for _, _, off, dur, op_key, _ in ce.entry:
                        if op_key and op_key.startswith(res + "#"):
                            inst_id = int(op_key.split("#")[1])
                            used_offsets[inst_id] = max(used_offsets[inst_id],
                                                        off + dur.t_su)

                for inst_id, free_off in used_offsets.items():
                    if free_off + t_ret.t_su <= t_clk:
                        op_key = f"{res}#{inst_id}"
                        sched.schedule_at(f"{n.mnemonic}_{n.idx}", try_cycle,
                                          free_off, t_ret, op_key, iteration=N)
                        placed = True
                        break
                if placed:
                    break

            if not placed:
                # Fallback sans ressource
                sched.schedule_at(f"{n.mnemonic}_{n.idx}", earliest, 0.0, t_ret,
                                  None, iteration=N)

    return sched


# ═════════════════════════════════════════════════════════════════════════════
# Orchestration principale (boucle)
# ═════════════════════════════════════════════════════════════════════════════

def schedule_with_loops(
        all_nodes: List[Node],
        edges: List[dict],
        resource_limits: Dict[str, int],
        op_to_resource: Dict[str, str],
        timings: Dict[str, TimingInfo],
        t_clk: float,
        N: int,
) -> Tuple[ScheduleTable, int]:
    """
    Pipeline logiciel complet pour une boucle avec N itérations.

    Étapes :
      1. Calculer II
      2. Pass 1 acyclique (sans back-edges) pour obtenir les latences de base
      3. Calculer les back-edge_ready (offset -II)
      4. Modulo scheduling du kernel
      5. Dépliage × N
    """
    trivial = [n for n in all_nodes if is_trivial(n)]
    returns = [n for n in all_nodes if is_return(n)]
    real    = [n for n in all_nodes if not is_trivial(n) and not is_return(n)]

    # print(f"  Triviaux ({len(trivial)}): {[n.idx for n in trivial]}")
    # print(f"  Réels    ({len(real)}):    {[n.idx for n in real]}")
    # print(f"  Returns  ({len(returns)}): {[n.idx for n in returns]}")
    print(f"  N itérations : {N}")

    # ── II ────────────────────────────────────────────────────────────────
    II = compute_mii(real, resource_limits, op_to_resource, timings)

    trivial_ready = {n.idx: 0 for n in trivial}
    trivial_done  = {n.idx for n in trivial}

    # ── Pass 1 : schedule acyclique pour estimer les latences réelles ─────
    _, ready_time_p1 = list_schedule_acyclic(
        trivial + real, resource_limits, op_to_resource, timings, t_clk,
        external_ready=dict(trivial_ready),
        already_done=trivial_done,
    )

    # ── Résoudre les back-edges ───────────────────────────────────────────
    # Pour une dépendance iter[k] → iter[k+1], on modélise la valeur
    # produite par iter[k-1] comme disponible à : ready[lp] - II
    back_edge_ready: Dict[str, int] = {}
    for n in all_nodes:
        for lp_id in n.loop_preds:
            if lp_id in ready_time_p1:
                back_edge_ready[lp_id] = max(0, ready_time_p1[lp_id] - II)

    external_kernel = {**trivial_ready, **back_edge_ready}

    # ── Modulo scheduling du kernel (avec auto-incrément de II si besoin) ─
    MAX_II = II * 4  # limite de sécurité
    while True:
        ready_time_kernel, kernel_ops = modulo_schedule_kernel(
            real, resource_limits, op_to_resource, timings, t_clk,
            external_ready=external_kernel,
            already_placed=trivial_done,
            II=II,
        )
        # Vérifier que tous les nœuds réels ont été placés
        unplaced = [n for n in real if n.idx not in kernel_ops]
        if not unplaced:
            break
        if II >= MAX_II:
            print(f"  ERREUR : impossible de scheduler avec II≤{MAX_II}, nœuds non placés : {[n.idx for n in unplaced]}")
            break
        II += 1
        print(f"  → Nœuds non placés {[n.idx for n in unplaced]}")#, augmentation II → {II}")
        # Recalculer les back-edges avec le nouvel II
        back_edge_ready = {}
        for n in all_nodes:
            for lp_id in n.loop_preds:
                if lp_id in ready_time_p1:
                    back_edge_ready[lp_id] = max(0, ready_time_p1[lp_id] - II)
        external_kernel = {**trivial_ready, **back_edge_ready}

    # print("\n  Kernel (slot relatif dans II) :")
    # for node_id, (slot, off, op_key) in sorted(kernel_ops.items(),
    #                                             key=lambda x: x[1][0]):
    #     n = next(nd for nd in real if nd.idx == node_id)
    #     print(f"    [{slot:2d}] {n.mnemonic:40s}  off={off:.1f}  res={op_key}")

    # ── Dépliage × N ─────────────────────────────────────────────────────
    sched = expand_schedule(
        all_nodes=all_nodes,
        trivial_nodes=trivial,
        real_nodes=real,
        return_nodes=returns,
        kernel_ops=kernel_ops,
        ready_time_kernel=ready_time_kernel,
        timings=timings,
        resource_limits=resource_limits,
        op_to_resource=op_to_resource,
        t_clk=t_clk,
        II=II,
        N=N,
    )

    return sched, II


# ═════════════════════════════════════════════════════════════════════════════
# Orchestration pour graphe acyclique (pas de boucle)
# ═════════════════════════════════════════════════════════════════════════════

def schedule_acyclic(
        nodes: List[Node],
        resource_limits: Dict[str, int],
        op_to_resource: Dict[str, str],
        timings: Dict[str, TimingInfo],
        t_clk: float,
) -> ScheduleTable:
    ext  = {n.idx: 0 for n in nodes if is_trivial(n)}
    done = {n.idx for n in nodes if is_trivial(n)}
    sched, _ = list_schedule_acyclic(nodes, resource_limits, op_to_resource,
                                      timings, t_clk, ext, done)
    return sched


# ═════════════════════════════════════════════════════════════════════════════
# Export HTML
# ═════════════════════════════════════════════════════════════════════════════

# Palette de couleurs pour distinguer visuellement les itérations
ITER_COLORS = [
    "#fff3e0",  # orange clair
    "#e8f5e9",  # vert clair
    "#e3f2fd",  # bleu clair
    "#fce4ec",  # rose clair
    "#f3e5f5",  # violet clair
    "#e0f7fa",  # cyan clair
    "#fff8e1",  # jaune clair
    "#ede7f6",  # indigo clair
]

def iter_color(iteration: int) -> str:
    if iteration < 0:
        return "#f0f0f0"   # triviaux / statique
    return ITER_COLORS[iteration % len(ITER_COLORS)]


def write_schedule_html(
        rtab: ScheduleTable,
        nodes: List[Node],
        resource_limits: Dict[str, int],
        filename: str,
        title: str,
        II: Optional[int] = None,
        N: Optional[int] = None,
) -> None:
    operator_instances = [
        f"{res}#{i}"
        for res, count in resource_limits.items()
        for i in range(count)
    ]
    total_ops = sum(len(ce.entry) for ce in rtab.table)
    ii_info   = (f"<strong>Initiation Interval (II):</strong> {II} cycles<br>"
                 f"<strong>Nombre d'itérations (N):</strong> {N}<br>") if II else ""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{title}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
          margin: 20px; background-color: #f5f5f5; }}
  h1   {{ color: #333; text-align: center; }}
  .info {{ background-color: #e3f2fd; padding: 10px; border-radius: 5px;
           margin-bottom: 20px; }}
  table {{ border-collapse: collapse; width: 100%; background-color: white;
           box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
  th   {{ background-color: #1976d2; color: white; padding: 12px;
          text-align: left; font-weight: bold; }}
  td   {{ padding: 8px 12px; border-bottom: 1px solid #ddd;
          border-right: 1px solid #eee; vertical-align: top; }}
  td:last-child {{ border-right: none; }}
  tr:hover {{ filter: brightness(0.97); }}
  .cycle-hdr {{ font-weight: bold; white-space: nowrap; }}
  .trivial  {{ color: #999; font-style: italic; font-size: 0.82em; margin-top: 4px; }}
  .op-cell  {{ border-radius: 4px; padding: 4px 7px; margin-bottom: 4px;
               font-family: 'Courier New', monospace; font-size: 0.9em; }}
  .op-name  {{ font-weight: 700; color: #b71c1c; }}
  .op-meta  {{ color: #555; font-size: 0.82em; }}
  .legend   {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }}
  .leg-item {{ padding: 4px 12px; border-radius: 12px; font-size: 0.85em;
               border: 1px solid #ccc; }}
</style></head><body>
<h1>{title}</h1>
<div class="info">
  <strong>Clock Period:</strong> {rtab.t_clk} ns<br>
  <strong>Total Cycles:</strong> {len(rtab.table)}<br>
  <strong>Total Opérations:</strong> {total_ops}<br>
  <strong>Total Nœuds:</strong> {len(nodes)}<br>
  {ii_info}
</div>
"""

    # Légende des couleurs d'itération
    if N and N > 0:
        html += '<div class="legend">'
        html += f'<div class="leg-item" style="background:{iter_color(-1)}">Statique / Triviaux</div>'
        for k in range(N):
            html += (f'<div class="leg-item" style="background:{iter_color(k)}">'
                     f'Itération {k}</div>')
        html += f'<div class="leg-item" style="background:{iter_color(N)}">Épilogue / Return</div>'
        html += '</div>\n'

    html += "<table><thead><tr><th>Cycle</th>"
    for oi in operator_instances:
        html += f"<th>{oi}</th>"
    html += "</tr></thead><tbody>\n"

    for ce in rtab.table:
        if not ce.entry:
            continue

        opmap: Dict[str, List] = {oi: [] for oi in operator_instances}
        trivials_html = []

        for entry in ce.entry:
            op, _, offset, duration, operator, iteration = entry
            if operator and operator in opmap:
                opmap[operator].append((op, offset, duration, iteration))
            else:
                trivials_html.append((op, iteration))

        html += f"<tr><td class='cycle-hdr'>Cycle {ce.cycle}"
        if trivials_html:
            html += "<div class='trivial'>"
            html += "<br>".join(
                f'<span style="background:{iter_color(it)};padding:1px 4px;border-radius:3px;">{op}</span>'
                for op, it in trivials_html
            )
            html += "</div>"
        html += "</td>"

        for oi in operator_instances:
            if opmap[oi]:
                cell_html = ""
                for opname, offset, dur, iteration in opmap[oi]:
                    bg = iter_color(iteration)
                    cell_html += (
                        f'<div class="op-cell" style="background:{bg};">'
                        f'<div class="op-name">{opname}</div>'
                        f'<div class="op-meta">off={offset:.1f} ns | lat={dur.L} | iter={iteration}</div>'
                        f'</div>'
                    )
                html += f"<td>{cell_html}</td>"
            else:
                html += "<td></td>"
        html += "</tr>\n"

    html += "</tbody></table></body></html>\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML schedule exporté : {filename}")

def format_op_id(raw_string):
    # Regex : on capture le début, on ignore le milieu entre parenthèses,
    # et on capture l'ID final après l'underscore.
    match = re.search(r'^([\w\.]+)\s*\(.*\)_(\d+)$', raw_string)

    if match:
        op_name = match.group(1) # ex: arith.muli
        op_id = match.group(2)   # ex: 3
        return f"{op_name}_{op_id}"

    return raw_string

def format_signal_id(signal_string):
    replacements = str.maketrans({":": "_", ".": "_", " ": "_", "(": "_", ")": "_", "+":"_", "*":"_"})
    signal_string = signal_string.translate(replacements)
    return signal_string

# ═════════════════════════════════════════════════════════════════════════════
# Export JSON
# ═════════════════════════════════════════════════════════════════════════════

def generate_json_schedule(
        rtab: ScheduleTable,
        nodes: List[Node],
        resource_limits: Dict[str, int],
) -> dict:
    node_map  = {n.idx: n for n in nodes}
    instances = [f"{r.lower()}_{i}"
    for r, cnt in resource_limits.items() for i in range(cnt)]
    out: dict = {}

    for ce in rtab.table:
        if not ce.entry:
            continue
        ck = f"Cycle {ce.cycle}"
        out[ck] = {inst: {} for inst in instances}

        for op_label, _, offset, duration, operator, iteration in ce.entry:
            # Retrouver le noeud de base (sans suffixe itération)
            node = next(
                (n for n in nodes if op_label.startswith(f"{n.mnemonic}_{n.idx}")),
                None,
            )
            if node is None:
                continue

            res_key = operator.replace("#", "_").lower() if operator else "no_resource"
            if res_key not in out[ck]:
                out[ck][res_key] = {}

            inputs = []
            for p_id in node.preds + node.loop_preds:
                p = node_map.get(p_id)
                if p:
                    inputs.append(f"{p.mnemonic}_{p.idx}")
            if not inputs:
                inputs = ["external_input"]

            out[ck][res_key] = {
                "operation" : format_op_id(f"{node.mnemonic}_{node.idx}"),
                "iteration" : iteration,
                "inputs"    : [format_signal_id(inp) for inp in inputs],
                "output"   : [format_signal_id(f"{node.mnemonic}_{node.idx}")],
                # "offset_ns" : offset,
                # "timing"    : duration.as_tuple(),
            }

    return out


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python scheduler_cycle_html.py <dag.json> [N_iterations]")
        return

    dag_file = sys.argv[1]

    # Lecture du graphe (trip_count optionnel dans le JSON)
    nodes, edges, trip_count_json = read_dag(dag_file)

    # Priorité : argument CLI > champ JSON > inférence automatique > défaut 1
    if len(sys.argv) >= 3:
        N = int(sys.argv[2])
        print(f"  [trip_count] Fourni en argument CLI : N={N}")
    elif trip_count_json > 0:
        N = trip_count_json
        print(f"  [trip_count] Fourni dans le JSON : N={N}")
    else:
        N = infer_trip_count(nodes)
        if N is None or N <= 0:
            print("  [trip_count] Inférence échouée → N=1 par défaut")
            N = 1

    # Fichiers de contraintes
    # Chemin absolu du répertoire du script python
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    try:
        ressources = os.path.join(SCRIPT_DIR, "resources_offset.json")
        res_lim, op2res = read_constraints(ressources)
    except FileNotFoundError:
        print("ERREUR : resources_offset.json introuvable.")
        return

    try:
        latencies= os.path.join(SCRIPT_DIR, "latencies.json")
        timings = read_timings(latencies)
    except FileNotFoundError:
        print("ERREUR : latencies.json introuvable.")
        return

    t_clk = 14.0
    II    = None

    has_loops = any(n.loop_preds for n in nodes)
    print(f"Graphe {'cyclique (boucle)' if has_loops else 'acyclique'} — "
          f"{len(nodes)} nœuds")

    if has_loops:
        sched, II = schedule_with_loops(nodes, edges, res_lim, op2res,
                                        timings, t_clk, N=N)
        # print(f"\nII final = {II} cycles  |  Schedule total = "
        #       f"{sum(1 for ce in sched.table if ce.entry)} cycles actifs")
        print(f"Schedule total = "f"{sum(1 for ce in sched.table if ce.entry)} cycles actifs")
    else:
        sched = schedule_acyclic(nodes, res_lim, op2res, timings, t_clk)

    #sched.print_table()

    # Export JSON
    out_json = generate_json_schedule(sched, nodes, res_lim)
    if len(sys.argv) > 1:
        out_json_path = sys.argv[1].replace(".json", "_schedule.json")
    else:
        out_json_path = "scheduling.json"
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2, ensure_ascii=False)
    print("Schedule JSON → ", out_json_path)

    # Export HTML
    write_schedule_html(
        sched, nodes, res_lim,
        out_json_path.replace(".json", ".html"),
        "List Scheduling",
        II=II, N=N,
    )


if __name__ == "__main__":
    main()