// Header/implementation split + virtual + override + typedef.
#pragma once

namespace gotchas {

class Shape;  // forward declaration — must canonicalise to the same USR
              // as the Shape definition below

class Shape {
public:
    Shape();
    virtual ~Shape();
    virtual int area() const = 0;

protected:
    int tag_;
};

class Square : public Shape {
public:
    explicit Square(int side);
    int area() const override;

private:
    int side_;
};

// typedef + using-alias both should yield Type(kind=alias) with `typed` edges.
typedef int LegacyArea;
using ModernArea = int;

}  // namespace gotchas
