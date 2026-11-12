#include <assert.h>
#include <stdio.h>

unsigned int regular_value = 7U;
volatile unsigned int observed_value = 7U;

unsigned int read_regular_twice(void)
{
    unsigned int first = regular_value;
    unsigned int second = regular_value;
    return first + second;
}

unsigned int read_observed_twice(void)
{
    /* 两次读取位于两个完整表达式中。 */
    unsigned int first = observed_value;
    unsigned int second = observed_value;
    return first + second;
}

int main(void)
{
    unsigned int regular = read_regular_twice();
    unsigned int observed = read_observed_twice();
    printf("regular=%u\n", regular);
    printf("observed=%u\n", observed);
    assert(regular == 14U && observed == 14U);
    return 0;
}
