// Test if Boost.Python enum registration crashes
#include <boost/python.hpp>

enum Color { RED = 0, GREEN = 1, BLUE = 2 };

BOOST_PYTHON_MODULE(_qi)
{
    boost::python::enum_<Color>("Color")
        .value("RED", RED)
        .value("GREEN", GREEN)
        .value("BLUE", BLUE)
    ;
}
