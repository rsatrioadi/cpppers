// Defines the methods declared in shape.h. `cursor.get_definition()`
// must canonicalise both decls and definitions to the same USR — that's
// the keystone for header/impl merging.
#include "shape.h"

namespace gotchas {

Shape::Shape() : tag_(0) {}
Shape::~Shape() {}

Square::Square(int side) : side_(side) { tag_ = 1; }

int Square::area() const { return side_ * side_; }

}  // namespace gotchas
