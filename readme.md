Cet outil a été réalisé par Réda Lahdoudi et Clément Nassih dans le cadre de notre projet de fin d'étude, le Projet Phoenix sous l'encadrement de monsieur Derrien. Ce projet a été réalisé lors de notre M2 Logiciel pour Systèmes Embarqués.

Ce outil a pour but de passer d'un code c initial à un fichier VHDl décrivant le comportement d'un circuit représentant le code C.

Pour cela nous passons par plusieurs étapes :

1) le fichier C est compilé en une représentation intermédiaire (IR) optimisé grâce à LLVM et la passe mem2reg au moyen d'une ligne de commande.
    'clang -S -emit-llvm -Xclang -disable-O0-optnone fichier.c -o - | opt -passes='mem2reg' -S -o IR.ll
2) De cette IR nous extrayons un graphe de flot de contrôle entre les différents basic blocks ainsi qu'un graphe de dépendances des différentes opérations au sein d'un basic block.
   Ce graphe est représenté sous la forme d'un fichier json. Cela est effectué dans le fichier "extraction_graphe.py"
3) Ce fichier json est transformé en png pour pouvoir plus facilement visualiser le graphe en utilisant graphViz. Cela se fait dans le fichier "visu_graphe.py".
4) Nous appliquons ensuite un algorithme de List Scheduling à ce graphe afin d'en obtenir un tableau de scheduling sous format HTMl ainsi qu'une représentation dans un format JSON pouvant être utilisée pour la génération VHDL qui va suivre.Cette étape est réalisée par le script "list_scheduling.py"
5)

Avant de pouvoir utiliser notre outil, il vous faudra installer plusieurs modules pythons :
- myhdl
- llvmlite
- graphViz

Ainsi que GDKWave pour pouvoir réaliser les simulations sur le code VHDL final.

Pour utiliser ce outil il vous suffit de lancer le script run_outils.sh et passer en paramètre le path vers un fichier C.
Vous avez un exemple déjà présent dans le repertoire exemples à la racine du projet et vous pouvez utiliser cet exemple avec notre outils via la commande :
    './run_outils exemples/ex1.c'
