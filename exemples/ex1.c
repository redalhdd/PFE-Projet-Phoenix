int main() {
    int a=5, acc =0, b=0;
    for(int i=1; i<5; i++){
        acc += a*i;
        b=i*2 +5;
        acc = acc*b;
    }
    return acc;
}


