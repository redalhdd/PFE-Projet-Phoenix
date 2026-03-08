#!/bin/bash
if [ -z "$1" ]; then
  echo "Usage : ./run.sh <schedule.json>"
  exit 1
fi

if [ ! -f "$1" ]; then
  echo "Erreur : fichier '$1' introuvable"
  exit 1
fi

python testbench.py "$1"   # ← $1 entre guillemets, pas "schedule.json"

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
fi