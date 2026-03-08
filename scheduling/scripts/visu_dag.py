import json,sys
from graphviz import Digraph
from collections import defaultdict

def visualize_dag(json_file):
    with open(json_file, 'r') as f:
        data = json.load(f)

    dot = Digraph(comment='LLVM Dependency Graph')
    dot.attr(rankdir='TB')
    dot.attr('graph', fontname='Helvetica', nodesep='0.5', ranksep='0.9', splines='polyline')
    dot.attr('node', fontname='Helvetica', fontsize='11')
    dot.attr('edge', fontname='Helvetica', fontsize='9')

    # Grouper les noeuds par basic block
    blocks = defaultdict(list)
    for node in data['nodes']:
        blocks[node['block']].append(node)

    # Tous les IDs de noeuds existants (pour éviter les fantômes)
    all_node_ids = {str(n['id']) for n in data['nodes']}

    # Premier noeud non-const de chaque bloc (cible des edges de contrôle)
    first_real_node = {}
    for b_name, nodes in blocks.items():
        non_const = [n for n in nodes if 'const' not in n['mnemonic']]
        first_real_node[str(b_name)] = str(
            non_const[0]['id'] if non_const else nodes[0]['id']
        )

    # Blocs sources des edges de contrôle (ont besoin d'un noeud br)
    # IMPORTANT : on compare les noms de BLOCS, pas les IDs de noeuds
    block_names = set(str(b) for b in blocks.keys())
    blocks_with_br = set()
    for e in data.get('edges', []):
        src = str(e['from'])
        if src in block_names:
            blocks_with_br.add(src)

    # Ordre des blocs
    def block_sort_key(b):
        try: return (0 if b == '0' else 1, int(b))
        except: return (1, 999)
    block_names_sorted = sorted(blocks.keys(), key=block_sort_key)

    # ── CLUSTERS ──────────────────────────────────────────────────────────────
    for b_name in block_names_sorted:
        nodes = blocks[b_name]
        with dot.subgraph(name=f'cluster_{b_name}') as sub:
            lbl = 'Entry (BB%0)' if str(b_name) == '0' else f'Basic Block %{b_name}'
            sub.attr(label=lbl, style='filled', fillcolor='lightyellow',
                     color='black', penwidth='2', fontname='Helvetica', fontsize='12')

            for node in nodes:
                nid      = str(node['id'])
                mnemonic = node['mnemonic']
                lbl_txt  = f"{mnemonic}\n(ID: {nid})"

                if 'arith' in mnemonic:
                    sub.node(nid, lbl_txt, shape='box',
                             style='filled', fillcolor='lightblue', color='blue')
                elif 'phi' in mnemonic:
                    sub.node(nid, lbl_txt, shape='ellipse',
                             style='filled', fillcolor='plum', color='purple')
                elif 'const' in mnemonic:
                    sub.node(nid, lbl_txt, shape='ellipse',
                             style='filled', fillcolor='lightgray', color='gray')
                elif 'return' in mnemonic:
                    sub.node(nid, lbl_txt, shape='ellipse',
                             style='filled', fillcolor='lightgreen', color='darkgreen')
                else:
                    sub.node(nid, lbl_txt, shape='ellipse')

            # Noeud br seulement pour les blocs sources d'edges de contrôle
            if str(b_name) in blocks_with_br:
                out_edges = [e for e in data.get('edges', [])
                             if str(e['from']) == str(b_name)]
                br_lbl = 'br (cond)' if len(out_edges) > 1 else 'br'
                sub.node(f'br_{b_name}', br_lbl, shape='diamond',
                         style='filled', fillcolor='gold',
                         color='darkorange', fontsize='10')

    # ── DEPENDANCES DE DONNEES ─────────────────────────────────────────────────
    for node in data['nodes']:
        nid = str(node['id'])
        for pred in node.get('preds', []):
            dot.edge(str(pred), nid, color='black', penwidth='1.5')

    # ── BACK-EDGES DES PHI (loop_preds) ───────────────────────────────────────
    for node in data['nodes']:
        nid = str(node['id'])
        for pred in node.get('loop_preds', []):
            dot.edge(str(pred), nid,
                     color='crimson', style='dashed', label='↺',
                     fontcolor='crimson', constraint='false', penwidth='1.5')

    # ── ANCRAGE br <- dernier noeud utile du bloc ──────────────────────────────
    for b_name in blocks_with_br:
        b_nodes = blocks.get(b_name, blocks.get(int(b_name), []))
        anchor = None
        for n in reversed(b_nodes):
            if 'icmp' in n['mnemonic']:
                anchor = str(n['id']); break
        if anchor is None:
            for n in reversed(b_nodes):
                if 'arith' in n['mnemonic']:
                    anchor = str(n['id']); break
        if anchor is None and b_nodes:
            anchor = str(b_nodes[-1]['id'])
        if anchor:
            dot.edge(anchor, f'br_{b_name}', color='gray40',
                     style='dashed', arrowhead='none')

    # ── FLOT DE CONTROLE ──────────────────────────────────────────────────────
    for edge in data.get('edges', []):
        src   = str(edge['from'])
        tgt   = str(edge['to'])
        label = edge.get('label', '')
        br_id = f'br_{src}'

        # Résoudre la cible vers un vrai noeud existant
        tgt_node = first_real_node.get(tgt)
        if tgt_node not in all_node_ids:
            # Fallback : chercher dans le bloc
            tgt_nodes = blocks.get(tgt, blocks.get(int(tgt) if tgt.isdigit() else tgt, []))
            tgt_node  = str(tgt_nodes[0]['id']) if tgt_nodes else None

        if tgt_node is None:
            print(f"WARN: pas de noeud cible pour bloc '{tgt}', edge ignoré")
            continue

        if 'True'      in label: color, fc = 'darkgreen',  'darkgreen'
        elif 'False'   in label: color, fc = 'crimson',    'crimson'
        elif 'loop_back' in label: color, fc = 'royalblue', 'royalblue'
        else:                    color, fc = 'darkorange', 'darkorange'

        dot.edge(br_id, tgt_node,
                 label=f' {label}', color=color, fontcolor=fc,
                 penwidth='2',
                 constraint='false' if 'loop_back' in label else 'true')

    png_name=sys.argv[1].replace('.json', '')
    dot.render(png_name, view=False, format='png', cleanup=True)
    print(f"Visualisation sauvegardee : {png_name}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        visualize_dag(sys.argv[1])