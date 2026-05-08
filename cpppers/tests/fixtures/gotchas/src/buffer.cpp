// Anonymous namespace + anonymous struct.
//
// Per §3.4: cursor.get_usr() should produce a stable id for anonymous
// entities (it encodes the location). The fallback synthesised id
// (<file>::anon@<line>:<col>) only triggers when get_usr() returns "".
#include "buffer.h"

namespace gotchas {

namespace {  // anonymous namespace
    struct Helper {  // not strictly anonymous, but inside anonymous ns
        int v;
    };

    struct {  // anonymous struct (declaration only — not legal at namespace
              // scope in C++ without a name; use a typedef to force compile)
        int x;
    } single;

    int helperFunction(int n) {
        Buffer<int, 4> buf;
        return buf.size() + n;
    }
}  // namespace

int useHelpers() {
    Helper h{42};
    return helperFunction(h.v);
}

}  // namespace gotchas
