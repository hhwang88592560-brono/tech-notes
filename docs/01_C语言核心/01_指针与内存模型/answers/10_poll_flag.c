#include <assert.h>
#include <stddef.h>
#include <stdio.h>

static int poll_flag(const volatile unsigned int *status,
                     unsigned int mask, size_t max_reads)
{
    if (status == NULL || mask == 0U) {
        return 0;
    }
    for (size_t i = 0; i < max_reads; ++i) {
        unsigned int current = *status;
        if ((current & mask) != 0U) {
            return 1;
        }
    }
    return 0;
}

int main(void)
{
    /* 都是本程序的内存对象，没有访问外设。 */
    volatile unsigned int ready = 1U;
    volatile unsigned int idle = 0U;
    int found = poll_flag(&ready, 1U, 3);
    int missing = poll_flag(&idle, 1U, 3);
    int no_reads = poll_flag(&ready, 1U, 0);
    assert(found == 1 && missing == 0 && no_reads == 0);
    assert(poll_flag(NULL, 1U, 3) == 0);
    assert(poll_flag(&ready, 0U, 3) == 0);
    printf("ready=%d\n", found);
    printf("idle=%d\n", missing);
    printf("zero_reads=%d\n", no_reads);
    return 0;
}
