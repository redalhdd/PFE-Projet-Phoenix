#!/bin/bash
# Script qui prend en entrée un code c, le compile en une IR optimisée avec mem2reg puis génère
# - un fichier json comprenant les dépendances entre les opérations et le flot de controle des basic block
# - la visualisation sous forme png de ce fichier json : un graphe de flot de controle et de dépendances
# - un fichier html contenant un scheduling cycle par cycle de des opérations
# - un fichier json contenant l'ordonnancment cycle par cycle pour pouvoir être exploité par réda

c_file="$1"
base="${c_file%.c}"
IR_file="${base}.ll"

# compilation du code c en IR optimisée avec mem2reg
clang -S -emit-llvm -Xclang -disable-O0-optnone "$c_file" -o - | opt -passes='mem2reg' -S -o "$IR_file"

# génération du json représentant le grapphe de flot et de dépendance de l'IR LLVM
python3 ./scheduling/scripts/dag_block_v4.py "$IR_file" > "${base}_graphe.json"

# visualisation du graphe de flot et de dépendance avec graphviz
python3 ./scheduling/scripts/visu_dag.py "${base}_graphe.json"

#list scheduling des opérations présente dans le json de dépendance/flot
python3 ./scheduling/scripts/scheduler_cycle_html_v3.py "${base}_graphe.json"

# deduction du nom du json de scheduling a donné en paramètre à  l'outil de reda
json_schedule="${base}_graphe_schedule.json"
echo "Fichier JSON schedule : $json_schedule"