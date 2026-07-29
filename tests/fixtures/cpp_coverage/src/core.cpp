#include "core.hpp"

int classify_number(int value) {
    if (value < 0)
        return -1;
    if (value == 0)
        return 0;
    return 1;
}
