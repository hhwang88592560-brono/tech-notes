#include <stdio.h>

static void set_value(int value)
{
    value = 42;
    printf("inside=%d\n", value);
}

int main(void)
{
    int value = 7;
    set_value(value);
    printf("outside=%d\n", value);
    return 0;
}
