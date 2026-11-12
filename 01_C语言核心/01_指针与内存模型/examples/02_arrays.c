#include <assert.h>
#include <stddef.h>
#include <stdio.h>

/* items 在形参位置调整为 const int *；count 才是本次处理的数量。
   约定：count > 0 时有至少 count 个可读元素；本例数值之和不溢出 int。 */
static int sum_items(const int items[4], size_t count)
{
    int total = 0;
    for (size_t i = 0; i < count; ++i) {
        total += items[i];
    }
    return total;
}

int main(void)
{
    int values[4] = {10, 20, 30, 40};
    int *p = values;
    int (*whole)[4] = &values;
    size_t count = sizeof values / sizeof values[0];

    printf("count=%zu\n", count);
    printf("array_bytes=%zu pointer_bytes=%zu element_bytes=%zu\n",
           sizeof values, sizeof p, sizeof values[0]);
    printf("whole_array_bytes=%zu\n", sizeof *whole);
    printf("step_equals_second=%d\n", p + 1 == &values[1]);
    printf("sum=%d\n", sum_items(values, count));

    /* 本函数约定 count 为零时不访问 items，因此这一调用合法。 */
    printf("empty_sum=%d\n", sum_items(NULL, 0));

    p[1] = 25;
    printf("updated_sum=%d\n", sum_items(values, count));
    assert(count == 4);
    assert(sizeof *whole == sizeof values);
    assert(p + 1 == &values[1]);
    assert(values[1] == 25 && sum_items(values, count) == 105);
    return 0;
}
