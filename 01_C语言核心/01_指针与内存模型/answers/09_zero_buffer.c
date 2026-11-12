#include <assert.h>
#include <stddef.h>
#include <stdio.h>

static int zero_buffer(int *data, size_t count)
{
    if (count == 0) {
        return 1;
    }
    if (data == NULL) {
        return 0;
    }
    /* 调用者保证 data 指向至少 count 个可写 int 元素。 */
    for (size_t i = 0; i < count; ++i) {
        data[i] = 0;
    }
    return 1;
}

int main(void)
{
    int values[3] = {3, 6, 9};
    int ok = zero_buffer(values, sizeof values / sizeof values[0]);
    int empty_ok = zero_buffer(NULL, 0);
    int bad_ok = zero_buffer(NULL, 2);
    assert(ok == 1 && values[0] == 0 && values[1] == 0 && values[2] == 0);
    assert(empty_ok == 1 && bad_ok == 0);
    printf("zeroed=%d,%d,%d\n", values[0], values[1], values[2]);
    printf("null_empty=%d\n", empty_ok);
    printf("null_nonempty=%d\n", bad_ok);
    return 0;
}
