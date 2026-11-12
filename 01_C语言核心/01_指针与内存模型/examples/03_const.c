#include <assert.h>
#include <stdio.h>

int main(void)
{
    int x = 10;
    int y = 30;
    const int *read_only = &x;
    int *const fixed = &x;
    const int *const fixed_read = &x;
    int snapshot = *fixed_read;

    /* fixed 不能改指向，但它所指的 x 可写。 */
    *fixed = 20;
    /* read_only 可以改指向，但不能经它写入目标对象。 */
    read_only = &y;
    printf("snapshot=%d\n", snapshot);
    printf("x=%d read_only=%d fixed_read=%d\n",
           x, *read_only, *fixed_read);

    /* x 本身不是 const，直接修改 x 仍然合法。 */
    x = 25;
    printf("x_after_alias=%d fixed_read=%d\n", x, *fixed_read);
    assert(snapshot == 10 && x == 25);
    assert(*read_only == 30 && *fixed_read == 25);

    /* 以下三行分别取消注释，会违反对应的 const 约束。 */
    /* *read_only = 7; */
    /* fixed = &y; */
    /* *fixed_read = 7; */
    return 0;
}
