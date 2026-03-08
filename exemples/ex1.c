int main() {
    int a=5;
    int acc =0;
    int b=0;
    for(int i=1; i<5; i++){
        acc += a*i;
        b=i*2 +5;
        acc = acc*b;
    }
    return acc;
}


