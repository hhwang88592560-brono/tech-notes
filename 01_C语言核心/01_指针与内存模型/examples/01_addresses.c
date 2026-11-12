#include <assert.h>
#include <limits.h>
#include <stdio.h>

int main(void)
{
    int x = 10;
    int y = 99;
    int *p = &x;
    int *q = p;

    printf("CHAR_BIT=%d\n", CHAR_BIT);
    printf("sizeof_int=%zu\n", sizeof x);
    printf("sizeof_pointer=%zu\n", sizeof p);
    printf("x_addr=%p p_value=%p p_addr=%p\n",
           (void *)&x, (void *)p, (void *)&p);
    printf("initial: x=%d via_p=%d via_q=%d\n", x, *p, *q);

    /* 修改共同指向的对象，不改变两个指针的指向。 */
    *p = 20;
    assert(x == 20 && *q == 20);
    printf("write: x=%d via_q=%d\n", x, *q);

    /* 只改变 p 的指向，q 仍然指向 x。 */
    p = &y;
    *p = 100;
    assert(x == 20 && *q == 20 && y == 100);
    printf("redirect: x=%d y=%d via_p=%d via_q=%d\n",
           x, y, *p, *q);
    return 0;
}
