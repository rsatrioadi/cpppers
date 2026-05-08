// Templates + partial specialization. Per §3.4 we want ONE Type node per
// template definition (no per-instantiation node) and parameterizes edges
// from each template parameter Variable to the template Operation/Type.
#pragma once

namespace gotchas {

template <typename T, int N>
class Buffer {
public:
    T data[N];
    int size() const { return N; }
};

// Partial specialization — emitted as a separate Type with `specializes`
// edge back to the primary template.
template <int N>
class Buffer<int, N> {
public:
    int data[N];
    int size() const { return N; }
};

template <typename T>
T identity(T value) { return value; }

}  // namespace gotchas
