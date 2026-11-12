#include <stddef.h>
#include <stdio.h>

static size_t count_items(const int values[4])
{
    return sizeof values / sizeof values[0];
}

int main(void)
{
    int values[4] = {1, 2, 3, 4};
    printf("caller=%zu\n", sizeof values / sizeof values[0]);
    printf("callee=%zu\n", count_items(values));
    return 0;
}
