#include <stdio.h>

static void redirect(int *p, int *replacement)
{
    p = replacement;
    printf("local=%d\n", *p);
}

int main(void)
{
    int first = 7;
    int second = 9;
    int *p = &first;
    redirect(p, &second);
    printf("caller=%d\n", *p);
    return 0;
}
