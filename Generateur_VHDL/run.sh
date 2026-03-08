#!/bin/bash


# Vérifier qu'un argument est fourni
if [ -z "$1" ]; then
    echo "Usage : ./run_sim.sh <schedule.json>"
    exit 1
fi

# Vérifier que le fichier existe
if [ ! -f "$1" ]; then
    echo "Erreur : fichier '$1' introuvable"
    exit 1
fi

python testbench.py schedule.json

if [ $? -ne 0 ]; then
    echo "Erreur lors de la simulation !"
    exit 1
fi

echo ""
echo "=== Ouverture GTKWave ==="
if command -v gtkwave &> /dev/null; then
    gtkwave testbench.vcd &
else
    echo "GTKWave non installé — visualise le fichier testbench.vcd manuellement"
    echo "Installation : sudo apt install gtkwave (Linux) / brew install gtkwave (Mac)"
fi