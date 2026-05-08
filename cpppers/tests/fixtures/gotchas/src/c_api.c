#include "c_api.h"

int compute_area(const dimensions_t* d) {
    if (!d) return 0;
    return d->rows * d->cols;
}
