// Pure-C portion. Per §3.4: C exercises a smaller subset of SABO edges
// (no specializes, no overrides, no nested types, no templates) — that's
// expected, not a bug.
#ifndef CPPPERS_C_API_H
#define CPPPERS_C_API_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int rows;
    int cols;
} dimensions_t;

int compute_area(const dimensions_t* d);

#ifdef __cplusplus
}
#endif

#endif  // CPPPERS_C_API_H
