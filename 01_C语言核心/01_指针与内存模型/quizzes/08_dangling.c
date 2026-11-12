#include <stdio.h>

static int *make_value(void)
{
    int value = 17;
    return &value;
}

int main(void)
{
    int *p = make_value();
    printf("value=%d\n", *p);
    return 0;
}
