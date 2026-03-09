/*
 * _qi.so bootstrap module for Python 3
 *
 * This is a minimal wrapper that initializes the qi Python bindings
 * by calling qi::py::export_all() from libqipython3.so
 *
 * Build requirements:
 *   - 32-bit (i386) target
 *   - Python 3.5 development headers
 *   - Boost.Python 1.59 for Python 3
 *   - libqipython3.so from NAOqi 2.7
 *
 * Build command (in appropriate 32-bit environment):
 *   g++ -m32 -shared -fPIC -o _qi.cpython-35m-i386-linux-gnu.so _qi_py3.cpp \
 *       -I/usr/include/python3.5m \
 *       -I/opt/aldebaran/include \
 *       -L/opt/aldebaran/lib -lqipython3 \
 *       -L/usr/lib -lboost_python3 -lpython3.5m \
 *       -Wl,-rpath,/opt/aldebaran/lib \
 *       -std=c++11
 */

#include <Python.h>
#include <boost/python.hpp>
#include <string>

// Forward declaration - implemented in libqipython3.so
namespace qi {
    namespace py {
        void export_all();
    }
    namespace log {
        void addCategory(const std::string& cat);
    }
}

// For Boost.Python 1.59+ with Python 3, use BOOST_PYTHON_MODULE
// This macro automatically creates PyInit__qi for Python 3
BOOST_PYTHON_MODULE(_qi)
{
    // Initialize Python threading support
    PyEval_InitThreads();

    // Register qi log category
    qi::log::addCategory("qi.python");

    // Export all qi bindings (Session, Future, Signal, Property, etc.)
    qi::py::export_all();
}
