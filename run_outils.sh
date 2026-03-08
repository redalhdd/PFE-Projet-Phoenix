#!/bin/bash

c_file="$1"

# run scheduler.sh et récupère le nom du json en output
json_schedule=$(./scheduling/scheduler.sh "$c_file" | tail -n 1)
if [ $? -ne 0 ]; then
    echo "ERREUR : scheduler.sh a échoué" >&2
    exit 1
fi

# echo "JSON généré : $graphe_json"

./Generateur_VHDL/run.sh "$json_schedule"
if [ $? -ne 0 ]; then
    echo "ERREUR : run.sh a échoué" >&2
    exit 1
fi

echo "Succès : tous les fichiers générés pour $c_file"

