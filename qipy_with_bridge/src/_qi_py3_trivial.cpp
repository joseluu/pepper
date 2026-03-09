// Trivial Boost.Python module to test ABI compatibility
#include <boost/python.hpp>

int add(int a, int b) { return a + b; }

BOOST_PYTHON_MODULE(_qi)
{
    boost::python::def("add", &add);
}
